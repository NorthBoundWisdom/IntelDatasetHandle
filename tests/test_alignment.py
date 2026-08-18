from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from weld_data_workbench.alignment import estimate_sample_alignment, sensor_time_axis
from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.real_schema_fixture import generate_real_schema_fixture


def test_alignment_recovers_known_fixture_onsets(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_real_schema_fixture(raw)
    config = init_workspace(raw, workspace)
    IndexBuilder(config).build(workers=2)
    repo = DatasetRepository(config.index_path, config.dataset_root)

    rows = repo.list_samples(query="04-03-23-0001-00", limit=10)
    assert len(rows) == 1
    sample = repo.get_sample(str(rows[0]["sample_id"]))
    assert sample is not None

    report = estimate_sample_alignment(sample)
    assert report.reference_modality == "sensor"

    audio = report.estimates["audio"]
    video = report.estimates["video"]
    sensor = report.estimates["sensor"]
    assert audio.error is None
    assert video.error is None
    assert sensor.error is None
    assert audio.onset_s is not None
    assert video.onset_s is not None
    assert sensor.onset_s is not None

    # Fixture truth: sensor 0.15 s, video frame 5 / 30 ~= 0.167 s,
    # audio 0.18 s. Estimators are deliberately coarse/bounded.
    assert abs(sensor.onset_s - 0.15) <= 0.03
    assert abs(video.onset_s - (5.0 / 30.0)) <= 0.05
    assert abs(audio.onset_s - 0.18) <= 0.04
    assert report.offsets_s["sensor"] == 0.0
    assert report.offsets_s["audio"] is not None
    assert report.offsets_s["video"] is not None


def test_sensor_time_axis_parses_audited_datetime_without_warning() -> None:
    frame = pd.DataFrame(
        {
            "Date": ["04-03-23", "04-03-23", "04-03-23"],
            "Time": ["10:00:00.000", "10:00:00.010", "10:00:00.020"],
            "Primary Weld Current": [0.0, 1.0, 2.0],
        }
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        axis, source = sensor_time_axis(frame)

    assert caught == []
    assert axis is not None
    assert axis.tolist() == pytest.approx([0.0, 0.01, 0.02])
    assert source.endswith(":%m-%d-%y %H:%M:%S.%f")


def test_sensor_time_axis_refuses_to_invent_sampling_rate() -> None:
    frame = pd.DataFrame({"Primary Weld Current": [0.0, 1.0, 2.0]})
    axis, source = sensor_time_axis(frame)
    assert axis is None
    assert source == "unresolved"
