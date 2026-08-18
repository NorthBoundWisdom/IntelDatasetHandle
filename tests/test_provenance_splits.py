from __future__ import annotations

import json
from pathlib import Path

import pytest

from weld_data_workbench.config import AppConfig
from weld_data_workbench.provenance import (
    SnapshotVerificationError,
    create_snapshot,
    load_snapshot,
    verify_snapshot,
)
from weld_data_workbench.splits import (
    audit_upstream_split,
    grouped_kfold_assignments,
    sample_assignments_from_sessions,
    session_holdout_assignments,
    write_split_artifact,
)


def test_snapshot_is_deterministic_and_verifiable(
    indexed_workspace: tuple[AppConfig, object], tmp_path: Path
) -> None:
    config, _summary = indexed_workspace
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first = create_snapshot(config, output=first_path)
    second = create_snapshot(config, output=second_path)

    assert first.snapshot_id == second.snapshot_id
    assert first.payload == second.payload
    assert first.payload["counts"]["samples"] > 0
    assert first.payload["canonical_index_sha256"]

    loaded = load_snapshot(first_path)
    verify_snapshot(config, loaded)


def test_snapshot_rejects_tampered_document(
    indexed_workspace: tuple[AppConfig, object], tmp_path: Path
) -> None:
    config, _summary = indexed_workspace
    path = tmp_path / "snapshot.json"
    create_snapshot(config, output=path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"]["counts"]["samples"] += 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SnapshotVerificationError, match="internally inconsistent"):
        verify_snapshot(config, load_snapshot(path))


def test_session_holdout_is_deterministic_and_disjoint(
    indexed_workspace: tuple[AppConfig, object],
) -> None:
    config, _summary = indexed_workspace
    first = session_holdout_assignments(config, seed=42)
    second = session_holdout_assignments(config, seed=42)
    changed = session_holdout_assignments(config, seed=43)

    assert first == second
    assert first
    assert set(first.values()) <= {"train", "validation", "test"}
    assert set(first) == set(changed)

    samples = sample_assignments_from_sessions(config, first)
    assert samples
    assert set(samples.values()) <= {"train", "validation", "test"}


def test_grouped_kfold_assigns_each_session_once(
    indexed_workspace: tuple[AppConfig, object],
) -> None:
    config, _summary = indexed_workspace
    assignments = grouped_kfold_assignments(config, folds=3, seed=7)
    assert assignments
    assert set(assignments.values()) <= {0, 1, 2}


def test_split_artifact_has_stable_identity(
    indexed_workspace: tuple[AppConfig, object], tmp_path: Path
) -> None:
    config, _summary = indexed_workspace
    first = write_split_artifact(config, tmp_path / "a.json", seed=5)
    second = write_split_artifact(config, tmp_path / "b.json", seed=5)

    assert first["split_artifact_id"] == second["split_artifact_id"]
    assert first["session_assignments"] == second["session_assignments"]
    assert first["sample_assignments"] == second["sample_assignments"]


def test_leakage_audit_shape(indexed_workspace: tuple[AppConfig, object]) -> None:
    config, _summary = indexed_workspace
    audit = audit_upstream_split(config)
    payload = audit.to_dict()

    assert payload["total_sessions"] > 0
    assert payload["cross_split_session_count"] == len(audit.cross_split_sessions)
    assert isinstance(payload["exact_asset_hash_cross_split"], dict)
