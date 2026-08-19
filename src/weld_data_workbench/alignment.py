from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
import soundfile as sf

ALIGNMENT_SCHEMA_VERSION = 2
DEFAULT_AUDIO_MAX_SECONDS = 60.0
DEFAULT_VIDEO_MAX_SECONDS = 60.0
DEFAULT_SENSOR_MAX_ROWS = 200_000
DEFAULT_VIDEO_MAX_WIDTH = 320
DEFAULT_VIDEO_ANALYSIS_FPS = 10.0

_KNOWN_SENSOR_DATETIME_FORMATS = (
    "%m-%d-%y %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S.%f",
    "%m/%d/%Y %H:%M:%S",
)


@dataclass(frozen=True, slots=True)
class OnsetEstimate:
    """Backward-compatible modality activity estimate.

    The class kept its historical name because downstream callers already consume
    ``onset_s`` and ``confidence``. Schema v2 extends the same record with the
    estimated activity end and duration rather than introducing a parallel result
    type that would force every client to migrate at once.
    """

    modality: str
    onset_s: float | None
    confidence: float
    method: str
    details: dict[str, Any]
    error: str | None = None
    end_s: float | None = None
    duration_s: float | None = None


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    schema_version: int
    sample_id: str
    reference_modality: str | None
    estimates: dict[str, OnsetEstimate]
    offsets_s: dict[str, float | None]
    end_offsets_s: dict[str, float | None]
    durations_s: dict[str, float | None]
    start_spread_s: float | None
    end_spread_s: float | None
    duration_spread_s: float | None
    quality: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "reference_modality": self.reference_modality,
            "estimates": {key: asdict(value) for key, value in self.estimates.items()},
            "offsets_s": self.offsets_s,
            "end_offsets_s": self.end_offsets_s,
            "durations_s": self.durations_s,
            "start_spread_s": self.start_spread_s,
            "end_spread_s": self.end_spread_s,
            "duration_spread_s": self.duration_spread_s,
            "quality": self.quality,
        }


@dataclass(frozen=True, slots=True)
class AlignmentLimits:
    """Explicit per-sample decode/read limits for alignment diagnostics."""

    audio_max_seconds: float = DEFAULT_AUDIO_MAX_SECONDS
    video_max_seconds: float = DEFAULT_VIDEO_MAX_SECONDS
    sensor_max_rows: int = DEFAULT_SENSOR_MAX_ROWS
    video_max_width: int = DEFAULT_VIDEO_MAX_WIDTH
    video_analysis_fps: float = DEFAULT_VIDEO_ANALYSIS_FPS

    def validate(self) -> None:
        if not math.isfinite(self.audio_max_seconds) or self.audio_max_seconds <= 0:
            raise ValueError("audio_max_seconds must be finite and positive")
        if not math.isfinite(self.video_max_seconds) or self.video_max_seconds <= 0:
            raise ValueError("video_max_seconds must be finite and positive")
        if self.sensor_max_rows < 5:
            raise ValueError("sensor_max_rows must be at least 5")
        if self.video_max_width < 32:
            raise ValueError("video_max_width must be at least 32")
        if not math.isfinite(self.video_analysis_fps) or self.video_analysis_fps <= 0:
            raise ValueError("video_analysis_fps must be finite and positive")


def _positive_step(time_axis_s: np.ndarray) -> float | None:
    differences = np.diff(time_axis_s)
    positive = differences[np.isfinite(differences) & (differences > 0)]
    if positive.size == 0:
        return None
    return float(np.median(positive))


def _bridge_short_false_gaps(mask: np.ndarray, maximum_gap: int) -> np.ndarray:
    result = np.asarray(mask, dtype=bool).copy()
    if maximum_gap <= 0 or result.size < 3:
        return result
    index = 0
    while index < len(result):
        if result[index]:
            index += 1
            continue
        start = index
        while index < len(result) and not result[index]:
            index += 1
        end = index
        gap = end - start
        bounded = start > 0 and end < len(result) and result[start - 1] and result[end]
        if bounded and gap <= maximum_gap:
            result[start:end] = True
    return result


def _first_true_run(mask: np.ndarray, required: int) -> int | None:
    run = 0
    for index, value in enumerate(mask):
        run = run + 1 if bool(value) else 0
        if run >= required:
            return index - required + 1
    return None


