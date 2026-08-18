from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.policy_compare import (
    compare_split_policies,
    load_verified_holdout_artifact,
)
from weld_data_workbench.real_schema_fixture import generate_real_schema_fixture
from weld_data_workbench.splits import write_split_artifact


def test_policy_comparison_exposes_upstream_session_overlap(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_real_schema_fixture(raw)
    config = init_workspace(raw, workspace)
    IndexBuilder(config).build(workers=2)
    repo = DatasetRepository(config.index_path, config.dataset_root)

    predictions = pd.DataFrame(
        [
            {
                "sample_id": row["sample_id"],
                "anomaly_score": 0.1 if row["is_good"] else 0.9,
            }
            for row in repo.list_samples(limit=100)
        ]
    )
    split_path = tmp_path / "session-disjoint.json"
    artifact = write_split_artifact(
        config,
        split_path,
        seed=17,
        train=0.5,
        validation=0.25,
        test=0.25,
        strategy="balanced",
    )
    verified = load_verified_holdout_artifact(split_path)
    assert verified["split_artifact_id"] == artifact["split_artifact_id"]

    report = compare_split_policies(
        config,
        predictions,
        verified,
        bootstrap_iterations=0,
    )
    assert report["prediction_samples"] == 9
    assert report["policies"]["upstream"]["session_overlap"]["sessions_crossing_any_partition"] > 0
    assert (
        report["policies"]["upstream"]["session_overlap"]["pairwise"]["validation_test"]["count"]
        > 0
    )
    assert (
        report["policies"]["session_disjoint"]["session_overlap"]["sessions_crossing_any_partition"]
        == 0
    )
    assert (
        report["policies"]["upstream"]["metrics"]["evaluation_combined"]["overall"]["roc_auc"]
        == 1.0
    )


def test_split_artifact_verification_rejects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "tampered.json"
    path.write_text(
        json.dumps(
            {
                "split_artifact_id": "0" * 64,
                "schema_version": 1,
                "mode": "holdout",
                "seed": 0,
                "parameters": {},
                "session_assignments": {},
                "sample_assignments": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        load_verified_holdout_artifact(path)
