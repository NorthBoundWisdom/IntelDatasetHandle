from __future__ import annotations

import json
import math
import platform
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None  # type: ignore[assignment]

import numpy as np
import pandas as pd

PREDICTION_SCHEMA_VERSION = 1
DEFAULT_MODALITIES = ("audio", "video", "sensor", "image")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class InferenceTelemetry:
    latency_ms: float
    process_cpu_ms: float
    peak_rss_mb: float | None
    device: str | None = None
    batch_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _peak_rss_mb() -> float | None:
    if resource is None:
        return None
    try:
        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    # macOS reports bytes; Linux/BSD normally report KiB.
    if platform.system() == "Darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def measure_inference(
    operation: Callable[[], T],
    *,
    device: str | None = None,
    batch_size: int | None = None,
) -> tuple[T, InferenceTelemetry]:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    result = operation()
    telemetry = InferenceTelemetry(
        latency_ms=(time.perf_counter() - wall_start) * 1000.0,
        process_cpu_ms=(time.process_time() - cpu_start) * 1000.0,
        peak_rss_mb=_peak_rss_mb(),
        device=device,
        batch_size=batch_size,
    )
    return result, telemetry


def modality_score_column(modality: str) -> str:
    return f"score_{modality}"


def modality_available_column(modality: str) -> str:
    return f"available_{modality}"


def modality_reliability_column(modality: str) -> str:
    return f"reliability_{modality}"


def _coerce_bool_series(series: pd.Series, name: str) -> pd.Series:
    if series.dtype == bool:
        return series.astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="raise")
        if not numeric.isin([0, 1]).all():
            raise ValueError(f"{name} must contain only boolean/0/1 values")
        return numeric.astype(bool)
    normalized = series.astype(str).str.strip().str.casefold()
    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
        "yes": True,
        "no": False,
    }
    unknown = sorted(set(normalized) - set(mapping))
    if unknown:
        raise ValueError(f"{name} contains unsupported boolean values: {unknown[:5]}")
    return normalized.map(mapping).astype(bool)


def normalize_prediction_frame(
    frame: pd.DataFrame,
    *,
    modalities: Iterable[str] = DEFAULT_MODALITIES,
    require_labels: bool = False,
    require_score: bool = False,
    score_col: str = "anomaly_score",
    label_col: str = "is_anomaly",
) -> pd.DataFrame:
    """Validate and normalize the common model-prediction artifact contract.

    A prediction row is sample-oriented. `anomaly_score` is the model/fused score
    where larger means more anomalous. Per-modality scores, availability and
    reliability fields are optional, which allows unimodal and fusion models to use
    the same file format. Inference telemetry is also optional but standardized.

    Persisted prediction artifacts require `sample_id`. For backwards-compatible
    in-memory evaluation, a labeled frame may omit it; deterministic ephemeral row
    identifiers are inserted so metric computation remains sample-oriented without
    weakening the serialization boundary.
    """

    clean = frame.copy()
    if "sample_id" not in clean.columns:
        if not require_labels:
            raise ValueError("Prediction frame must contain sample_id")
        clean.insert(
            0,
            "sample_id",
            [f"row-{position:08d}" for position in range(len(clean))],
        )
    clean["sample_id"] = clean["sample_id"].astype(str)
    if clean["sample_id"].eq("").any():
        raise ValueError("sample_id cannot be empty")
    if clean["sample_id"].duplicated().any():
        duplicates = clean.loc[clean["sample_id"].duplicated(), "sample_id"].tolist()
        raise ValueError(f"Prediction frame contains duplicate sample_id values: {duplicates[:5]}")

    if score_col in clean.columns:
        clean[score_col] = pd.to_numeric(clean[score_col], errors="coerce")
    elif require_score:
        raise ValueError(f"Prediction frame must contain {score_col}")

    if label_col in clean.columns:
        clean[label_col] = pd.to_numeric(clean[label_col], errors="raise").astype(int)
        if not clean[label_col].isin([0, 1]).all():
            raise ValueError(f"{label_col} must contain only 0/1 values")
    elif require_labels:
        raise ValueError(f"Prediction frame must contain {label_col}")

    normalized_modalities = tuple(dict.fromkeys(str(value).casefold() for value in modalities))
    for modality in normalized_modalities:
        score_name = modality_score_column(modality)
        available_name = modality_available_column(modality)
        reliability_name = modality_reliability_column(modality)
        if score_name in clean.columns:
            clean[score_name] = pd.to_numeric(clean[score_name], errors="coerce")
        if available_name in clean.columns:
            clean[available_name] = _coerce_bool_series(clean[available_name], available_name)
        elif score_name in clean.columns:
            clean[available_name] = np.isfinite(clean[score_name].to_numpy(dtype=float))
        if reliability_name in clean.columns:
            clean[reliability_name] = pd.to_numeric(clean[reliability_name], errors="coerce")
            finite = clean[reliability_name].dropna()
            if ((finite < 0.0) | (finite > 1.0)).any():
                raise ValueError(f"{reliability_name} must be within [0, 1]")

    for numeric_column in (
        "inference_latency_ms",
        "process_cpu_ms",
        "peak_rss_mb",
    ):
        if numeric_column in clean.columns:
            clean[numeric_column] = pd.to_numeric(clean[numeric_column], errors="coerce")
            finite = clean[numeric_column].dropna()
            if (finite < 0).any():
                raise ValueError(f"{numeric_column} cannot be negative")

    if "batch_size" in clean.columns:
        numeric_batch = pd.to_numeric(clean["batch_size"], errors="coerce")
        finite = numeric_batch.dropna()
        if ((finite < 1) | ((finite % 1) != 0)).any():
            raise ValueError("batch_size must contain positive integers")
        clean["batch_size"] = numeric_batch.astype("Int64")

    return clean


