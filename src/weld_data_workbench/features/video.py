from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .common import safe_float, sample_video_frames


def extract_video_features(path: Path, *, frame_samples: int = 16) -> dict[str, float | int | None]:
    frames, metadata = sample_video_frames(path, count=frame_samples)
    features: dict[str, float | int | None] = {
        "video_fps": metadata["fps"],
        "video_frame_count": metadata["frame_count"],
        "video_width": metadata["width"],
        "video_height": metadata["height"],
        "video_duration_s": metadata["duration_s"],
        "video_sampled_frames": len(frames),
    }
    if not frames:
        return features

    brightness: list[float] = []
    contrast: list[float] = []
    saturation: list[float] = []
    edge_density: list[float] = []
    motion: list[float] = []
    previous_gray: np.ndarray | None = None

    for frame in frames:
        small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        edges = cv2.Canny(gray, 80, 160)
        brightness.append(float(gray.mean()))
        contrast.append(float(gray.std()))
        saturation.append(float(hsv[..., 1].mean()))
        edge_density.append(float(np.mean(edges > 0)))
        if previous_gray is not None:
            motion.append(float(np.mean(cv2.absdiff(gray, previous_gray))))
        previous_gray = gray

    for name, values in (
        ("brightness", brightness),
        ("contrast", contrast),
        ("saturation", saturation),
        ("edge_density", edge_density),
        ("motion_l1", motion),
    ):
        if values:
            array = np.asarray(values, dtype=np.float64)
            features[f"video_{name}_mean"] = safe_float(array.mean())
            features[f"video_{name}_std"] = safe_float(array.std())
            features[f"video_{name}_max"] = safe_float(array.max())
        else:
            features[f"video_{name}_mean"] = None
            features[f"video_{name}_std"] = None
            features[f"video_{name}_max"] = None
    return features
