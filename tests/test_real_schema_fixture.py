from __future__ import annotations

from pathlib import Path

from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.real_schema_fixture import generate_real_schema_fixture
from weld_data_workbench.splits import audit_upstream_split


def test_generated_real_schema_fixture_covers_audited_edge_cases(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    fixture = generate_real_schema_fixture(raw)
    assert fixture.samples == 8
    assert fixture.sessions == 4

    config = init_workspace(raw, workspace)
    summary = IndexBuilder(config).build(workers=2)
    assert summary.sample_count == 8

    repo = DatasetRepository(config.index_path, config.dataset_root)
    stats = repo.stats()
    assert stats["total_samples"] == 8
    assert stats["total_sessions"] == 4
    assert stats["by_split"] == {"test": 3, "train": 2, "validation": 3}
    assert stats["by_category"]["Good"] == 3
    assert stats["audio_sample_rates_hz"]["16000"] == 5
    assert stats["audio_sample_rates_hz"]["22050"] == 1

    issue_codes = {item["code"] for item in repo.issues()}
    assert "missing_image" in issue_codes
    assert "unexpected_image_count" in issue_codes
    assert "video_probe_failed" in issue_codes
    assert "audio_probe_failed" in issue_codes
    assert "image_probe_failed" in issue_codes

    # Two different session directories intentionally use the same sample basename;
    # discovery must keep both records rather than silently overwriting one.
    duplicate_basename_rows = [
        row
        for row in repo.list_samples(limit=100)
        if str(row["relpath"]).endswith("/04-03-23-0010-11")
    ]
    assert len(duplicate_basename_rows) == 2
    assert len({row["sample_id"] for row in duplicate_basename_rows}) == 2

    # SUBDIRS is already session-prefixed in the audited public manifest shape.
    # Regression guard: DIRECTORY must never be concatenated a second time.
    assert all(
        str(row["relpath"]).count(str(row["session_id"])) == 1
        for row in repo.list_samples(limit=100)
    )

    audit = audit_upstream_split(config)
    assert audit.has_session_leakage
    assert "10_crater_cracks_7_03-20-23_Fe410" in audit.cross_split_sessions
