from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from .alignment import AlignmentLimits, AlignmentReport, estimate_sample_alignment
from .index.repository import DatasetRepository

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ALIGNMENT_BATCH_SCHEMA_VERSION = 1
_MODALITIES = ("sensor", "audio", "video")


@dataclass(frozen=True, slots=True)
class AlignmentBatchOptions:
    query: str | None = None
    category: str | None = None
    split: str | None = None
    health: str | None = None
    limit: int | None = None
    workers: int = 4
    batch_size: int = 200
    audio_max_seconds: float = 60.0
    video_max_seconds: float = 60.0
    sensor_max_rows: int = 200_000
    video_max_width: int = 320
    video_analysis_fps: float = 10.0

    def validate(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be positive when supplied")
        if self.workers < 1:
            raise ValueError("workers must be at least 1")
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.alignment_limits().validate()

    def alignment_limits(self) -> AlignmentLimits:
        return AlignmentLimits(
            audio_max_seconds=self.audio_max_seconds,
            video_max_seconds=self.video_max_seconds,
            sensor_max_rows=self.sensor_max_rows,
            video_max_width=self.video_max_width,
            video_analysis_fps=self.video_analysis_fps,
        )


@dataclass(frozen=True, slots=True)
class AlignmentBatchReport:
    schema_version: int
    generated_at: str
    options: dict[str, Any]
    summary: dict[str, Any]
    samples: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(values: list[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def _stats(values: list[float | None]) -> dict[str, float | int | None]:
    data = np.asarray(_finite(values), dtype=np.float64)
    if data.size == 0:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p05": None,
            "p95": None,
            "minimum": None,
            "maximum": None,
        }
    return {
        "count": int(data.size),
        "mean": float(np.mean(data)),
        "median": float(np.median(data)),
        "p05": float(np.percentile(data, 5)),
        "p95": float(np.percentile(data, 95)),
        "minimum": float(np.min(data)),
        "maximum": float(np.max(data)),
    }


def _sample_row(metadata: dict[str, Any], report: AlignmentReport) -> dict[str, Any]:
    estimates = report.estimates
    row: dict[str, Any] = {
        "sample_id": report.sample_id,
        "session_id": metadata.get("session_id"),
        "category": metadata.get("category"),
        "split": metadata.get("split"),
        "health_status": metadata.get("health_status"),
        "reference_modality": report.reference_modality,
        "quality": report.quality,
        "start_spread_s": report.start_spread_s,
        "end_spread_s": report.end_spread_s,
        "duration_spread_s": report.duration_spread_s,
    }
    for modality in _MODALITIES:
        estimate = estimates[modality]
        row[f"{modality}_onset_s"] = estimate.onset_s
        row[f"{modality}_end_s"] = estimate.end_s
        row[f"{modality}_duration_s"] = estimate.duration_s
        row[f"{modality}_confidence"] = estimate.confidence
        row[f"{modality}_offset_s"] = report.offsets_s.get(modality)
        row[f"{modality}_end_offset_s"] = report.end_offsets_s.get(modality)
        row[f"{modality}_error"] = estimate.error
        row[f"{modality}_end_censored"] = estimate.details.get("end_censored")
        row[f"{modality}_analysis_window_truncated"] = estimate.details.get(
            "analysis_window_truncated"
        )
        row[f"{modality}_max_time_gap_s"] = estimate.details.get("max_time_gap_s")
        row[f"{modality}_time_gap_detected"] = estimate.details.get("time_gap_detected")
    return row


def _group_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        grouped[str(value) if value is not None else "<missing>"].append(row)
    result: dict[str, Any] = {}
    for value, group in sorted(grouped.items()):
        result[value] = {
            "samples": len(group),
            "quality_counts": dict(Counter(str(row["quality"]) for row in group)),
            "start_spread_s": _stats([row.get("start_spread_s") for row in group]),
            "duration_spread_s": _stats([row.get("duration_spread_s") for row in group]),
        }
    return result


def _session_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("session_id") or "<missing>")].append(row)
    session_rows: list[dict[str, Any]] = []
    for session_id, group in grouped.items():
        start_values = [row.get("start_spread_s") for row in group]
        duration_values = [row.get("duration_spread_s") for row in group]
        poor = sum(str(row.get("quality")) in {"poor", "insufficient"} for row in group)
        session_rows.append(
            {
                "session_id": session_id,
                "samples": len(group),
                "poor_or_insufficient_samples": poor,
                "start_spread_s": _stats(start_values),
                "duration_spread_s": _stats(duration_values),
            }
        )
    session_rows.sort(
        key=lambda item: (
            -item["poor_or_insufficient_samples"],
            -float(item["start_spread_s"]["p95"] or 0.0),
            item["session_id"],
        )
    )
    return {
        "sessions": len(session_rows),
        "worst_sessions": session_rows[:25],
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    quality_counts = Counter(str(row.get("quality")) for row in rows)
    modality_success: dict[str, Any] = {}
    for modality in _MODALITIES:
        success = sum(row.get(f"{modality}_onset_s") is not None for row in rows)
        interval = sum(
            row.get(f"{modality}_onset_s") is not None and row.get(f"{modality}_end_s") is not None
            for row in rows
        )
        errors = Counter(
            str(row[f"{modality}_error"]) for row in rows if row.get(f"{modality}_error")
        )
        modality_success[modality] = {
            "onset_success": success,
            "interval_success": interval,
            "onset_success_fraction": float(success / len(rows)) if rows else 0.0,
            "interval_success_fraction": float(interval / len(rows)) if rows else 0.0,
            "duration_s": _stats([row.get(f"{modality}_duration_s") for row in rows]),
            "confidence": _stats([row.get(f"{modality}_confidence") for row in rows]),
            "end_censored": sum(bool(row.get(f"{modality}_end_censored")) for row in rows),
            "analysis_window_truncated": sum(
                bool(row.get(f"{modality}_analysis_window_truncated")) for row in rows
            ),
            "time_gap_detected": sum(
                bool(row.get(f"{modality}_time_gap_detected")) for row in rows
            ),
            "max_time_gap_s": _stats([row.get(f"{modality}_max_time_gap_s") for row in rows]),
            "top_errors": [
                {"error": error, "count": count} for error, count in errors.most_common(10)
            ],
        }

    return {
        "samples": len(rows),
        "quality_counts": dict(quality_counts),
        "start_spread_s": _stats([row.get("start_spread_s") for row in rows]),
        "end_spread_s": _stats([row.get("end_spread_s") for row in rows]),
        "duration_spread_s": _stats([row.get("duration_spread_s") for row in rows]),
        "start_offsets_s": {
            modality: _stats([row.get(f"{modality}_offset_s") for row in rows])
            for modality in _MODALITIES
        },
        "end_offsets_s": {
            modality: _stats([row.get(f"{modality}_end_offset_s") for row in rows])
            for modality in _MODALITIES
        },
        "modalities": modality_success,
        "by_split": _group_summary(rows, "split"),
        "by_category": _group_summary(rows, "category"),
        "sessions": _session_summary(rows),
    }


def _selected_metadata(
    repository: DatasetRepository,
    options: AlignmentBatchOptions,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    remaining = options.limit
    offset = 0
    while remaining is None or remaining > 0:
        request = options.batch_size if remaining is None else min(options.batch_size, remaining)
        batch = repository.list_samples(
            query=options.query,
            category=options.category,
            split=options.split,
            health=options.health,
            limit=request,
            offset=offset,
            sort_by="sample_id",
        )
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if remaining is not None:
            remaining -= len(batch)
        if len(batch) < request:
            break
    return rows


def run_alignment_batch(
    repository: DatasetRepository,
    *,
    options: AlignmentBatchOptions | None = None,
) -> AlignmentBatchReport:
    selected = options or AlignmentBatchOptions()
    selected.validate()
    alignment_limits = selected.alignment_limits()
    metadata_rows = _selected_metadata(repository, selected)
    result_rows: list[dict[str, Any]] = []

    def analyze(metadata: dict[str, Any]) -> dict[str, Any]:
        sample_id = str(metadata["sample_id"])
        sample = repository.get_sample(sample_id)
        if sample is None:
            return {
                "sample_id": sample_id,
                "session_id": metadata.get("session_id"),
                "category": metadata.get("category"),
                "split": metadata.get("split"),
                "health_status": metadata.get("health_status"),
                "reference_modality": None,
                "quality": "insufficient",
                "batch_error": "sample disappeared during alignment batch",
            }
        try:
            return _sample_row(
                metadata,
                estimate_sample_alignment(sample, limits=alignment_limits),
            )
        except Exception as exc:
            return {
                "sample_id": sample_id,
                "session_id": metadata.get("session_id"),
                "category": metadata.get("category"),
                "split": metadata.get("split"),
                "health_status": metadata.get("health_status"),
                "reference_modality": None,
                "quality": "insufficient",
                "batch_error": f"{type(exc).__name__}: {exc}",
            }

    with ThreadPoolExecutor(
        max_workers=selected.workers, thread_name_prefix="weld-align"
    ) as executor:
        futures = {executor.submit(analyze, metadata): metadata for metadata in metadata_rows}
        for future in as_completed(futures):
            result_rows.append(future.result())

    result_rows.sort(key=lambda row: str(row.get("sample_id") or ""))
    return AlignmentBatchReport(
        schema_version=ALIGNMENT_BATCH_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        options=asdict(selected),
        summary=_summarize(result_rows),
        samples=result_rows,
    )


def write_alignment_batch_json(report: AlignmentBatchReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def write_alignment_batch_csv(report: AlignmentBatchReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    seen: set[str] = set()
    for row in report.samples:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in report.samples:
            writer.writerow(row)
    return destination


def _plot_offsets(report: AlignmentBatchReport, output: Path) -> Path | None:
    series = []
    labels = []
    for modality in ("audio", "video"):
        values = _finite([row.get(f"{modality}_offset_s") for row in report.samples])
        if values:
            series.append(values)
            labels.append(modality)
    if not series:
        return None
    figure, axis = plt.subplots(figsize=(8.0, 4.8))
    axis.boxplot(series, tick_labels=labels, showfliers=True)
    axis.axhline(0.0, linewidth=1.0)
    axis.set_ylabel("Start offset to reference (s)")
    axis.set_title("Multimodal welding onset offsets")
    axis.grid(True, axis="y", alpha=0.2)
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)
    return output


def _plot_spreads(report: AlignmentBatchReport, output: Path) -> Path | None:
    values = _finite([row.get("start_spread_s") for row in report.samples])
    if not values:
        return None
    figure, axis = plt.subplots(figsize=(8.0, 4.8))
    bins = min(max(round(math.sqrt(len(values))), 5), 40)
    axis.hist(values, bins=bins)
    axis.set_xlabel("Max onset spread across modalities (s)")
    axis.set_ylabel("Samples")
    axis.set_title("Alignment start-spread distribution")
    axis.grid(True, axis="y", alpha=0.2)
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)
    return output


def _plot_durations(report: AlignmentBatchReport, output: Path) -> Path | None:
    series = []
    labels = []
    for modality in _MODALITIES:
        values = _finite([row.get(f"{modality}_duration_s") for row in report.samples])
        if values:
            series.append(values)
            labels.append(modality)
    if not series:
        return None
    figure, axis = plt.subplots(figsize=(8.0, 4.8))
    axis.boxplot(series, tick_labels=labels, showfliers=True)
    axis.set_ylabel("Estimated active duration (s)")
    axis.set_title("Per-modality welding activity duration")
    axis.grid(True, axis="y", alpha=0.2)
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)
    return output


def write_alignment_plots(report: AlignmentBatchReport, output_dir: Path) -> list[Path]:
    destination = output_dir.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    outputs = [
        _plot_offsets(report, destination / "start-offsets.png"),
        _plot_spreads(report, destination / "start-spread-histogram.png"),
        _plot_durations(report, destination / "active-durations.png"),
    ]
    return [path for path in outputs if path is not None]
