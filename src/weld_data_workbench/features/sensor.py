from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import feature_name, safe_float


def extract_sensor_features(
    path: Path,
    *,
    max_rows: int = 200_000,
    max_columns: int = 32,
) -> dict[str, float | int | None]:
    frame = pd.read_csv(path, sep=None, engine="python", nrows=max_rows)
    numeric = frame.select_dtypes(include=["number"]).iloc[:, :max_columns]

    features: dict[str, float | int | None] = {
        "sensor_rows_loaded": len(frame),
        "sensor_columns": len(frame.columns),
        "sensor_numeric_columns": len(numeric.columns),
        "sensor_missing_fraction": safe_float(frame.isna().to_numpy().mean())
        if frame.size
        else 0.0,
    }

    if numeric.empty:
        return features

    per_column_missing: list[float] = []
    per_column_std: list[float] = []
    for column in numeric.columns:
        name = feature_name(column)
        series = pd.to_numeric(numeric[column], errors="coerce")
        values = series.to_numpy(dtype=np.float64)
        finite = values[np.isfinite(values)]
        missing = float(1.0 - finite.size / max(values.size, 1))
        per_column_missing.append(missing)

        prefix = f"sensor_{name}"
        features[f"{prefix}_missing_fraction"] = missing
        if finite.size == 0:
            for suffix in (
                "mean",
                "std",
                "min",
                "max",
                "q05",
                "q50",
                "q95",
                "diff_abs_mean",
                "diff_std",
            ):
                features[f"{prefix}_{suffix}"] = None
            continue

        std = float(np.std(finite))
        per_column_std.append(std)
        diffs = np.diff(finite)
        features.update(
            {
                f"{prefix}_mean": safe_float(np.mean(finite)),
                f"{prefix}_std": safe_float(std),
                f"{prefix}_min": safe_float(np.min(finite)),
                f"{prefix}_max": safe_float(np.max(finite)),
                f"{prefix}_q05": safe_float(np.quantile(finite, 0.05)),
                f"{prefix}_q50": safe_float(np.quantile(finite, 0.50)),
                f"{prefix}_q95": safe_float(np.quantile(finite, 0.95)),
                f"{prefix}_diff_abs_mean": safe_float(np.mean(np.abs(diffs)))
                if diffs.size
                else 0.0,
                f"{prefix}_diff_std": safe_float(np.std(diffs)) if diffs.size else 0.0,
            }
        )

    features["sensor_column_missing_mean"] = safe_float(np.mean(per_column_missing))
    features["sensor_column_std_mean"] = (
        safe_float(np.mean(per_column_std)) if per_column_std else None
    )
    features["sensor_column_std_max"] = (
        safe_float(np.max(per_column_std)) if per_column_std else None
    )
    return features
