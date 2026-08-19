from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .index.repository import DatasetRepository

DIMENSION_FIELDS = {
    "category",
    "split",
    "weld_type",
    "steel_type",
    "thickness_mm",
    "session_id",
    "health_status",
}
NUMERIC_FIELDS = {
    "thickness_mm",
    "current_a",
    "voltage_v",
    "gas_bar",
    "robot_speed_cpm",
    "total_bytes",
    "image_count",
}
DISTRIBUTION_FIELDS = DIMENSION_FIELDS | NUMERIC_FIELDS
PROCESS_NUMERIC_FIELDS = (
    "thickness_mm",
    "current_a",
    "voltage_v",
    "gas_bar",
    "robot_speed_cpm",
)
PROCESS_CATEGORICAL_FIELDS = ("weld_type", "steel_type")
PIVOT_MEASURES = {"count", "mean", "median", "sum", "min", "max"}


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _label(value: Any) -> str:
    return "Unknown" if pd.isna(value) else str(value)


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


@dataclass(frozen=True, slots=True)
class GoodMatch:
    sample_id: str
    session_id: str
    category: str | None
    split: str | None
    distance: float
    distance_terms: dict[str, float]
    process: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AnalysisService:
    """Read-only comparison and aggregate analysis over the canonical index."""

    def __init__(self, repository: DatasetRepository):
        self.repository = repository

    def _records(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        split: str | None = None,
        health: str | None = None,
    ) -> list[dict[str, Any]]:
        return list(
            self.repository.iter_samples(
                batch_size=1000,
                query=query,
                category=category,
                split=split,
                health=health,
            )
        )

    @staticmethod
    def _robust_scales(records: list[dict[str, Any]]) -> dict[str, float]:
        scales: dict[str, float] = {}
        for field in PROCESS_NUMERIC_FIELDS:
            values = [
                numeric
                for record in records
                if (numeric := _finite_float(record.get(field))) is not None
            ]
            if len(values) < 2:
                scales[field] = 1.0
                continue
            array = np.asarray(values, dtype=float)
            q25, q75 = np.quantile(array, [0.25, 0.75])
            scale = float(q75 - q25)
            if not np.isfinite(scale) or scale <= 1e-12:
                scale = float(np.std(array))
            scales[field] = scale if np.isfinite(scale) and scale > 1e-12 else 1.0
        return scales

    @staticmethod
    def _distance(
        target: dict[str, Any],
        candidate: dict[str, Any],
        scales: dict[str, float],
    ) -> tuple[float, dict[str, float]]:
        terms: dict[str, float] = {}
        for field in PROCESS_CATEGORICAL_FIELDS:
            left = target.get(field)
            right = candidate.get(field)
            if left is None and right is None:
                terms[field] = 0.0
            elif left is None or right is None:
                terms[field] = 0.5
            else:
                terms[field] = 0.0 if str(left).casefold() == str(right).casefold() else 2.0

        for field in PROCESS_NUMERIC_FIELDS:
            left = _finite_float(target.get(field))
            right = _finite_float(candidate.get(field))
            if left is None and right is None:
                terms[field] = 0.0
            elif left is None or right is None:
                terms[field] = 1.0
            else:
                terms[field] = abs(left - right) / scales[field]
        return float(sum(terms.values())), terms

    def good_matches(
        self,
        sample_id: str,
        *,
        limit: int = 5,
        same_split: bool = False,
    ) -> list[dict[str, Any]]:
        target = self.repository.get_sample(sample_id)
        if target is None:
            raise KeyError(f"Unknown sample: {sample_id}")

        good_records = [
            record
            for record in self._records()
            if bool(record.get("is_good"))
            and record["sample_id"] != sample_id
            and (not same_split or record.get("split") == target.get("split"))
        ]
        if not good_records:
            return []
        scales = self._robust_scales(good_records)

        matches: list[GoodMatch] = []
        for candidate in good_records:
            distance, terms = self._distance(target, candidate, scales)
            process = {
                field: candidate.get(field)
                for field in (*PROCESS_CATEGORICAL_FIELDS, *PROCESS_NUMERIC_FIELDS)
            }
            matches.append(
                GoodMatch(
                    sample_id=str(candidate["sample_id"]),
                    session_id=str(candidate["session_id"]),
                    category=None
                    if candidate.get("category") is None
                    else str(candidate["category"]),
                    split=None if candidate.get("split") is None else str(candidate["split"]),
                    distance=distance,
                    distance_terms=terms,
                    process=process,
                )
            )
        matches.sort(key=lambda item: (item.distance, item.sample_id))
        return [item.to_dict() for item in matches[: min(max(int(limit), 1), 100)]]

    def distribution(
        self,
        field: str,
        *,
        bins: int = 20,
        query: str | None = None,
        category: str | None = None,
        split: str | None = None,
        health: str | None = None,
    ) -> dict[str, Any]:
        if field not in DISTRIBUTION_FIELDS:
            raise ValueError(f"Unsupported distribution field: {field}")
        records = self._records(query=query, category=category, split=split, health=health)
        frame = pd.DataFrame.from_records(records)
        if frame.empty:
            return {"field": field, "kind": "empty", "sample_count": 0, "items": []}

        if field in NUMERIC_FIELDS:
            numeric = pd.to_numeric(frame[field], errors="coerce")
            finite = numeric[np.isfinite(numeric.to_numpy(dtype=float))]
            null_count = int(len(numeric) - len(finite))
            if finite.empty:
                return {
                    "field": field,
                    "kind": "numeric",
                    "sample_count": len(frame),
                    "null_count": null_count,
                    "bins": [],
                }
            count, edges = np.histogram(
                finite.to_numpy(dtype=float),
                bins=min(max(int(bins), 1), 100),
            )
            return {
                "field": field,
                "kind": "numeric",
                "sample_count": len(frame),
                "null_count": null_count,
                "min": float(finite.min()),
                "max": float(finite.max()),
                "bins": [
                    {
                        "left": float(edges[index]),
                        "right": float(edges[index + 1]),
                        "count": int(count[index]),
                    }
                    for index in range(len(count))
                ],
            }

        counts = frame[field].map(_label).value_counts(dropna=False)
        items = [
            {"label": str(label), "count": int(count)}
            for label, count in sorted(
                counts.items(),
                key=lambda item: (-int(item[1]), str(item[0])),
            )
        ]
        return {
            "field": field,
            "kind": "categorical",
            "sample_count": len(frame),
            "items": items,
        }

    def pivot(
        self,
        *,
        row: str,
        column: str | None = None,
        measure: str = "count",
        value: str | None = None,
        query: str | None = None,
        category: str | None = None,
        split: str | None = None,
        health: str | None = None,
        limit: int = 5000,
    ) -> dict[str, Any]:
        if row not in DIMENSION_FIELDS:
            raise ValueError(f"Unsupported pivot row: {row}")
        if column is not None and column not in DIMENSION_FIELDS:
            raise ValueError(f"Unsupported pivot column: {column}")
        measure = measure.casefold()
        if measure not in PIVOT_MEASURES:
            raise ValueError(f"Unsupported pivot measure: {measure}")
        if measure != "count" and value not in NUMERIC_FIELDS:
            raise ValueError(f"Pivot measure {measure} requires a numeric value field")

        records = self._records(query=query, category=category, split=split, health=health)
        frame = pd.DataFrame.from_records(records)
        group_fields = [row] + ([column] if column is not None else [])
        if frame.empty:
            return {
                "row": row,
                "column": column,
                "measure": measure,
                "value": value,
                "sample_count": 0,
                "records": [],
            }

        if measure == "count":
            grouped = frame.groupby(group_fields, dropna=False).size().reset_index(name="value")
        else:
            assert value is not None
            frame[value] = pd.to_numeric(frame[value], errors="coerce")
            grouped = (
                frame.groupby(group_fields, dropna=False)[value]
                .agg(measure)
                .reset_index(name="value")
            )
            grouped = grouped[grouped["value"].notna()]

        cap = min(max(int(limit), 1), 50_000)
        if len(grouped) > cap:
            raise ValueError(
                f"Pivot cardinality {len(grouped)} exceeds limit {cap}; refine filters"
            )
        grouped = grouped.sort_values(group_fields, kind="stable", na_position="last")
        output_records = [
            {
                **{field: _json_value(record[field]) for field in group_fields},
                "value": _json_value(record["value"]),
            }
            for record in grouped.to_dict(orient="records")
        ]
        return {
            "row": row,
            "column": column,
            "measure": measure,
            "value": value,
            "sample_count": len(frame),
            "records": output_records,
        }
