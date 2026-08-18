from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from weld_data_workbench.experiments import ExperimentRegistry


def test_experiment_registry_persists_provenance_predictions_and_metrics(tmp_path: Path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments")
    handle = registry.create(
        name="smoke",
        config={"model": "dummy", "alpha": 0.5},
        dataset_snapshot_id="snapshot-123",
        split_artifact_id="split-456",
        git_sha="deadbeef",
        seeds={"numpy": 7},
    )

    assert handle.config_path.is_file()
    assert handle.provenance_path.is_file()
    assert handle.environment_path.is_file()
    assert handle.artifacts_dir.is_dir()

    provenance = json.loads(handle.provenance_path.read_text(encoding="utf-8"))
    assert provenance["dataset_snapshot_id"] == "snapshot-123"
    assert provenance["split_artifact_id"] == "split-456"

    frame = pd.DataFrame(
        {
            "sample_id": ["a", "b"],
            "is_anomaly": [0, 1],
            "anomaly_score": [0.1, 0.9],
        }
    )
    prediction_path = registry.write_predictions(handle, frame)
    metrics_path = registry.write_metrics(handle, {"roc_auc": 1.0})

    assert prediction_path.is_file()
    assert metrics_path.is_file()
    assert registry.list()[0].experiment_id == handle.experiment_id
