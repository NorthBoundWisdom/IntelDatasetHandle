from __future__ import annotations

from pathlib import Path

import pandas as pd

from weld_data_workbench.io.manifest import (
    candidates_from_manifest,
    discover_manifest,
    parse_path_list,
    read_manifest,
)


def test_path_list_parsing() -> None:
    assert parse_path_list('["a", "b"]') == ["a", "b"]
    assert parse_path_list("a;b") == ["a", "b"]
    assert parse_path_list(4) == []


def test_manifest_discovery_and_resolution(synthetic_root: Path) -> None:
    path = discover_manifest(
        synthetic_root,
        preferred_names=["manifest.csv"],
        max_depth=3,
    )
    assert path == synthetic_root / "manifest.csv"
    document = read_manifest(path)
    assert "CATEGORY" in document.matched_columns
    candidates = candidates_from_manifest(document, synthetic_root)
    assert len(candidates) == len(document.dataframe)
    assert all(candidate.sample_path.exists() for candidate in candidates)
    assert all(
        candidate.metadata.split in {"train", "validation", "test"} for candidate in candidates
    )


def test_manifest_paths_are_relative_to_manifest_and_do_not_duplicate_directory(
    tmp_path: Path,
) -> None:
    extraction_root = tmp_path / "extracted"
    dataset_root = extraction_root / "wrapper" / "dataset"
    sample_path = dataset_root / "session-a" / "sample-001"
    (sample_path / "images").mkdir(parents=True)
    for filename in ("sample-001.avi", "sample-001.flac", "sample-001.csv"):
        (sample_path / filename).touch()

    manifest_path = dataset_root / "manifest.csv"
    pd.DataFrame(
        [
            {
                "CATEGORY": "Good",
                "DIRECTORY": "session-a",
                # The real Intel manifest stores a root-relative path here,
                # including DIRECTORY as its first component.
                "SUBDIRS": "session-a/sample-001",
                "SAMPLES": 1,
                "SPLIT": "TRAIN",
            }
        ]
    ).to_csv(manifest_path, index=False)

    candidates = candidates_from_manifest(read_manifest(manifest_path), extraction_root)

    assert len(candidates) == 1
    assert candidates[0].sample_path == sample_path
    assert candidates[0].relpath == "wrapper/dataset/session-a/sample-001"
