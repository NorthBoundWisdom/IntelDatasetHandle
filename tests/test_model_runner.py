from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from weld_data_workbench.ml.model_runner import (
    ModelFitContext,
    ModelPredictContext,
    ModelRunSpec,
    validate_runner_predictions,
)


class FakeRunner:
    spec = ModelRunSpec(name="sensor-smoke", modalities=("sensor",), batch_size=8)

    def fit(self, context: ModelFitContext) -> dict[str, object]:
        return {"train": len(context.train_sample_ids)}

    def predict(self, context: ModelPredictContext) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sample_id": list(context.sample_ids),
                "score_sensor": [0.1] * len(context.sample_ids),
                "anomaly_score": [0.1] * len(context.sample_ids),
            }
        )

    def save(self, output: Path) -> Path:
        return output


def test_model_run_spec_and_prediction_identity_contract() -> None:
    runner = FakeRunner()
    frame = runner.predict(
        ModelPredictContext(
            workspace=Path("."),
            dataset_snapshot_id="snapshot",
            split_artifact_id="split",
            sample_ids=("a", "b"),
        )
    )
    normalized = validate_runner_predictions(runner, frame, expected_sample_ids=("a", "b"))
    assert list(normalized["sample_id"]) == ["a", "b"]
    assert runner.spec.to_config()["modalities"] == ["sensor"]


def test_model_runner_rejects_prediction_identity_drift() -> None:
    runner = FakeRunner()
    frame = pd.DataFrame({"sample_id": ["a"], "score_sensor": [0.1]})
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_runner_predictions(runner, frame, expected_sample_ids=("a", "b"))


def test_model_run_spec_rejects_duplicate_modalities() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        ModelRunSpec(name="bad", modalities=("audio", "audio")).validate()