def _sustained_true_runs(mask: np.ndarray, required: int) -> list[tuple[int, int]]:
    """Return half-open true runs that meet the minimum support length."""

    result: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if bool(value) and start is None:
            start = index
        if start is not None and (not bool(value) or index == len(mask) - 1):
            end = index if not bool(value) else index + 1
            if end - start >= required:
                result.append((start, end))
            start = None
    return result


def _release_index(mask: np.ndarray, onset_index: int, required_false: int) -> int | None:
    false_run = 0
    for index in range(onset_index, len(mask)):
        if bool(mask[index]):
            false_run = 0
            continue
        false_run += 1
        if false_run >= required_false:
            return index - required_false + 1
    return None


def _spread(values: list[float | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and np.isfinite(value)]
    return max(finite) - min(finite) if len(finite) >= 2 else None


def _robust_activity_interval(
    values: np.ndarray,
    *,
    time_axis_s: np.ndarray,
    baseline_fraction: float = 0.10,
    minimum_baseline_points: int = 3,
    consecutive: int = 2,
    release_consecutive: int = 3,
    bridge_gap_points: int = 1,
    mad_multiplier: float = 3.0,
    near_dominant_fraction: float = 0.90,
) -> tuple[float | None, float | None, float, dict[str, Any]]:
    """Estimate a bounded active interval from an inspectable scalar activity trace.

    The threshold is derived from the leading baseline only. That choice is
    deliberate: several welding recordings remain active until the file ends, so a
    trailing-baseline assumption would erase valid activity. A short false gap may
    be bridged, while a sustained release terminates the interval. If no release is
    observed before the final sample, the result is explicitly marked end-censored.
    """

    values = np.asarray(values, dtype=np.float64)
    time_axis_s = np.asarray(time_axis_s, dtype=np.float64)
    finite = np.isfinite(values) & np.isfinite(time_axis_s)
    values = values[finite]
    time_axis_s = time_axis_s[finite]
    if len(values) < max(minimum_baseline_points + consecutive, 5):
        return None, None, 0.0, {"reason": "insufficient_points"}

    order = np.argsort(time_axis_s, kind="stable")
    values = values[order]
    time_axis_s = time_axis_s[order]

    baseline_count = max(minimum_baseline_points, round(len(values) * baseline_fraction))
    baseline_count = min(baseline_count, max(1, len(values) - consecutive))
    baseline_values = values[:baseline_count]
    baseline = float(np.median(baseline_values))
    mad = float(np.median(np.abs(baseline_values - baseline)))
    upper = float(np.percentile(values, 95))
    dynamic = max(upper - baseline, 0.0)
    threshold = baseline + max(max(0.0, mad_multiplier) * mad, 0.15 * dynamic, 1e-9)

    raw_active = values > threshold
    active = _bridge_short_false_gaps(raw_active, max(0, bridge_gap_points))
    required = max(1, consecutive)
    sustained_runs = _sustained_true_runs(active, required)

    peak = float(np.max(values))
    amplitude_confidence = 0.0
    if peak > baseline:
        amplitude_confidence = float(
            np.clip((peak - threshold) / max(peak - baseline, 1e-12), 0.0, 1.0)
        )

    details: dict[str, Any] = {
        "baseline": baseline,
        "mad": mad,
        "p95": upper,
        "threshold": threshold,
        "peak": peak,
        "baseline_points": baseline_count,
        "raw_active_points": int(np.count_nonzero(raw_active)),
        "bridged_active_points": int(np.count_nonzero(active)),
        "bridge_gap_points": max(0, bridge_gap_points),
        "release_consecutive": max(1, release_consecutive),
        "mad_multiplier": max(0.0, mad_multiplier),
        "sustained_run_count": len(sustained_runs),
    }
    if not sustained_runs:
        details["reason"] = "no_sustained_activity"
        return None, None, amplitude_confidence, details

    # Welding traces contain short current, acoustic, and illumination dropouts.
    # Select the dominant bridged activity run instead of ending at the first
    # release; ties favor the earlier run deterministically.
    longest_run_points = max(end - start for start, end in sustained_runs)
    near_dominant_fraction = float(np.clip(near_dominant_fraction, 0.0, 1.0))
    near_dominant_threshold = longest_run_points * near_dominant_fraction
    near_dominant_runs = [
        run for run in sustained_runs if run[1] - run[0] >= near_dominant_threshold
    ]
    onset_index, selected_end = min(near_dominant_runs, key=lambda run: run[0])
    active_end_index = selected_end - 1
    step = _positive_step(time_axis_s)
    onset_s = float(time_axis_s[onset_index])
    trailing_points = len(time_axis_s) - selected_end
    if trailing_points < max(1, release_consecutive):
        final_time = float(time_axis_s[-1])
        end_s = final_time + (step or 0.0)
        end_censored = True
    else:
        end_s = float(time_axis_s[selected_end])
        end_censored = False

    interval_points = max(selected_end - onset_index, 1)
    raw_active_count = int(np.count_nonzero(raw_active[onset_index:selected_end]))
    persistence = float(np.clip(raw_active_count / interval_points, 0.0, 1.0))
    confidence = float(np.sqrt(max(amplitude_confidence, 0.0) * max(persistence, 0.0)))
    if end_censored:
        confidence *= 0.9

    details.update(
        {
            "onset_index": onset_index,
            "active_end_index": active_end_index,
            "selected_run_points": interval_points,
            "selected_raw_active_points": raw_active_count,
            "near_dominant_fraction": near_dominant_fraction,
            "near_dominant_run_count": len(near_dominant_runs),
            "end_censored": end_censored,
            "median_time_step_s": step,
            "persistence": persistence,
        }
    )
    return onset_s, end_s, confidence, details


def _robust_onset(
    values: np.ndarray,
    *,
    time_axis_s: np.ndarray,
    baseline_fraction: float = 0.10,
    minimum_baseline_points: int = 3,
    consecutive: int = 2,
) -> tuple[float | None, float, dict[str, Any]]:
    """Compatibility wrapper for callers that only need the activity start."""

    onset, _end, confidence, details = _robust_activity_interval(
        values,
        time_axis_s=time_axis_s,
        baseline_fraction=baseline_fraction,
        minimum_baseline_points=minimum_baseline_points,
        consecutive=consecutive,
    )
    return onset, confidence, details


def _estimate_from_trace(
    *,
    modality: str,
    method: str,
    values: np.ndarray,
    time_axis_s: np.ndarray,
    details: dict[str, Any],
    consecutive: int = 2,
    release_consecutive: int = 3,
    bridge_gap_points: int = 1,
    mad_multiplier: float = 3.0,
) -> OnsetEstimate:
    onset, end, confidence, interval_details = _robust_activity_interval(
        values,
        time_axis_s=time_axis_s,
        consecutive=consecutive,
        release_consecutive=release_consecutive,
        bridge_gap_points=bridge_gap_points,
        mad_multiplier=mad_multiplier,
    )
    interval_details.update(details)
    duration = None
    if onset is not None and end is not None and end >= onset:
        duration = float(end - onset)
    return OnsetEstimate(
        modality=modality,
        onset_s=onset,
        confidence=confidence,
        method=method,
        details=interval_details,
        end_s=end,
        duration_s=duration,
    )


def estimate_audio_onset(
    path: Path,
    *,
    frame_ms: float = 20.0,
    max_seconds: float = DEFAULT_AUDIO_MAX_SECONDS,
    bridge_gap_seconds: float = 0.5,
) -> OnsetEstimate:
    try:
        if not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("max_seconds must be finite and positive")
        info = sf.info(str(path))
        frames_to_read = min(int(info.frames), int(max_seconds * info.samplerate))
        data, sample_rate = sf.read(
            str(path),
            frames=frames_to_read,
            dtype="float32",
            always_2d=True,
        )
        if data.size == 0 or sample_rate <= 0:
            raise ValueError("audio contains no readable samples")
        mono = np.mean(data, axis=1, dtype=np.float64)
        frame_length = max(16, round(sample_rate * frame_ms / 1000.0))
        frame_count = len(mono) // frame_length
        if frame_count < 5:
            raise ValueError("audio is too short for activity estimation")
        trimmed = mono[: frame_count * frame_length].reshape(frame_count, frame_length)
        rms = np.sqrt(np.mean(np.square(trimmed), axis=1))
        time_axis = np.arange(frame_count, dtype=np.float64) * frame_length / sample_rate
        actual_frame_s = float(frame_length / sample_rate)
        return _estimate_from_trace(
            modality="audio",
            method="framed_rms_activity",
            values=rms,
            time_axis_s=time_axis,
            details={
                "sample_rate_hz": int(sample_rate),
                "frame_ms": float(frame_length * 1000.0 / sample_rate),
                "analyzed_seconds": float(len(mono) / sample_rate),
                "source_duration_s": float(info.frames / info.samplerate),
                "analysis_window_truncated": frames_to_read < int(info.frames),
                "max_seconds": float(max_seconds),
            },
            consecutive=max(2, math.ceil(0.10 / actual_frame_s)),
            bridge_gap_points=max(1, math.ceil(bridge_gap_seconds / actual_frame_s)),
        )
    except Exception as exc:
        return OnsetEstimate(
            modality="audio",
            onset_s=None,
            confidence=0.0,
            method="framed_rms_activity",
            details={},
            error=f"{type(exc).__name__}: {exc}",
        )


def _video_activity_trace(
    path: Path,
    max_seconds: float,
    *,
    max_width: int = DEFAULT_VIDEO_MAX_WIDTH,
    max_analysis_fps: float = DEFAULT_VIDEO_ANALYSIS_FPS,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("OpenCV could not open video")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            raise ValueError("video has no usable FPS")
        source_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        max_frames = max(5, round(max_seconds * fps))
        frame_stride = max(1, math.ceil(fps / max_analysis_fps))
        scores: list[float] = []
        sample_times: list[float] = []
        frame_index = 0
        while frame_index < max_frames:
            if not capture.grab():
                break
            if frame_index % frame_stride != 0:
                frame_index += 1
                continue
            ok, frame = capture.retrieve()
            if not ok or frame is None:
                break
            if frame.shape[1] > max_width:
                scale = max_width / frame.shape[1]
                frame = cv2.resize(
                    frame,
                    (max_width, max(1, round(frame.shape[0] * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            p95 = float(np.percentile(gray, 95))
            bright_fraction = float(np.mean(gray >= 200))
            scores.append(p95 + 100.0 * bright_fraction)
            sample_times.append(frame_index / fps)
            frame_index += 1
        if len(scores) < 5:
            raise ValueError("video contains too few readable frames")
        time_axis = np.asarray(sample_times, dtype=np.float64)
        actual_analysis_fps = fps / frame_stride
        return (
            np.asarray(scores, dtype=np.float64),
            time_axis,
            {
                "fps": fps,
                "analysis_fps": actual_analysis_fps,
                "frame_stride": frame_stride,
                "frames_analyzed": len(scores),
                "source_frames_scanned": frame_index,
                "analyzed_seconds": float(frame_index / fps),
                "source_frame_count": source_frame_count or None,
                "source_duration_s": (
                    float(source_frame_count / fps) if source_frame_count > 0 else None
                ),
                "source_width": source_width or None,
                "source_height": source_height or None,
                "analysis_max_width": int(max_width),
                "analysis_window_truncated": (
                    source_frame_count > max_frames if source_frame_count > 0 else False
                ),
                "max_seconds": float(max_seconds),
            },
        )
    finally:
        capture.release()


def estimate_video_onset(
    path: Path,
    *,
    max_seconds: float = DEFAULT_VIDEO_MAX_SECONDS,
    max_width: int = DEFAULT_VIDEO_MAX_WIDTH,
    max_analysis_fps: float = DEFAULT_VIDEO_ANALYSIS_FPS,
    bridge_gap_seconds: float = 0.5,
) -> OnsetEstimate:
    try:
        if not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("max_seconds must be finite and positive")
        if max_width < 32:
            raise ValueError("max_width must be at least 32")
        if not math.isfinite(max_analysis_fps) or max_analysis_fps <= 0:
            raise ValueError("max_analysis_fps must be finite and positive")
        scores, time_axis, details = _video_activity_trace(
            path,
            max_seconds,
            max_width=max_width,
            max_analysis_fps=max_analysis_fps,
        )
        step = _positive_step(time_axis)
        if step is None:
            raise ValueError("video analysis time axis has no positive step")
        return _estimate_from_trace(
            modality="video",
            method="illumination_activity",
            values=scores,
            time_axis_s=time_axis,
            details=details,
            consecutive=max(2, math.ceil(0.10 / step)),
            bridge_gap_points=max(1, math.ceil(bridge_gap_seconds / step)),
        )
    except Exception as exc:
        return OnsetEstimate(
            modality="video",
            onset_s=None,
            confidence=0.0,
            method="illumination_activity",
            details={},
            error=f"{type(exc).__name__}: {exc}",
        )


def _parse_sensor_datetime(values: pd.Series) -> tuple[pd.Series, str]:
    """Parse known sensor timestamp layouts without pandas format-inference warnings."""

    for date_format in _KNOWN_SENSOR_DATETIME_FORMATS:
        timestamps = pd.to_datetime(values, format=date_format, errors="coerce")
        if int(timestamps.notna().sum()) >= 2:
            return timestamps, date_format
    timestamps = pd.to_datetime(values, format="mixed", errors="coerce")
    return timestamps, "mixed"


def sensor_time_axis(frame: pd.DataFrame) -> tuple[np.ndarray | None, str]:
    """Resolve an explicit sensor time axis without inventing a sample rate."""

    normalized = {str(column).strip().casefold(): str(column) for column in frame.columns}
    for candidate in ("timestamp_s", "time_s", "elapsed_s", "seconds", "second"):
        column = normalized.get(candidate)
        if column is None:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64)
        finite = np.isfinite(numeric)
        if finite.sum() >= 2:
            first = float(numeric[finite][0])
            return numeric - first, f"numeric:{column}"

    date_column = normalized.get("date")
    time_column = normalized.get("time")
    if date_column is not None and time_column is not None:
        combined = (
            frame[date_column].astype(str).str.strip()
            + " "
            + frame[time_column].astype(str).str.strip()
        )
        timestamps, parsed_format = _parse_sensor_datetime(combined)
        valid = timestamps.notna()
        if int(valid.sum()) >= 2:
            first = timestamps[valid].iloc[0]
            seconds = (timestamps - first).dt.total_seconds().to_numpy(dtype=np.float64)
            return seconds, f"datetime:{date_column}+{time_column}:{parsed_format}"

    if time_column is not None:
        deltas = pd.to_timedelta(frame[time_column].astype(str), errors="coerce")
        valid = deltas.notna()
        if int(valid.sum()) >= 2:
            first = deltas[valid].iloc[0]
            seconds = (deltas - first).dt.total_seconds().to_numpy(dtype=np.float64)
            return seconds, f"timedelta:{time_column}"

    return None, "unresolved"


def _sensor_activity_column(frame: pd.DataFrame) -> tuple[str | None, np.ndarray | None]:
    names = [str(column) for column in frame.columns]
    preferred = [name for name in names if "current" in name.casefold()]
    preferred += [name for name in names if "voltage" in name.casefold() and name not in preferred]
    for column in preferred:
        numeric = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64)
        if np.isfinite(numeric).sum() >= 5:
            return column, np.abs(numeric)
    return None, None


def estimate_sensor_onset(
    path: Path,
    *,
    max_rows: int = DEFAULT_SENSOR_MAX_ROWS,
    bridge_gap_seconds: float = 0.75,
) -> OnsetEstimate:
    try:
        if max_rows < 5:
            raise ValueError("max_rows must be at least 5")
        frame = pd.read_csv(path, nrows=max_rows + 1)
        analysis_window_truncated = len(frame) > max_rows
        if analysis_window_truncated:
            frame = frame.iloc[:max_rows].copy()
        if frame.empty:
            raise ValueError("sensor CSV is empty")
        time_axis, time_source = sensor_time_axis(frame)
        if time_axis is None:
            return OnsetEstimate(
                modality="sensor",
                onset_s=None,
                confidence=0.0,
                method="current_voltage_activity",
                details={
                    "time_axis_source": time_source,
                    "rows": len(frame),
                    "max_rows": max_rows,
                    "analysis_window_truncated": analysis_window_truncated,
                },
                error="No explicit sensor time axis could be resolved",
            )
        activity_column, activity = _sensor_activity_column(frame)
        if activity_column is None or activity is None:
            raise ValueError("no numeric current/voltage column found")
        step = _positive_step(time_axis)
        differences = np.diff(time_axis)
        positive_differences = differences[np.isfinite(differences) & (differences > 0)]
        maximum_step = float(np.max(positive_differences)) if positive_differences.size else None
        time_gap_detected = bool(
            step is not None and maximum_step is not None and maximum_step > max(1.0, 10.0 * step)
        )
        bridge_gap_points = max(1, math.ceil(bridge_gap_seconds / step)) if step is not None else 1
        return _estimate_from_trace(
            modality="sensor",
            method="current_voltage_activity",
            values=activity,
            time_axis_s=time_axis,
            details={
                "time_axis_source": time_source,
                "activity_column": activity_column,
                "rows": len(frame),
                "max_rows": max_rows,
                "analysis_window_truncated": analysis_window_truncated,
                "max_time_gap_s": maximum_step,
                "time_gap_detected": time_gap_detected,
            },
            bridge_gap_points=bridge_gap_points,
        )
    except Exception as exc:
        return OnsetEstimate(
            modality="sensor",
            onset_s=None,
            confidence=0.0,
            method="current_voltage_activity",
            details={},
            error=f"{type(exc).__name__}: {exc}",
        )


def _primary_asset_path(sample: dict[str, Any], kind: str) -> Path | None:
    candidates = sorted(
        (
            asset
            for asset in sample.get("assets", [])
            if asset.get("kind") == kind and asset.get("absolute_path")
        ),
        key=lambda asset: (int(asset.get("ordinal") or 0), str(asset.get("relpath") or "")),
    )
    return Path(str(candidates[0]["absolute_path"])) if candidates else None


def _missing_estimate(modality: str, method: str) -> OnsetEstimate:
    return OnsetEstimate(modality, None, 0.0, method, {}, f"missing {modality} asset")


def _alignment_quality(estimates: dict[str, OnsetEstimate], start_spread: float | None) -> str:
    available = sum(estimate.onset_s is not None for estimate in estimates.values())
    if available < 2:
        return "insufficient"
    if available == 2:
        return "partial"
    if start_spread is None:
        return "partial"
    if start_spread <= 0.25 and all(estimate.confidence >= 0.20 for estimate in estimates.values()):
        return "good"
    if start_spread <= 0.75:
        return "warning"
    return "poor"


def estimate_sample_alignment(
    sample: dict[str, Any],
    *,
    limits: AlignmentLimits | None = None,
) -> AlignmentReport:
    selected_limits = limits or AlignmentLimits()
    selected_limits.validate()
    audio_path = _primary_asset_path(sample, "audio")
    video_path = _primary_asset_path(sample, "video")
    sensor_path = _primary_asset_path(sample, "sensor")
    estimates = {
        "audio": estimate_audio_onset(
            audio_path,
            max_seconds=selected_limits.audio_max_seconds,
        )
        if audio_path is not None
        else _missing_estimate("audio", "framed_rms_activity"),
        "video": estimate_video_onset(
            video_path,
            max_seconds=selected_limits.video_max_seconds,
            max_width=selected_limits.video_max_width,
            max_analysis_fps=selected_limits.video_analysis_fps,
        )
        if video_path is not None
        else _missing_estimate("video", "illumination_activity"),
        "sensor": estimate_sensor_onset(
            sensor_path,
            max_rows=selected_limits.sensor_max_rows,
        )
        if sensor_path is not None
        else _missing_estimate("sensor", "current_voltage_activity"),
    }

    reference: str | None = None
    for candidate in ("sensor", "audio", "video"):
        if estimates[candidate].onset_s is not None:
            reference = candidate
            break

    reference_onset = estimates[reference].onset_s if reference is not None else None
    reference_end = estimates[reference].end_s if reference is not None else None
    offsets: dict[str, float | None] = {}
    end_offsets: dict[str, float | None] = {}
    durations: dict[str, float | None] = {}
    for modality, estimate in estimates.items():
        offsets[modality] = (
            float(estimate.onset_s - reference_onset)
            if reference_onset is not None and estimate.onset_s is not None
            else None
        )
        end_offsets[modality] = (
            float(estimate.end_s - reference_end)
            if reference_end is not None and estimate.end_s is not None
            else None
        )
        durations[modality] = estimate.duration_s

    start_spread = _spread([estimate.onset_s for estimate in estimates.values()])
    end_spread = _spread([estimate.end_s for estimate in estimates.values()])
    duration_spread = _spread([estimate.duration_s for estimate in estimates.values()])
    return AlignmentReport(
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        sample_id=str(sample.get("sample_id") or ""),
        reference_modality=reference,
        estimates=estimates,
        offsets_s=offsets,
        end_offsets_s=end_offsets,
        durations_s=durations,
        start_spread_s=start_spread,
        end_spread_s=end_spread,
        duration_spread_s=duration_spread,
        quality=_alignment_quality(estimates, start_spread),
    )


def write_alignment_report(report: AlignmentReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
