from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import pandas as pd


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _safe_name(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_." else "-" for character in value
    )
    return cleaned.strip("-.") or "experiment"


def environment_snapshot() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for package in (
        "numpy",
        "pandas",
        "scikit-learn",
        "scipy",
        "opencv-python-headless",
        "soundfile",
        "torch",
    ):
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            continue
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "packages": packages,
    }


@dataclass(frozen=True, slots=True)
class ExperimentHandle:
    experiment_id: str
    root: Path

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def provenance_path(self) -> Path:
        return self.root / "provenance.json"

    @property
    def predictions_path(self) -> Path:
        return self.root / "predictions.parquet"

    @property
    def metrics_path(self) -> Path:
        return self.root / "metrics.json"

    @property
    def environment_path(self) -> Path:
        return self.root / "environment.json"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"


class ExperimentRegistry:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        name: str,
        config: dict[str, Any],
        dataset_snapshot_id: str,
        split_artifact_id: str | None = None,
        git_sha: str | None = None,
        seeds: dict[str, int] | None = None,
        notes: str | None = None,
    ) -> ExperimentHandle:
        now = datetime.now(UTC)
        identity = {
            "name": name,
            "config": config,
            "dataset_snapshot_id": dataset_snapshot_id,
            "split_artifact_id": split_artifact_id,
            "git_sha": git_sha,
            "seeds": seeds or {},
            "timestamp_ns": now.timestamp(),
            "pid": os.getpid(),
        }
        suffix = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:10]
        experiment_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{_safe_name(name)}-{suffix}"
        experiment_root = self.root / experiment_id
        experiment_root.mkdir(parents=False, exist_ok=False)
        handle = ExperimentHandle(experiment_id=experiment_id, root=experiment_root)
        handle.artifacts_dir.mkdir()

        handle.config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        provenance = {
            "experiment_schema_version": 1,
            "experiment_id": experiment_id,
            "created_at": now.isoformat(),
            "dataset_snapshot_id": dataset_snapshot_id,
            "split_artifact_id": split_artifact_id,
            "git_sha": git_sha,
            "seeds": seeds or {},
            "notes": notes,
        }
        handle.provenance_path.write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        handle.environment_path.write_text(
            json.dumps(environment_snapshot(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return handle

    @staticmethod
    def write_predictions(handle: ExperimentHandle, frame: pd.DataFrame) -> Path:
        try:
            frame.to_parquet(handle.predictions_path, index=False)
            return handle.predictions_path
        except (ImportError, ModuleNotFoundError):
            fallback = handle.root / "predictions.csv"
            frame.to_csv(fallback, index=False)
            return fallback

    @staticmethod
    def write_metrics(handle: ExperimentHandle, metrics: dict[str, Any]) -> Path:
        handle.metrics_path.write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return handle.metrics_path

    def list(self) -> list[ExperimentHandle]:
        handles: list[ExperimentHandle] = []
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and (child / "provenance.json").is_file():
                handles.append(ExperimentHandle(child.name, child))
        return handles
