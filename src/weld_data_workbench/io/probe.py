from __future__ import annotations

import csv
import hashlib
import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
import soundfile as sf
from PIL import Image

from ..config import AppConfig
from ..constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, SENSOR_EXTENSIONS, VIDEO_EXTENSIONS
from ..domain.models import (
    AssetKind,
    AssetProbe,
    HealthStatus,
    Issue,
    ProbeMode,
    SampleCandidate,
    SampleProbe,
    Severity,
)
from .paths import relative_posix, stable_asset_id

logger = logging.getLogger(__name__)


def _sha256(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def _sniff_delimiter(path: Path) -> str:
    try:
        sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        return ","


def _count_lines(path: Path) -> int:
    count = 0
    last_byte = b""
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            count += block.count(b"\n")
            last_byte = block[-1:]
    if path.stat().st_size and last_byte not in {b"\n", b"\r"}:
        count += 1
    return count


def _ffprobe_rate(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.casefold() == "n/a":
        return None
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            rate = float(numerator) / denominator_value
        else:
            rate = float(text)
    except (TypeError, ValueError):
        return None
    return rate if np.isfinite(rate) and rate > 0 else None


def _ffprobe_positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0 else None


def _ffprobe_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _probe_video_opencv(path: Path, mode: ProbeMode) -> tuple[dict[str, Any], bool]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        return {
            "probe_backend": "opencv",
            "error": "OpenCV could not open video",
        }, False

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fourcc_int = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
    fourcc = "".join(chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)).strip("\x00")
    duration = frames / fps if frames > 0 and fps > 0 else None

    metadata: dict[str, Any] = {
        "probe_backend": "opencv",
        "fps": fps or None,
        "frame_count": frames or None,
        "width": width or None,
        "height": height or None,
        "duration_s": duration,
        "fourcc": fourcc or None,
    }

    ok = width > 0 and height > 0
    if mode == ProbeMode.FULL and frames > 0:
        decoded_positions: list[int] = []
        for fraction in (0.0, 0.5, 0.95):
            frame_index = min(max(int(frames * fraction), 0), max(frames - 1, 0))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = capture.read()
            if success and frame is not None and frame.size:
                decoded_positions.append(frame_index)
        metadata["decoded_probe_frames"] = decoded_positions
        metadata["decode_verified"] = bool(decoded_positions)
        ok = ok and bool(decoded_positions)
    elif mode == ProbeMode.FULL:
        metadata["decoded_probe_frames"] = []
        metadata["decode_verified"] = False
        ok = False

    capture.release()
    if not ok:
        metadata["error"] = (
            "OpenCV could not decode sampled video frames"
            if mode == ProbeMode.FULL
            else "OpenCV returned invalid video dimensions"
        )
    return metadata, ok


def _probe_video_ffprobe(path: Path) -> tuple[dict[str, Any], bool]:
    executable = shutil.which("ffprobe")
    if executable is None:
        return {
            "probe_backend": "ffprobe",
            "error": "ffprobe executable is not available",
        }, False

    command = [
        executable,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        (
            "stream=codec_name,codec_tag_string,width,height,avg_frame_rate,"
            "r_frame_rate,nb_frames,duration:format=duration"
        ),
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "probe_backend": "ffprobe",
            "error": f"ffprobe execution failed: {exc}",
        }, False

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        return {
            "probe_backend": "ffprobe",
            "error": f"ffprobe exited with status {completed.returncode}",
            "stderr": stderr[-2000:] if stderr else None,
        }, False

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "probe_backend": "ffprobe",
            "error": f"ffprobe returned invalid JSON: {exc}",
        }, False

    if not isinstance(payload, dict):
        return {
            "probe_backend": "ffprobe",
            "error": "ffprobe JSON root is not an object",
        }, False
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        return {
            "probe_backend": "ffprobe",
            "error": "ffprobe found no video stream",
        }, False

    stream = streams[0]
    format_payload = payload.get("format")
    format_metadata = format_payload if isinstance(format_payload, dict) else {}
    fps = _ffprobe_rate(stream.get("avg_frame_rate")) or _ffprobe_rate(stream.get("r_frame_rate"))
    duration = _ffprobe_positive_float(stream.get("duration")) or _ffprobe_positive_float(
        format_metadata.get("duration")
    )
    frames = _ffprobe_positive_int(stream.get("nb_frames"))
    width = _ffprobe_positive_int(stream.get("width"))
    height = _ffprobe_positive_int(stream.get("height"))
    fourcc = str(stream.get("codec_tag_string") or "").strip() or None
    codec_name = str(stream.get("codec_name") or "").strip() or None

    metadata: dict[str, Any] = {
        "probe_backend": "ffprobe",
        "fps": fps,
        "frame_count": frames,
        "width": width,
        "height": height,
        "duration_s": duration,
        "fourcc": fourcc,
        "codec_name": codec_name,
        "decode_verified": False,
    }
    ok = width is not None and height is not None
    if not ok:
        metadata["error"] = "ffprobe returned no usable video dimensions"
    return metadata, ok


