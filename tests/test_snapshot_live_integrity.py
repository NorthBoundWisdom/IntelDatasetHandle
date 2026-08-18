from __future__ import annotations

from pathlib import Path

import pytest

from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.provenance import (
    SnapshotVerificationError,
    build_snapshot_payload,
    create_snapshot,
    verify_snapshot,
)
from weld_data_workbench.synthetic import generate_synthetic_dataset


def test_snapshot_verification_detects_asset_stat_drift(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_synthetic_dataset(raw, profile="tiny")
    config = init_workspace(raw, workspace)
    IndexBuilder(config).build(workers=2)

    snapshot = create_snapshot(config)
    assert snapshot.payload["live_asset_integrity"]["missing"] == 0
    assert snapshot.payload["live_asset_integrity"]["stat_mismatch"] == 0
    assert snapshot.payload["video_resolutions"]
    assert snapshot.payload["missing_modalities"] == {
        "video": 0,
        "audio": 0,
        "sensor": 0,
        "image": 0,
    }

    repo = DatasetRepository(config.index_path, config.dataset_root)
    sample = repo.get_sample("good-train-000")
    assert sample is not None
    audio = next(asset for asset in sample["assets"] if asset["kind"] == "audio")
    Path(audio["absolute_path"]).touch()

    current = build_snapshot_payload(config)
    assert current["live_asset_integrity"]["stat_mismatch"] == 1
    with pytest.raises(SnapshotVerificationError, match="Snapshot mismatch"):
        verify_snapshot(config, snapshot)
