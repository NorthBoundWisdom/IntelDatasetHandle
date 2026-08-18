from __future__ import annotations

import shutil
from pathlib import Path

from weld_data_workbench.config import init_workspace
from weld_data_workbench.duplicates import scan_near_duplicates
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.real_schema_fixture import generate_real_schema_fixture


def test_near_duplicate_scan_finds_cross_split_copied_image_bundle(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_real_schema_fixture(raw)

    source_dir = raw / "10_good_01_03-20-23_Fe410" / "04-03-23-0001-00" / "images"
    target_dir = raw / "10_porosity_03-21-23_Fe410" / "04-03-23-0010-11" / "images"
    shutil.copytree(source_dir, target_dir)

    config = init_workspace(raw, workspace)
    IndexBuilder(config).build(workers=2)
    repo = DatasetRepository(config.index_path, config.dataset_root)

    source_row = repo.list_samples(query="10_good_01_03-20-23_Fe410/04-03-23-0001-00", limit=5)[0]
    target_row = repo.list_samples(query="10_porosity_03-21-23_Fe410/04-03-23-0010-11", limit=5)[0]
    source_id = str(source_row["sample_id"])
    target_id = str(target_row["sample_id"])

    first = scan_near_duplicates(
        config,
        kinds=("image",),
        image_distance=0,
        cross_split_only=True,
        max_pairs=1_000,
    )
    assert first.summary.assets_considered == 45
    assert first.summary.signatures_computed == 45
    assert first.summary.signatures_reused == 0
    assert first.summary.signature_failures == 1  # intentionally corrupt JPEG in the fixture

    expected_key = tuple(sorted((source_id, target_id)))
    matching = [
        pair
        for pair in first.pairs
        if (pair["sample_a"], pair["sample_b"]) == expected_key
    ]
    assert len(matching) == 1
    pair = matching[0]
    assert pair["quality"] == "strong"
    assert pair["image_matches"] == 5
    assert pair["video_matches"] == 0
    assert all(item["hamming_distance"] == 0 for item in pair["evidence"])

    second = scan_near_duplicates(
        config,
        kinds=("image",),
        image_distance=0,
        cross_split_only=True,
        max_pairs=1_000,
    )
    assert second.summary.signatures_computed == 0
    assert second.summary.signatures_reused == 45
    assert second.summary.signature_failures == 1
    assert any(
        (pair["sample_a"], pair["sample_b"]) == expected_key for pair in second.pairs
    )
