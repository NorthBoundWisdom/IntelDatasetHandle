"""Stable research-runner contracts for learned unimodal and fused models.

The workbench owns dataset identity, split/provenance, prediction artifacts, and evaluation.
Concrete research models own decoding, preprocessing, fitting, and score generation. This
module keeps that boundary explicit so model experiments do not grow one-off output formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from ..prediction_contract import normalize_prediction_frame


@dataclass(frozen=True, slots=True)
class ModelRunSpec:
    name: str
    modalities: tuple[str, ...]
    seed: int = 0
    device: str = "cpu"
    batch_size: int = 1
    config: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("ModelRunSpec.name must be non-empty")
        if not self.modalities:
            raise ValueError("ModelRunSpec.modalities must be non-empty")
        if len(set(self.modalities)) != len(self.modalities):
            raise ValueError("ModelRunSpec.modalities must not contain duplicates")
        if self.batch_size < 1:
            raise ValueError("ModelRunSpec.batch_size must be positive")
        if not self.device.strip():
            raise ValueError("ModelRunSpec.device must be non-empty")

    def to_config(self) -> dict[str, Any]:
        self.validate()
        return {
            "name": self.name,
            "modalities": list(self.modalities),
            "seed": self.seed,
            "device": self.device,
            "batch_size": self.batch_size,
            "config": self.config,
        }


@dataclass(frozen=True, slots=True)
class ModelFitContext:
    workspace: Path
    dataset_snapshot_id: str
    split_artifact_id: str | None
    artifact_dir: Path
    train_sample_ids: tuple[str, ...]
    validation_sample_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelPredictContext:
    workspace: Path
    dataset_snapshot_id: str
    split_artifact_id: str | None
    sample_ids: tuple[str, ...]


@runtime_checkable
class ModelRunner(Protocol):
    """Minimal contract concrete research models must implement."""

    @property
    def spec(self) -> ModelRunSpec: ...

    def fit(self, context: ModelFitContext) -> dict[str, Any]:
        """Fit only from training data, with validation reserved for calibration/tuning."""
        ...

    def predict(self, context: ModelPredictContext) -> pd.DataFrame:
        """Return one row per sample using the common prediction contract."""
        ...

    def save(self, output: Path) -> Path:
        """Persist model-specific state under an experiment artifact directory."""
        ...


def validate_runner_predictions(
    runner: ModelRunner,
    frame: pd.DataFrame,
    *,
    expected_sample_ids: tuple[str, ...] | list[str] | None = None,
) -> pd.DataFrame:
    """Normalize a runner result and enforce identity/modality fields before registry writes."""

    runner.spec.validate()
    normalized = normalize_prediction_frame(frame)
    if expected_sample_ids is not None:
        expected = set(str(value) for value in expected_sample_ids)
        actual = set(normalized["sample_id"].astype(str))
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            raise ValueError(
                "Prediction sample identity mismatch: "
                f"missing={missing[:10]} extra={extra[:10]}"
            )

    for modality in runner.spec.modalities:
        score_column = f"score_{modality}"
        if score_column not in normalized.columns and "anomaly_score" not in normalized.columns:
            raise ValueError(
                f"Runner {runner.spec.name} must emit {score_column!r} or 'anomaly_score'"
            )
    return normalized
