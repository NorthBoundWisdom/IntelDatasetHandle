from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from weld_data_workbench.alignment_batch import (
    AlignmentBatchOptions,
    run_alignment_batch,
    write_alignment_batch_csv,
    write_alignment_batch_json,
    write_alignment_plots,
)
from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.infrastructure_cli import app
from weld_data_workbench.real_schema_fixture import generate_real_schema_fixture


def _real_schema_repository(tmp_path: Path) -> tuple[DatasetRepository, Path]:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_real_schema_fixture(raw)
    config = init_workspace(raw, workspace)
    IndexBuilder(config).build(workers=2)
    return DatasetRepository(config.index_path, config.dataset_root), workspace


def test_alignment_batch_summarizes_good_samples_and_writes_artifacts(tmp_path: Path) -> None:
    repository, _workspace = _real_schema_repository(tmp_path)
    report = run_alignment_batch(
        repository,
        options=AlignmentBatchOptions(category="Good", workers=2, batch_size=2),
    )

    assert report.schema_version == 1
    assert report.options["category"] == "Good"
    assert report.summary["samples"] == 3
    assert sum(report.summary["quality_counts"].values()) == 3
    assert report.summary["modalities"]["sensor"]["onset_success"] == 3
    assert report.summary["modalities"]["audio"]["onset_success"] == 3
    assert report.summary["modalities"]["video"]["onset_success"] == 3
    assert report.summary["modalities"]["sensor"]["interval_success"] == 3
    assert report.summary["start_spread_s"]["count"] == 3
    assert report.summary["duration_spread_s"]["count"] == 3
    assert report.summary["sessions"]["sessions"] == 2
    assert "train" in report.summary["by_split"]
    assert "test" in report.summary["by_split"]
    assert "Good" in report.summary["by_category"]

    for row in report.samples:
        assert row["category"] == "Good"
        assert row["sensor_onset_s"] is not None
        assert row["audio_onset_s"] is not None
        assert row["video_onset_s"] is not None
        assert row["sensor_duration_s"] is not None
        assert row["audio_duration_s"] is not None
        assert row["video_duration_s"] is not None
        assert row["quality"] in {"good", "warning", "poor"}

    json_path = write_alignment_batch_json(report, tmp_path / "reports" / "alignment.json")
    csv_path = write_alignment_batch_csv(report, tmp_path / "reports" / "alignment.csv")
    plots = write_alignment_plots(report, tmp_path / "reports" / "plots")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["samples"] == 3
    assert len(payload["samples"]) == 3
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert "sensor_onset_s" in rows[0]
    assert "duration_spread_s" in rows[0]
    assert {path.name for path in plots} == {
        "start-offsets.png",
        "start-spread-histogram.png",
        "active-durations.png",
    }
    assert all(path.stat().st_size > 0 for path in plots)


def test_alignment_batch_keeps_corrupt_samples_as_rows(tmp_path: Path) -> None:
    repository, _workspace = _real_schema_repository(tmp_path)
    report = run_alignment_batch(
        repository,
        options=AlignmentBatchOptions(workers=3, limit=9, batch_size=4),
    )

    assert report.summary["samples"] == 9
    assert len(report.samples) == 9
    assert report.samples == sorted(report.samples, key=lambda row: row["sample_id"])
    assert sum(report.summary["quality_counts"].values()) == 9

    corrupt = [row for row in report.samples if row["health_status"] == "error"]
    assert corrupt
    assert any(
        row.get("audio_error") or row.get("video_error") or row.get("sensor_error")
        for row in corrupt
    )
    assert report.summary["modalities"]["audio"]["top_errors"]
    assert report.summary["sessions"]["worst_sessions"]


def test_alignment_batch_limit_and_split_filter_are_deterministic(tmp_path: Path) -> None:
    repository, _workspace = _real_schema_repository(tmp_path)
    first = run_alignment_batch(
        repository,
        options=AlignmentBatchOptions(split="test", limit=2, workers=1, batch_size=1),
    )
    second = run_alignment_batch(
        repository,
        options=AlignmentBatchOptions(split="test", limit=2, workers=2, batch_size=5),
    )

    assert len(first.samples) == 2
    assert [row["sample_id"] for row in first.samples] == [
        row["sample_id"] for row in second.samples
    ]
    assert all(row["split"] == "test" for row in first.samples)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (AlignmentBatchOptions(limit=0), "limit"),
        (AlignmentBatchOptions(workers=0), "workers"),
        (AlignmentBatchOptions(batch_size=0), "batch_size"),
    ],
)
def test_alignment_batch_options_validate(options: AlignmentBatchOptions, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        options.validate()


def test_alignment_batch_cli_writes_json_and_csv_without_plots(tmp_path: Path) -> None:
    _repository, workspace = _real_schema_repository(tmp_path)
    output = tmp_path / "cli" / "batch.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "alignment-batch",
            "--workspace",
            str(workspace),
            "--category",
            "Good",
            "--limit",
            "2",
            "--workers",
            "2",
            "--output",
            str(output),
            "--no-plots",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert output.with_suffix(".csv").is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["samples"] == 2
    assert '"plots": []' in result.output
