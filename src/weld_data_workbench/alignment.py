from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
import soundfile as sf

ALIGNMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class OnsetEstimate:
    modality: str
    onset_s: float | None
    confidence: float
    method: str
    details: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    schema_version: int
    sample_id: str
    reference_modality: str | None
    estimates: dict[str, OnsetEstimate]
    offsets_s: dict[str, float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "reference_modality": self.reference_modality,
            "estimates": {key: asdict(value) for key, value in self.estimates.items()},
            "offsets_s": self.offsets_s,
        }


def _robust_onset(
    values: np.ndarray,
    *,
    time_axis_s: np.ndarray,
    baseline_fraction: float = 0.10,
    minimum_baseline_points: int = 3,
    consecutive: int = 2,
) -> tuple[float | None, float, dict[str, float]]:
    values = np.asarray(values, dtype=np.float64)
    time_axis_s = np.asarray(time_axis_s, dtype=np.float64)
    finite = np.isfinite(values) & np.isfinite(time_axis_s)
    values = values[finite]
    time_axis_s = time_axis_s[finite]
    if len(values) < max(minimum_baseline_points + consecutive, 5):
        return None, 0.0, {"reason": "insufficient_points"}

    baseline_count = max(minimum_baseline_points, round(len(values) * baseline_fraction))
    baseline_count = min(baseline_count, max(1, len(values) - consecutive))
    baseline_values = values[:baseline_count]
    baseline = float(np.median(baseline_values))
    mad = float(np.median(np.abs(baseline_values - baseline)))
    upper = float(np.percentile(values, 95))
    dynamic = max(upper - baseline, 0.0)
    threshold = baseline + max(6.0 * mad, 0.15 * dynamic, 1e-9)

    above = values > threshold
    onset_index: int | None = None
    required = max(1, consecutive)
    for index in range(0, len(above) - required + 1):
        if bool(np.all(above[index : index + required])):
            onset_index = index
            break

    peak = float(np.max(values))
    confidence = 0.0
    if peak > baseline:
        confidence = float(np.clip((peak - threshold) / (peak - baseline), 0.0, 1.0))
    details = {
        "baseline": baseline,
        "mad": mad,
        "p95": upper,
        "threshold": threshold,
        "peak": peak,
        "baseline_points": float(baseline_count),
    }
    if onset_index is None:
        return None, confidence, details
    return float(time_axis_s[onset_index]), confidence, details


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
            raise ValueError("audio is too short for onset estimation")
        trimmed = mono[: frame_count * frame_length].reshape(frame_count, frame_length)
        rms = np.sqrt(np.mean(np.square(trimmed), axis=1))
        time_axis = np.arange(frame_count, dtype=np.float64) * frame_length / sample_rate
        onset, confidence, details = _robust_onset(rms, time_axis_s=time_axis)
        details.update(
            {
                "sample_rate_hz": int(sample_rate),
                "frame_ms": float(frame_length * 1000.0 / sample_rate),
                "analyzed_seconds": float(len(mono) / sample_rate),
            }
        )
        return OnsetEstimate(
            modality="audio",
            onset_s=onset,
            confidence=confidence,
            method="framed_rms_change",
            details=details,
        )
    except Exception as exc:
        return OnsetEstimate(
            modality="audio",
            onset_s=None,
            confidence=0.0,
            method="framed_rms_change",
            details={},
            error=f"{type(exc).__name__}: {exc}",
        )


def estimate_video_onset(
    path: Path,
    *,
    max_seconds: float = 15.0,
) -> OnsetEstimate:
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
            # Arc ignition typically changes both high-end luminance and the
            # fraction of saturated/near-saturated pixels. This bounded score is
            # intentionally simple and inspectable rather than model-based.
            p95 = float(np.percentile(gray, 95))
            bright_fraction = float(np.mean(gray >= 200))
            scores.append(p95 + 100.0 * bright_fraction)
            frame_index += 1
        if len(scores) < 5:
            raise ValueError("video contains too few readable frames")
        time_axis = np.arange(len(scores), dtype=np.float64) / fps
        onset, confidence, details = _robust_onset(
            np.asarray(scores, dtype=np.float64),
            time_axis_s=time_axis,
        )
        details.update(
            {
                "fps": fps,
                "frames_analyzed": len(scores),
                "analyzed_seconds": float(len(scores) / fps),
            }
        )
        return OnsetEstimate(
            modality="video",
            onset_s=onset,
            confidence=confidence,
            method="illumination_change",
            details=details,
        )
    except Exception as exc:
        return OnsetEstimate(
            modality="video",
            onset_s=None,
            confidence=0.0,
            method="illumination_change",
            details={},
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        capture.release()


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
        timestamps = pd.to_datetime(combined, errors="coerce")
        valid = timestamps.notna()
        if int(valid.sum()) >= 2:
            first = timestamps[valid].iloc[0]
            seconds = (timestamps - first).dt.total_seconds().to_numpy(dtype=np.float64)
            return seconds, f"datetime:{date_column}+{time_column}"

    # A bare clock-time column can still be normalized within one recording.
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
                method="current_voltage_change",
                details={"time_axis_source": time_source, "rows": len(frame)},
                error="No explicit sensor time axis could be resolved",
            )
        activity_column, activity = _sensor_activity_column(frame)
        if activity_column is None or activity is None:
            raise ValueError("no numeric current/voltage column found")
        onset, confidence, details = _robust_onset(activity, time_axis_s=time_axis)
        details.update(
            {
                "time_axis_source": time_source,
                "activity_column": activity_column,
                "rows": len(frame),
            }
        )
        return OnsetEstimate(
            modality="sensor",
            onset_s=onset,
            confidence=confidence,
            method="current_voltage_change",
            details=details,
        )
    except Exception as exc:
        return OnsetEstimate(
            modality="sensor",
            onset_s=None,
            confidence=0.0,
            method="current_voltage_change",
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


def estimate_sample_alignment(sample: dict[str, Any]) -> AlignmentReport:
    estimates: dict[str, OnsetEstimate] = {}
    audio_path = _primary_asset_path(sample, "audio")
    video_path = _primary_asset_path(sample, "video")
    sensor_path = _primary_asset_path(sample, "sensor")

    estimates["audio"] = (
        estimate_audio_onset(audio_path)
        if audio_path is not None
        else OnsetEstimate("audio", None, 0.0, "framed_rms_change", {}, "missing audio asset")
    )
    estimates["video"] = (
        estimate_video_onset(video_path)
        if video_path is not None
        else OnsetEstimate("video", None, 0.0, "illumination_change", {}, "missing video asset")
    )
    estimates["sensor"] = (
        estimate_sensor_onset(sensor_path)
        if sensor_path is not None
        else OnsetEstimate(
            "sensor", None, 0.0, "current_voltage_change", {}, "missing sensor asset"
        )
    )

    reference: str | None = None
    for candidate in ("sensor", "audio", "video"):
        if estimates[candidate].onset_s is not None:
            reference = candidate
            break
    reference_onset = estimates[reference].onset_s if reference is not None else None
    offsets: dict[str, float | None] = {}
    for modality, estimate in estimates.items():
        if reference_onset is None or estimate.onset_s is None:
            offsets[modality] = None
        else:
            offsets[modality] = float(estimate.onset_s - reference_onset)

    return AlignmentReport(
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        sample_id=str(sample.get("sample_id") or ""),
        reference_modality=reference,
        estimates=estimates,
        offsets_s=offsets,
    )


def write_alignment_report(report: AlignmentReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