def _probe_video(path: Path, mode: ProbeMode) -> tuple[dict[str, Any], bool]:
    opencv_metadata, opencv_ok = _probe_video_opencv(path, mode)
    if opencv_ok:
        return opencv_metadata, True

    ffprobe_metadata, ffprobe_ok = _probe_video_ffprobe(path)
    if ffprobe_ok:
        ffprobe_metadata["fallback_reason"] = opencv_metadata.get(
            "error", "OpenCV video probe did not validate the asset"
        )
        ffprobe_metadata["opencv_metadata"] = opencv_metadata
        return ffprobe_metadata, True

    return {
        "probe_backend": "opencv+ffprobe",
        "error": "OpenCV video probe failed and ffprobe fallback did not validate the asset",
        "opencv_metadata": opencv_metadata,
        "ffprobe_metadata": ffprobe_metadata,
    }, False


def _probe_audio(path: Path, mode: ProbeMode) -> tuple[dict[str, Any], bool]:
    try:
        info = sf.info(str(path))
        metadata: dict[str, Any] = {
            "sample_rate_hz": int(info.samplerate),
            "channels": int(info.channels),
            "frames": int(info.frames),
            "duration_s": float(info.duration),
            "format": info.format,
            "subtype": info.subtype,
        }
        if mode == ProbeMode.FULL:
            with sf.SoundFile(str(path)) as handle:
                sample_frames = min(handle.frames, max(handle.samplerate // 2, 1))
                data = handle.read(sample_frames, dtype="float32", always_2d=True)
                metadata["probe_peak"] = float(np.max(np.abs(data))) if data.size else 0.0
                metadata["probe_rms"] = (
                    float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0
                )
        return metadata, info.samplerate > 0 and info.channels > 0
    except Exception as exc:
        return {"error": str(exc)}, False


def _probe_sensor(path: Path, mode: ProbeMode, max_rows: int) -> tuple[dict[str, Any], bool]:
    delimiter = _sniff_delimiter(path)
    try:
        preview_rows = min(max_rows, 200 if mode == ProbeMode.LIGHT else max_rows)
        frame = pd.read_csv(path, sep=delimiter, nrows=preview_rows, engine="python")
        line_count = _count_lines(path)
        row_count = max(line_count - 1, 0)
        numeric_columns = frame.select_dtypes(include=["number"]).columns.tolist()
        metadata: dict[str, Any] = {
            "delimiter": "\\t" if delimiter == "\t" else delimiter,
            "row_count": row_count,
            "column_count": len(frame.columns),
            "columns": [str(column) for column in frame.columns],
            "numeric_columns": [str(column) for column in numeric_columns],
            "preview_rows": len(frame),
        }
        if mode == ProbeMode.FULL:
            metadata["missing_fraction_preview"] = {
                str(column): float(frame[column].isna().mean()) for column in frame.columns
            }
            metadata["constant_numeric_columns_preview"] = [
                str(column) for column in numeric_columns if frame[column].dropna().nunique() <= 1
            ]
        return metadata, len(frame.columns) > 0
    except Exception as exc:
        return {"error": str(exc), "delimiter": delimiter}, False


def _probe_image(path: Path, mode: ProbeMode) -> tuple[dict[str, Any], bool]:
    try:
        with Image.open(path) as image:
            metadata: dict[str, Any] = {
                "width": int(image.width),
                "height": int(image.height),
                "mode": image.mode,
                "format": image.format,
            }
            if mode == ProbeMode.FULL:
                image.verify()
        return metadata, metadata["width"] > 0 and metadata["height"] > 0
    except Exception as exc:
        return {"error": str(exc)}, False


def _asset_files(candidate: SampleCandidate) -> list[tuple[AssetKind, Path]]:
    path = candidate.sample_path
    if not path.is_dir():
        return []

    assets: list[tuple[AssetKind, Path]] = []
    direct_files = sorted(
        (item for item in path.iterdir() if item.is_file()), key=lambda p: p.name.casefold()
    )
    for item in direct_files:
        suffix = item.suffix.casefold()
        if suffix in VIDEO_EXTENSIONS:
            assets.append((AssetKind.VIDEO, item))
        elif suffix in AUDIO_EXTENSIONS:
            assets.append((AssetKind.AUDIO, item))
        elif suffix in SENSOR_EXTENSIONS:
            # A sample-level CSV is treated as sensor data. Manifest files are normally outside samples.
            assets.append((AssetKind.SENSOR, item))
        elif suffix in IMAGE_EXTENSIONS:
            assets.append((AssetKind.IMAGE, item))

    images_dir = path / "images"
    if images_dir.is_dir():
        for item in sorted(images_dir.rglob("*"), key=lambda p: p.as_posix().casefold()):
            if item.is_file() and item.suffix.casefold() in IMAGE_EXTENSIONS:
                assets.append((AssetKind.IMAGE, item))
    return assets


def _issue(
    severity: Severity,
    code: str,
    message: str,
    candidate: SampleCandidate,
    *,
    relpath: str | None = None,
    details: dict[str, Any] | None = None,
) -> Issue:
    return Issue(
        severity=severity,
        code=code,
        message=message,
        sample_id=candidate.sample_id,
        relpath=relpath or candidate.relpath,
        details=details or {},
    )


def probe_sample(
    candidate: SampleCandidate,
    config: AppConfig,
    *,
    progress: Callable[[str], None] | None = None,
) -> SampleProbe:
    mode = ProbeMode(config.scan.probe_mode)
    result = SampleProbe(candidate=candidate, health_status=HealthStatus.UNPROBED)

    if not candidate.sample_path.exists():
        result.issues.append(
            _issue(
                Severity.ERROR, "sample_path_missing", "Sample directory does not exist", candidate
            )
        )
        result.health_status = HealthStatus.ERROR
        return result
    if not candidate.sample_path.is_dir():
        result.issues.append(
            _issue(
                Severity.ERROR,
                "sample_path_not_directory",
                "Sample path is not a directory",
                candidate,
            )
        )
        result.health_status = HealthStatus.ERROR
        return result

    files = _asset_files(candidate)
    counts = {kind: 0 for kind in AssetKind}

    for kind, path in files:
        ordinal = counts[kind]
        counts[kind] += 1
        try:
            stat = path.stat()
            relpath = relative_posix(path, config.dataset_root)
        except (OSError, ValueError) as exc:
            result.issues.append(
                _issue(
                    Severity.ERROR,
                    "asset_stat_failed",
                    f"Unable to stat asset: {exc}",
                    candidate,
                    relpath=path.as_posix(),
                )
            )
            continue

        metadata: dict[str, Any] = {}
        ok = True
        status = HealthStatus.UNPROBED if mode == ProbeMode.NONE else HealthStatus.OK
        if mode != ProbeMode.NONE:
            if kind == AssetKind.VIDEO:
                metadata, ok = _probe_video(path, mode)
            elif kind == AssetKind.AUDIO:
                metadata, ok = _probe_audio(path, mode)
            elif kind == AssetKind.SENSOR:
                metadata, ok = _probe_sensor(path, mode, config.scan.max_sensor_preview_rows)
            elif kind == AssetKind.IMAGE:
                metadata, ok = _probe_image(path, mode)
            status = HealthStatus.OK if ok else HealthStatus.ERROR

        checksum = _sha256(path) if config.scan.compute_sha256 else None
        asset = AssetProbe(
            asset_id=stable_asset_id(candidate.sample_id, kind.value, relpath, ordinal),
            sample_id=candidate.sample_id,
            kind=kind,
            path=path,
            relpath=relpath,
            ordinal=ordinal,
            size_bytes=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
            status=status,
            metadata=metadata,
            sha256=checksum,
        )
        result.assets.append(asset)
        result.total_bytes += asset.size_bytes

        if not ok:
            result.issues.append(
                _issue(
                    Severity.ERROR,
                    f"{kind.value}_probe_failed",
                    f"Unable to read {kind.value} asset",
                    candidate,
                    relpath=relpath,
                    details=metadata,
                )
            )
        if progress:
            progress(relpath)

    videos = [asset for asset in result.assets if asset.kind == AssetKind.VIDEO]
    audios = [asset for asset in result.assets if asset.kind == AssetKind.AUDIO]
    sensors = [asset for asset in result.assets if asset.kind == AssetKind.SENSOR]
    images = [asset for asset in result.assets if asset.kind == AssetKind.IMAGE]

    result.image_count = len(images)
    result.primary_video_relpath = videos[0].relpath if videos else None
    result.primary_audio_relpath = audios[0].relpath if audios else None
    result.primary_sensor_relpath = sensors[0].relpath if sensors else None

    required = {
        "video": videos,
        "audio": audios,
        "sensor": sensors,
        "image": images,
    }
    for name, assets in required.items():
        if not assets:
            result.issues.append(
                _issue(Severity.ERROR, f"missing_{name}", f"Sample has no {name} asset", candidate)
            )

    for name, assets in (("video", videos), ("audio", audios), ("sensor", sensors)):
        if len(assets) > 1:
            result.issues.append(
                _issue(
                    Severity.WARNING,
                    f"multiple_{name}_assets",
                    f"Sample contains {len(assets)} {name} assets; the first is marked primary",
                    candidate,
                    details={"assets": [asset.relpath for asset in assets]},
                )
            )

    expected_images = config.validation.expected_post_weld_images
    if expected_images and len(images) != expected_images:
        result.issues.append(
            _issue(
                Severity.WARNING,
                "unexpected_image_count",
                f"Expected {expected_images} post-weld images, found {len(images)}",
                candidate,
                details={"expected": expected_images, "actual": len(images)},
            )
        )

    if candidate.metadata.category is None:
        result.issues.append(
            _issue(
                Severity.WARNING, "missing_category", "Sample has no category annotation", candidate
            )
        )
    if candidate.metadata.split is None:
        result.issues.append(
            _issue(Severity.WARNING, "missing_split", "Sample has no split annotation", candidate)
        )

    severities = {issue.severity for issue in result.issues}
    if Severity.ERROR in severities:
        result.health_status = HealthStatus.ERROR
    elif Severity.WARNING in severities:
        result.health_status = HealthStatus.WARNING
    elif mode == ProbeMode.NONE:
        result.health_status = HealthStatus.UNPROBED
    else:
        result.health_status = HealthStatus.OK

    logger.debug(
        "Probed %s assets=%d issues=%d status=%s metadata=%s",
        candidate.relpath,
        len(result.assets),
        len(result.issues),
        result.health_status,
        json.dumps(candidate.metadata.model_dump(mode="json"), ensure_ascii=False),
    )
    return result
