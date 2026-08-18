from __future__ import annotations

import math
import re
from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf


def finite_array(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values)
    return array[np.isfinite(array)]


def safe_float(value: float | np.floating | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def feature_name(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip().casefold()).strip("_")
    return text or "unnamed"


def read_uniform_audio(
    path: Path,
    *,
    segments: int = 8,
    seconds_per_segment: float = 1.0,
) -> tuple[np.ndarray, int, int, float]:
    with sf.SoundFile(str(path)) as handle:
        sample_rate = int(handle.samplerate)
        channels = int(handle.channels)
        total_frames = int(handle.frames)
        duration = float(total_frames / sample_rate) if sample_rate else 0.0
        segment_frames = max(1, int(seconds_per_segment * sample_rate))

        if total_frames <= segment_frames * segments:
            handle.seek(0)
            data = handle.read(total_frames, dtype="float32", always_2d=True)
        else:
            starts = np.linspace(0, total_frames - segment_frames, num=segments, dtype=np.int64)
            parts: list[np.ndarray] = []
            for start in starts:
                handle.seek(int(start))
                parts.append(handle.read(segment_frames, dtype="float32", always_2d=True))
            data = (
                np.concatenate(parts, axis=0)
                if parts
                else np.empty((0, channels), dtype=np.float32)
            )

    mono = data.mean(axis=1) if data.ndim == 2 else data
    return mono.astype(np.float32, copy=False), sample_rate, channels, duration


def sample_video_frames(
    path: Path, count: int = 16
) -> tuple[list[np.ndarray], dict[str, float | int | None]]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"OpenCV cannot open {path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = frame_count / fps if frame_count > 0 and fps > 0 else None

    frames: list[np.ndarray] = []
    if frame_count > 0:
        positions: Iterable[int] = np.linspace(
            0, frame_count - 1, num=min(count, frame_count), dtype=int
        )
        for position in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(position))
            ok, frame = capture.read()
            if ok and frame is not None and frame.size:
                frames.append(frame)
    else:
        for _ in range(count):
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)

    capture.release()
    return frames, {
        "fps": fps or None,
        "frame_count": frame_count or None,
        "width": width or None,
        "height": height or None,
        "duration_s": duration,
    }
