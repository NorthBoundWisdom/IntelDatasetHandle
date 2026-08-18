from __future__ import annotations

import warnings
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest
import soundfile as sf

from weld_data_workbench.alignment import (
    _bridge_short_false_gaps,
    _robust_activity_interval,
    estimate_audio_onset,
    estimate_sample_alignment,
    estimate_sensor_onset,
    estimate_video_onset,
    sensor_time_axis,
    write_alignment_report,
)
from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.real_schema_fixture import generate_real_schema_fixture


def test_robust_activity_interval_finds_release_and_bridges_small_gap() -> None:
    time_axis = np.arange(100, dtype=np.float64) * 0.01
    values = np.zeros(100, dtype=np.float64)
    values[20:70] = 10.0
    values[42] = 0.0

    onset, end, confidence, details = _robust_activity_interval(
        values,
        time_axis_s=time_axis,
        bridge_gap_points=1,
    )

    assert onset == pytest.approx(0.20)
    assert end == pytest.approx(0.70)
    assert confidence > 0.5
    assert details["end_censored"] is False
    assert details["raw_active_points"] == 49
    assert details["bridged_active_points"] == 50


def test_robust_activity_interval_marks_recording_end_censored() -> None:
    time_axis = np.arange(50, dtype=np.float64) * 0.02
    values = np.zeros(50, dtype=np.float64)
    values[10:] = 4.0

    onset, end, confidence, details = _robust_activity_interval(values, time_axis_s=time_axis)

    assert onset == pytest.approx(0.20)
    assert end == pytest.approx(1.00)
    assert confidence > 0.0
    assert details["end_censored"] is True
    assert details["median_time_step_s"] == pytest.approx(0.02)


def test_bridge_short_false_gaps_preserves_long_release() -> None:
    mask = np.asarray([False, True, True, False, True, True, False, False, True])
    bridged = _bridge_short_false_gaps(mask, 1)
    assert bridged.tolist() == [False, True, True, True, True, True, False, False, True]


def test_audio_activity_estimate_recovers_quiet_tail(tmp_path: Path) -> None:
    sample_rate = 16_000
    duration = 1.0
    time_axis = np.arange(int(sample_rate * duration), dtype=np.float64) / sample_rate
    audio = np.zeros_like(time_axis, dtype=np.float32)
    active = (time_axis >= 0.20) & (time_axis < 0.60)
    audio[active] = (0.3 * np.sin(2 * np.pi * 700.0 * time_axis[active])).astype(np.float32)
    path = tmp_path / "interval.flac"
    sf.write(path, audio, sample_rate, format="FLAC")

    estimate = estimate_audio_onset(path, frame_ms=20.0, max_seconds=2.0)

    assert estimate.error is None
    assert estimate.onset_s == pytest.approx(0.20, abs=0.03)
    assert estimate.end_s == pytest.approx(0.60, abs=0.04)
    assert estimate.duration_s == pytest.approx(0.40, abs=0.05)
    assert estimate.details["end_censored"] is False


def test_sensor_activity_estimate_recovers_explicit_end(tmp_path: Path) -> None:
    time_axis = np.arange(100, dtype=np.float64) * 0.01
    current = np.zeros(100, dtype=np.float64)
    current[(time_axis >= 0.15) & (time_axis < 0.65)] = 180.0
    path = tmp_path / "sensor.csv"
    pd.DataFrame(
        {
            "elapsed_s": time_axis,
            "Primary Weld Current": current,
            "Secondary Weld Voltage": np.where(current > 0, 24.0, 0.0),
        }
    ).to_csv(path, index=False)

    estimate = estimate_sensor_onset(path)

    assert estimate.error is None
    assert estimate.onset_s == pytest.approx(0.15, abs=0.02)
    assert estimate.end_s == pytest.approx(0.65, abs=0.03)
    assert estimate.duration_s == pytest.approx(0.50, abs=0.04)
    assert estimate.details["time_axis_source"] == "numeric:elapsed_s"
    assert estimate.details["end_censored"] is False


def test_video_activity_estimate_recovers_bright_interval(tmp_path: Path) -> None:
    path = tmp_path / "interval.avi"
    fps = 30.0
    width, height = 96, 64
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV MJPG writer unavailable")
    for index in range(60):
        level = 240 if 10 <= index < 36 else 15
        frame = np.full((height, width, 3), level, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    estimate = estimate_video_onset(path, max_seconds=3.0)

    assert estimate.error is None
    assert estimate.onset_s == pytest.approx(10 / fps, abs=1 / fps)
    assert estimate.end_s == pytest.approx(36 / fps, abs=2 / fps)
    assert estimate.duration_s == pytest.approx(26 / fps, abs=3 / fps)
    assert estimate.details["end_censored"] is False


def test_alignment_recovers_known_fixture_onsets_and_intervals(tmp_path: Path) -> None:
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
    assert report.schema_version == 2
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

    assert abs(sensor.onset_s - 0.15) <= 0.03
    assert abs(video.onset_s - (5.0 / 30.0)) <= 0.05
    assert abs(audio.onset_s - 0.18) <= 0.04
    assert report.offsets_s["sensor"] == 0.0
    assert report.offsets_s["audio"] is not None
    assert report.offsets_s["video"] is not None

    assert sensor.end_s is not None
    assert audio.end_s is not None
    assert video.end_s is not None
    assert sensor.duration_s is not None and sensor.duration_s > 0
    assert audio.duration_s is not None and audio.duration_s > 0
    assert video.duration_s is not None and video.duration_s > 0
    assert report.end_offsets_s["sensor"] == 0.0
    assert report.start_spread_s is not None
    assert report.end_spread_s is not None
    assert report.duration_spread_s is not None
    assert report.quality in {"good", "warning", "poor"}

    output = tmp_path / "alignment.json"
    write_alignment_report(report, output)
    payload = output.read_text(encoding="utf-8")
    assert '"schema_version": 2' in payload
    assert '"duration_spread_s"' in payload
    assert '"end_censored"' in payload


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


def test_sensor_time_axis_accepts_bare_clock_time() -> None:
    frame = pd.DataFrame(
        {
            "Time": ["10:00:00.000", "10:00:00.025", "10:00:00.050"],
            "Primary Weld Current": [0.0, 1.0, 2.0],
        }
    )
    axis, source = sensor_time_axis(frame)
    assert axis is not None
    assert axis.tolist() == pytest.approx([0.0, 0.025, 0.05])
    assert source == "timedelta:Time"


def test_sensor_time_axis_refuses_to_invent_sampling_rate() -> None:
    frame = pd.DataFrame({"Primary Weld Current": [0.0, 1.0, 2.0]})
    axis, source = sensor_time_axis(frame)
    assert axis is None
    assert source == "unresolved"