def availability_pattern(
    row: pd.Series | dict[str, Any],
    modalities: Iterable[str] = DEFAULT_MODALITIES,
) -> str:
    available: list[str] = []
    missing: list[str] = []
    for modality in modalities:
        name = str(modality).casefold()
        availability_name = modality_available_column(name)
        score_name = modality_score_column(name)
        value = row.get(availability_name)
        if value is None:
            score = row.get(score_name)
            present = score is not None and not (isinstance(score, float) and math.isnan(score))
        else:
            present = bool(value)
        (available if present else missing).append(name)
    available_text = "+".join(available) if available else "none"
    missing_text = "+".join(missing) if missing else "none"
    return f"available={available_text};missing={missing_text}"


def attach_telemetry(
    frame: pd.DataFrame,
    telemetry: InferenceTelemetry,
    *,
    rows: Iterable[int] | None = None,
) -> pd.DataFrame:
    output = frame.copy()
    target = output.index if rows is None else list(rows)
    values = telemetry.to_dict()
    mapping = {
        "latency_ms": "inference_latency_ms",
        "process_cpu_ms": "process_cpu_ms",
        "peak_rss_mb": "peak_rss_mb",
        "device": "device",
        "batch_size": "batch_size",
    }
    for source, destination in mapping.items():
        value = values[source]
        if value is not None:
            output.loc[target, destination] = value
    return output


def prediction_metadata(
    *,
    model_name: str,
    modalities: Iterable[str],
    score_semantics: str = "higher_is_more_anomalous",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "model_name": model_name,
        "modalities": [str(value).casefold() for value in modalities],
        "score_semantics": score_semantics,
        "telemetry_fields": [
            "inference_latency_ms",
            "process_cpu_ms",
            "peak_rss_mb",
            "device",
            "batch_size",
        ],
    }
    if extra:
        metadata["extra"] = extra
    return metadata


def write_prediction_artifact(
    frame: pd.DataFrame,
    path: Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_prediction_frame(frame)
    suffix = destination.suffix.casefold()
    if suffix == ".parquet":
        normalized.to_parquet(destination, index=False)
    elif suffix in {".jsonl", ".ndjson"}:
        normalized.to_json(destination, orient="records", lines=True, force_ascii=False)
    else:
        normalized.to_csv(destination, index=False)
    if metadata is not None:
        metadata_path = destination.with_suffix(destination.suffix + ".meta.json")
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return destination
