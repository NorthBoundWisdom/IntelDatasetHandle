from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import AppConfig
from ..index.repository import DatasetRepository
from .audio import extract_audio_features
from .cache import (
    EXTRACTOR_VERSIONS,
    FeatureJobPlan,
    FeatureJobStore,
    sample_modality_fingerprint,
)
from .images import extract_image_features
from .sensor import extract_sensor_features
from .video import extract_video_features


@dataclass(slots=True)
class FeatureExtractionSummary:
    output_path: Path
    samples_requested: int
    samples_completed: int
    samples_failed: int
    feature_columns: int
    jobs_requested: int = 0
    jobs_reused: int = 0
    jobs_executed: int = 0
    jobs_failed: int = 0
    interrupted_jobs_recovered: int = 0
    cache_path: Path | None = None


ProgressCallback = Callable[[int, int, str], None]

_MODALITY_ORDER = ("audio", "video", "sensor", "image")


class FeatureExtractor:
    """Extract deterministic bounded features with a per-modality resumable cache."""

    def __init__(self, config: AppConfig, repository: DatasetRepository | None = None):
        self.config = config
        self.repository = repository or DatasetRepository(config.index_path, config.dataset_root)
        self.cache = FeatureJobStore(config.features_dir / "feature_jobs.sqlite3")

    @staticmethod
    def _metadata_row(sample: dict[str, Any]) -> dict[str, object]:
        return {
            "sample_id": sample.get("sample_id"),
            "session_id": sample.get("session_id"),
            "relpath": sample.get("relpath"),
            "category": sample.get("category"),
            "category_raw": sample.get("category_raw"),
            "is_good": sample.get("is_good"),
            "split": sample.get("split"),
            "weld_type": sample.get("weld_type"),
            "thickness_mm": sample.get("thickness_mm"),
            "steel_type": sample.get("steel_type"),
            "current_a": sample.get("current_a"),
            "voltage_v": sample.get("voltage_v"),
            "gas_bar": sample.get("gas_bar"),
            "robot_speed_cpm": sample.get("robot_speed_cpm"),
        }

    @staticmethod
    def _paths(sample: dict[str, Any], kind: str) -> list[Path]:
        return [
            Path(str(asset["absolute_path"]))
            for asset in sample.get("assets", [])
            if asset.get("kind") == kind
        ]

    @classmethod
    def _extract_modality(cls, sample: dict[str, Any], modality: str) -> dict[str, object]:
        if modality == "audio":
            paths = cls._paths(sample, "audio")
            if not paths:
                raise FileNotFoundError("missing audio asset")
            return extract_audio_features(paths[0])
        if modality == "video":
            paths = cls._paths(sample, "video")
            if not paths:
                raise FileNotFoundError("missing video asset")
            return extract_video_features(paths[0])
        if modality == "sensor":
            paths = cls._paths(sample, "sensor")
            if not paths:
                raise FileNotFoundError("missing sensor asset")
            return extract_sensor_features(paths[0])
        if modality == "image":
            paths = cls._paths(sample, "image")
            if not paths:
                raise FileNotFoundError("missing image assets")
            return extract_image_features(paths)
        raise ValueError(f"Unsupported modality: {modality}")

    @classmethod
    def _execute_sample(
        cls,
        sample: dict[str, Any],
        modalities: tuple[str, ...],
    ) -> dict[str, tuple[dict[str, object] | None, str | None]]:
        results: dict[str, tuple[dict[str, object] | None, str | None]] = {}
        for modality in modalities:
            try:
                results[modality] = (cls._extract_modality(sample, modality), None)
            except Exception as exc:  # isolate one modality from the rest of the sample
                results[modality] = (None, f"{type(exc).__name__}: {exc}")
        return results

    @staticmethod
    def _normalize_modalities(modalities: Iterable[str]) -> tuple[str, ...]:
        selected = {
            "image" if item.casefold() == "images" else item.casefold() for item in modalities
        }
        unknown = selected - set(_MODALITY_ORDER)
        if unknown:
            raise ValueError(f"Unsupported modalities: {sorted(unknown)}")
        return tuple(item for item in _MODALITY_ORDER if item in selected)

    @staticmethod
    def _extractor_config(modality: str) -> dict[str, object]:
        # The current handcrafted extractors have no user-facing parameters. Keep
        # this hook explicit so future window sizes/model names participate in the
        # cache key without making output paths or worker counts invalidate work.
        return {"modality": modality, "bounded": True}

    def _plan_sample(
        self,
        sample: dict[str, Any],
        modalities: tuple[str, ...],
        *,
        force: bool,
    ) -> dict[str, FeatureJobPlan]:
        sample_id = str(sample["sample_id"])
        plans: dict[str, FeatureJobPlan] = {}
        for modality in modalities:
            plans[modality] = self.cache.plan(
                sample_id=sample_id,
                modality=modality,
                sample_fingerprint=sample_modality_fingerprint(sample, modality),
                extractor_name="handcrafted",
                extractor_version=EXTRACTOR_VERSIONS[modality],
                config=self._extractor_config(modality),
                force=force,
            )
        return plans

    def extract(
        self,
        output_path: Path,
        *,
        modalities: Iterable[str] = ("audio", "video", "sensor", "image"),
        split: str | None = None,
        category: str | None = None,
        limit: int | None = None,
        workers: int | None = None,
        progress: ProgressCallback | None = None,
        force: bool = False,
    ) -> FeatureExtractionSummary:
        selected = self._normalize_modalities(modalities)
        if not selected:
            raise ValueError("At least one modality must be selected")

        rows = list(
            self.repository.iter_samples(
                split=split,
                category=category,
                batch_size=500,
            )
        )
        if limit is not None:
            rows = rows[: max(limit, 0)]
        sample_ids = [str(row["sample_id"]) for row in rows]
        total = len(sample_ids)

        recovered = self.cache.recover_interrupted()
        samples: dict[str, dict[str, Any]] = {}
        plans: dict[str, dict[str, FeatureJobPlan]] = {}
        pending: dict[str, tuple[str, ...]] = {}
        jobs_reused = 0

        for sample_id in sample_ids:
            sample = self.repository.get_sample(sample_id)
            if sample is None:
                # A concurrently replaced index can theoretically remove a sample
                # between list and detail reads. Preserve an explicit failed row.
                sample = {
                    "sample_id": sample_id,
                    "session_id": None,
                    "relpath": None,
                    "assets": [],
                }
            samples[sample_id] = sample
            sample_plans = self._plan_sample(sample, selected, force=force)
            plans[sample_id] = sample_plans
            pending_modalities = tuple(
                modality for modality in selected if not sample_plans[modality].reused
            )
            pending[sample_id] = pending_modalities
            jobs_reused += len(selected) - len(pending_modalities)

        worker_count = workers or self.config.scan.workers
        futures: dict[Future[dict[str, tuple[dict[str, object] | None, str | None]]], str] = {}
        completed_samples = 0
        jobs_executed = 0

        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="weld-features"
        ) as executor:
            for sample_id in sample_ids:
                modalities_to_run = pending[sample_id]
                if not modalities_to_run:
                    completed_samples += 1
                    if progress:
                        progress(completed_samples, total, sample_id)
                    continue
                for modality in modalities_to_run:
                    self.cache.mark_running(plans[sample_id][modality])
                jobs_executed += len(modalities_to_run)
                futures[
                    executor.submit(
                        self._execute_sample,
                        samples[sample_id],
                        modalities_to_run,
                    )
                ] = sample_id

            for future in as_completed(futures):
                sample_id = futures[future]
                modalities_to_run = pending[sample_id]
                try:
                    results = future.result()
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    for modality in modalities_to_run:
                        self.cache.store_failure(plans[sample_id][modality], message)
                else:
                    for modality in modalities_to_run:
                        features, error = results.get(
                            modality,
                            (None, "worker did not return modality result"),
                        )
                        if error is not None or features is None:
                            self.cache.store_failure(
                                plans[sample_id][modality],
                                error or "empty feature result",
                            )
                        else:
                            self.cache.store_success(plans[sample_id][modality], features)
                completed_samples += 1
                if progress:
                    progress(completed_samples, total, sample_id)

        extracted: list[dict[str, object]] = []
        jobs_failed = 0
        for sample_id in sample_ids:
            row = self._metadata_row(samples[sample_id])
            errors: dict[str, str] = {}
            for modality in selected:
                result = self.cache.result(plans[sample_id][modality])
                if result.status == "success" and result.features is not None:
                    row.update(result.features)
                else:
                    errors[modality] = result.error or result.status
                    jobs_failed += 1
            row["feature_error"] = json.dumps(errors, ensure_ascii=False) if errors else None
            extracted.append(row)

        frame = pd.DataFrame(extracted).sort_values("sample_id") if extracted else pd.DataFrame()
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = output_path.suffix.casefold()
        if suffix == ".parquet":
            try:
                frame.to_parquet(output_path, index=False)
            except ImportError as exc:
                raise RuntimeError("Parquet export requires 'pip install -e .[parquet]'") from exc
        elif suffix in {".jsonl", ".ndjson"}:
            frame.to_json(output_path, orient="records", lines=True, force_ascii=False)
        else:
            frame.to_csv(output_path, index=False)

        failed_samples = (
            int(frame["feature_error"].notna().sum()) if "feature_error" in frame else 0
        )
        return FeatureExtractionSummary(
            output_path=output_path,
            samples_requested=total,
            samples_completed=len(frame),
            samples_failed=failed_samples,
            feature_columns=len(frame.columns),
            jobs_requested=total * len(selected),
            jobs_reused=jobs_reused,
            jobs_executed=jobs_executed,
            jobs_failed=jobs_failed,
            interrupted_jobs_recovered=recovered,
            cache_path=self.cache.path,
        )
