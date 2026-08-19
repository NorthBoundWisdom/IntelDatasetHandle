from __future__ import annotations

import json
from pathlib import Path

from weld_data_workbench.alignment_triage import (
    triage_alignment_batch,
    write_alignment_triage_csv,
    write_alignment_triage_json,
)


def test_alignment_triage_prioritizes_time_gap_and_large_spread(tmp_path: Path) -> None:
    source = {
        "schema_version": 1,
        "samples": [
            {
                "sample_id": "good",
                "session_id": "s1",
                "quality": "good",
                "start_spread_s": 0.1,
                "duration_spread_s": 0.2,
            },
            {
                "sample_id": "poor",
                "session_id": "s2",
                "quality": "poor",
                "start_spread_s": 6.0,
                "duration_spread_s": 8.0,
            },
            {
                "sample_id": "gap",
                "session_id": "s3",
                "quality": "poor",
                "start_spread_s": 3.0,
                "duration_spread_s": 2.0,
                "sensor_time_gap_detected": True,
                "sensor_max_time_gap_s": 117.0,
            },
        ],
    }

    report = triage_alignment_batch(source, limit=2)

    assert report.sample_count == 3
    assert report.selected_count == 2
    assert report.cases[0].sample_id == "gap"
    assert "sensor_time_gap" in report.cases[0].reasons
    assert report.cases[1].sample_id == "poor"
    assert "large_onset_spread" in report.cases[1].reasons
    assert all(case.sample_id != "good" for case in report.cases)

    json_path = write_alignment_triage_json(report, tmp_path / "triage.json")
    csv_path = write_alignment_triage_csv(report, tmp_path / "triage.csv")
    assert json.loads(json_path.read_text())["selected_count"] == 2
    assert "sensor_time_gap" in csv_path.read_text()


def test_alignment_triage_can_include_good_rows() -> None:
    report = triage_alignment_batch(
        {"samples": [{"sample_id": "good", "quality": "good"}]},
        include_good=True,
    )
    assert report.selected_count == 1
    assert report.cases[0].reasons == ("low_priority_review",)
