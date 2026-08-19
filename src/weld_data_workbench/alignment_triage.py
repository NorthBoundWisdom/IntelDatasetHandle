from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

TRIAGE_SCHEMA_VERSION = 1
_MODALITIES = ("sensor", "audio", "video")


@dataclass(frozen=True, slots=True)
class AlignmentTriageCase:
    rank: int
    sample_id: str
    session_id: str | None
    category: str | None
    split: str | None
    quality: str
    score: float
    reasons: tuple[str, ...]
    start_spread_s: float | None
    end_spread_s: float | None
    duration_spread_s: float | None
    sensor_time_gap_s: float | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True, slots=True)
class AlignmentTriageReport:
    schema_version: int
    source_schema_version: int | None
    sample_count: int
    selected_count: int
    cases: tuple[AlignmentTriageCase, ...]
    reason_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_schema_version": self.source_schema_version,
            "sample_count": self.sample_count,
            "selected_count": self.selected_count,
            "cases": [case.to_dict() for case in self.cases],
            "reason_counts": dict(sorted(self.reason_counts.items())),
        }


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _reason_score(row: dict[str, Any]) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []
    score = 0.0

    quality = str(row.get("quality") or "unknown").casefold()
    if quality == "insufficient":
        reasons.append("insufficient_modalities")
        score += 12.0
    elif quality == "partial":
        reasons.append("partial_modalities")
        score += 8.0
    elif quality == "poor":
        reasons.append("poor_alignment")
        score += 5.0
    elif quality == "warning":
        reasons.append("alignment_warning")
        score += 2.0

    start_spread = _finite(row.get("start_spread_s"))
    if start_spread is not None:
        score += min(start_spread, 30.0)
        if start_spread >= 5.0:
            reasons.append("large_onset_spread")
        elif start_spread >= 2.0:
            reasons.append("moderate_onset_spread")

    duration_spread = _finite(row.get("duration_spread_s"))
    if duration_spread is not None:
        score += min(duration_spread / 2.0, 20.0)
        if duration_spread >= 10.0:
            reasons.append("large_duration_spread")
        elif duration_spread >= 5.0:
            reasons.append("moderate_duration_spread")

    end_spread = _finite(row.get("end_spread_s"))
    if end_spread is not None and end_spread >= 5.0:
        reasons.append("large_end_spread")
        score += min(end_spread / 4.0, 10.0)

    for modality in _MODALITIES:
        if row.get(f"{modality}_error"):
            reasons.append(f"{modality}_error")
            score += 8.0
        if bool(row.get(f"{modality}_analysis_window_truncated")):
            reasons.append(f"{modality}_analysis_window_truncated")
            score += 10.0
        if bool(row.get(f"{modality}_end_censored")):
            reasons.append(f"{modality}_end_censored")
            score += 3.0

    sensor_gap = _finite(row.get("sensor_max_time_gap_s"))
    if bool(row.get("sensor_time_gap_detected")) or (sensor_gap is not None and sensor_gap > 1.0):
        reasons.append("sensor_time_gap")
        score += 15.0 + min((sensor_gap or 0.0) / 10.0, 10.0)

    if not reasons:
        reasons.append("low_priority_review")
    return score, tuple(dict.fromkeys(reasons))


def _load_source(source: Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = source.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Alignment batch report must be a JSON object")
    return payload


def triage_alignment_batch(
    source: Path | dict[str, Any],
    *,
    limit: int = 100,
    include_good: bool = False,
) -> AlignmentTriageReport:
    if limit < 1:
        raise ValueError("limit must be positive")
    payload = _load_source(source)
    raw_samples = payload.get("samples", [])
    if not isinstance(raw_samples, list):
        raise ValueError("Alignment batch report samples must be a list")

    scored: list[tuple[float, tuple[str, ...], dict[str, Any]]] = []
    reason_counts: dict[str, int] = {}
    for raw in raw_samples:
        if not isinstance(raw, dict):
            continue
        quality = str(raw.get("quality") or "unknown").casefold()
        if not include_good and quality == "good":
            continue
        score, reasons = _reason_score(raw)
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        scored.append((score, reasons, raw))

    scored.sort(
        key=lambda item: (
            -item[0],
            -float(_finite(item[2].get("start_spread_s")) or 0.0),
            str(item[2].get("session_id") or ""),
            str(item[2].get("sample_id") or ""),
        )
    )

    cases: list[AlignmentTriageCase] = []
    for rank, (score, reasons, row) in enumerate(scored[:limit], start=1):
        cases.append(
            AlignmentTriageCase(
                rank=rank,
                sample_id=str(row.get("sample_id") or ""),
                session_id=None if row.get("session_id") is None else str(row.get("session_id")),
                category=None if row.get("category") is None else str(row.get("category")),
                split=None if row.get("split") is None else str(row.get("split")),
                quality=str(row.get("quality") or "unknown"),
                score=float(score),
                reasons=reasons,
                start_spread_s=_finite(row.get("start_spread_s")),
                end_spread_s=_finite(row.get("end_spread_s")),
                duration_spread_s=_finite(row.get("duration_spread_s")),
                sensor_time_gap_s=_finite(row.get("sensor_max_time_gap_s")),
            )
        )

    source_schema = payload.get("schema_version")
    return AlignmentTriageReport(
        schema_version=TRIAGE_SCHEMA_VERSION,
        source_schema_version=int(source_schema) if isinstance(source_schema, int) else None,
        sample_count=len(raw_samples),
        selected_count=len(cases),
        cases=tuple(cases),
        reason_counts=reason_counts,
    )


def write_alignment_triage_json(report: AlignmentTriageReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def write_alignment_triage_csv(report: AlignmentTriageReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "sample_id",
        "session_id",
        "category",
        "split",
        "quality",
        "score",
        "reasons",
        "start_spread_s",
        "end_spread_s",
        "duration_spread_s",
        "sensor_time_gap_s",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in report.cases:
            row = case.to_dict()
            row["reasons"] = ";".join(case.reasons)
            writer.writerow(row)
    return destination


def triage_sample_ids(report: AlignmentTriageReport) -> Iterable[str]:
    return (case.sample_id for case in report.cases)
