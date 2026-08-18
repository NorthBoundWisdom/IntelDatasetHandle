from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .common import safe_float


def _single_image_features(path: Path) -> dict[str, float]:
    with Image.open(path) as image:
        rgb = np.asarray(
            image.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR), dtype=np.float32
        )

    gray = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2HSV)
    edges = cv2.Canny(gray, 80, 160)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F)

    return {
        "brightness": float(gray.mean()),
        "contrast": float(gray.std()),
        "red_mean": float(rgb[..., 0].mean()),
        "green_mean": float(rgb[..., 1].mean()),
        "blue_mean": float(rgb[..., 2].mean()),
        "saturation_mean": float(hsv[..., 1].mean()),
        "edge_density": float(np.mean(edges > 0)),
        "sharpness_laplacian_var": float(laplacian.var()),
    }


def extract_image_features(paths: list[Path]) -> dict[str, float | int | None]:
    rows: list[dict[str, float]] = []
    for path in paths:
        try:
            rows.append(_single_image_features(path))
        except Exception:
            continue

    features: dict[str, float | int | None] = {
        "image_requested_count": len(paths),
        "image_decoded_count": len(rows),
    }
    if not rows:
        return features

    keys = sorted(rows[0])
    for key in keys:
        values = np.asarray([row[key] for row in rows], dtype=np.float64)
        features[f"image_{key}_mean"] = safe_float(values.mean())
        features[f"image_{key}_std"] = safe_float(values.std())
        features[f"image_{key}_min"] = safe_float(values.min())
        features[f"image_{key}_max"] = safe_float(values.max())
    return features
