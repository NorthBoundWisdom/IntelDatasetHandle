from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
import soundfile as sf

ALIGNMENT_SCHEMA_VERSION = 2

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
    threshold = baseline + max(6.0 * mad, 0.15 * dynamic, 1e-9)

    raw_active = values > threshold
    active = _bridge_short_false_gaps(raw_active, max(0, bridge_gap_points))
    required = max(1, consecutive)
    onset_index = _first_true_run(active, required)

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
    }
    if onset_index is None:
        details["reason"] = "no_sustained_activity"
        return None, None, amplitude_confidence, details

    release = _release_index(active, onset_index, max(1, release_consecutive))
    step = _positive_step(time_axis_s)
    onset_s = float(time_axis_s[onset_index])
    if release is None:
        final_time = float(time_axis_s[-1])
        end_s = final_time + (step or 0.0)
        end_censored = True
        active_end_index = len(time_axis_s) - 1
    else:
        end_s = float(time_axis_s[release])
        end_censored = False
        active_end_index = max(onset_index, release - 1)

    active_count = max(active_end_index - onset_index + 1, 1)
    interval_points = max(len(active) - onset_index, 1)
    persistence = float(np.clip(active_count / interval_points, 0.0, 1.0))
    confidence = float(np.sqrt(max(amplitude_confidence, 0.0) * max(persistence, 0.0)))
    if end_censored:
        confidence *= 0.9

    details.update(
        {
            "onset_index": onset_index,
            "active_end_index": active_end_index,
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
) -> OnsetEstimate:
    onset, end, confidence, interval_details = _robust_activity_interval(
        values,
        time_axis_s=time_axis_s,
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
    max_seconds: float = 15.0,
) -> OnsetEstimate:
    try:
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
        return _estimate_from_trace(
            modality="audio",
            method="framed_rms_activity",
            values=rms,
            time_axis_s=time_axis,
            details={
                "sample_rate_hz": int(sample_rate),
                "frame_ms": float(frame_length * 1000.0 / sample_rate),
                "analyzed_seconds": float(len(mono) / sample_rate),
            },
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


def _video_activity_trace(path: Path, max_seconds: float) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("OpenCV could not open video")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            raise ValueError("video has no usable FPS")
        max_frames = max(5, round(max_seconds * fps))
        scores: list[float] = []
        frame_index = 0
        while frame_index < max_frames:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            p95 = float(np.percentile(gray, 95))
            bright_fraction = float(np.mean(gray >= 200))
            scores.append(p95 + 100.0 * bright_fraction)
            frame_index += 1
        if len(scores) < 5:
            raise ValueError("video contains too few readable frames")
        time_axis = np.arange(len(scores), dtype=np.float64) / fps
        return (
            np.asarray(scores, dtype=np.float64),
            time_axis,
            {
                "fps": fps,
                "frames_analyzed": len(scores),
                "analyzed_seconds": float(len(scores) / fps),
            },
        )
    finally:
        capture.release()


def estimate_video_onset(
    path: Path,
    *,
    max_seconds: float = 15.0,
) -> OnsetEstimate:
    try:
        scores, time_axis, details = _video_activity_trace(path, max_seconds)
        return _estimate_from_trace(
            modality="video",
            method="illumination_activity",
            values=scores,
            time_axis_s=time_axis,
            details=details,
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


def estimate_sensor_onset(path: Path) -> OnsetEstimate:
    try:
        frame = pd.read_csv(path)
        if frame.empty:
            raise ValueError("sensor CSV is empty")
        time_axis, time_source = sensor_time_axis(frame)
        if time_axis is None:
            return OnsetEstimate(
                modality="sensor",
                onset_s=None,
                confidence=0.0,
                method="current_voltage_activity",
                details={"time_axis_source": time_source, "rows": len(frame)},
                error="No explicit sensor time axis could be resolved",
            )
        activity_column, activity = _sensor_activity_column(frame)
        if activity_column is None or activity is None:
            raise ValueError("no numeric current/voltage column found")
        return _estimate_from_trace(
            modality="sensor",
            method="current_voltage_activity",
            values=activity,
            time_axis_s=time_axis,
            details={
                "time_axis_source": time_source,
                "activity_column": activity_column,
                "rows": len(frame),
            },
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


def estimate_sample_alignment(sample: dict[str, Any]) -> AlignmentReport:
    audio_path = _primary_asset_path(sample, "audio")
    video_path = _primary_asset_path(sample, "video")
    sensor_path = _primary_asset_path(sample, "sensor")
    estimates = {
        "audio": estimate_audio_onset(audio_path)
        if audio_path is not None
        else _missing_estimate("audio", "framed_rms_activity"),
        "video": estimate_video_onset(video_path)
        if video_path is not None
        else _missing_estimate("video", "illumination_activity"),
        "sensor": estimate_sensor_onset(sensor_path)
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
