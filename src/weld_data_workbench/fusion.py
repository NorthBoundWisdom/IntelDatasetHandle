from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from .prediction_contract import (
    modality_available_column,
    modality_reliability_column,
    normalize_prediction_frame,
)

FusionObjective = Literal["roc_auc", "pr_auc"]


@dataclass(frozen=True, slots=True)
class ScoreStandardizer:
    score_columns: tuple[str, ...]
    center: dict[str, float]
    scale: dict[str, float]
    fitted_rows: int
    policy: str = "good_training_zscore"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FusionSearchResult:
    objective: FusionObjective
    objective_value: float
    weights: dict[str, float]
    candidates_evaluated: int
    validation_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fit_good_standardizer(
    training: pd.DataFrame,
    *,
    score_columns: tuple[str, ...],
    label_col: str = "is_anomaly",
) -> ScoreStandardizer:
    if not score_columns:
        raise ValueError("score_columns cannot be empty")
    if label_col not in training.columns:
        raise ValueError(f"Training frame is missing {label_col}")
    labels = pd.to_numeric(training[label_col], errors="raise").astype(int)
    if not labels.isin([0, 1]).all():
        raise ValueError(f"{label_col} must contain only 0/1 values")
    good = training.loc[labels == 0]
    if good.empty:
        raise ValueError("Good-training standardization requires at least one non-anomalous row")

    center: dict[str, float] = {}
    scale: dict[str, float] = {}
    for column in score_columns:
        if column not in good.columns:
            raise ValueError(f"Training frame is missing score column {column}")
        values = pd.to_numeric(good[column], errors="coerce").to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            raise ValueError(f"No finite Good-training values for {column}")
        center[column] = float(np.mean(finite))
        std = float(np.std(finite))
        scale[column] = std if std > 1e-12 else 1.0
    return ScoreStandardizer(
        score_columns=tuple(score_columns),
        center=center,
        scale=scale,
        fitted_rows=len(good),
    )


def standardize_scores(frame: pd.DataFrame, standardizer: ScoreStandardizer) -> pd.DataFrame:
    output = frame.copy()
    for column in standardizer.score_columns:
        if column not in output.columns:
            raise ValueError(f"Prediction frame is missing score column {column}")
        values = pd.to_numeric(output[column], errors="coerce")
        output[column] = (values - standardizer.center[column]) / standardizer.scale[column]
    return output


def _modality_name(score_column: str) -> str:
    return score_column[6:] if score_column.startswith("score_") else score_column


def _normalized_weights(score_columns: tuple[str, ...], weights: dict[str, float]) -> np.ndarray:
    raw: list[float] = []
    for column in score_columns:
        modality = _modality_name(column)
        value = weights.get(column, weights.get(modality, 0.0))
        if value < 0 or not np.isfinite(value):
            raise ValueError(f"Invalid fusion weight for {column}: {value}")
        raw.append(float(value))
    array = np.asarray(raw, dtype=float)
    total = float(array.sum())
    if total <= 0:
        raise ValueError("At least one fusion weight must be positive")
    return array / total


def fuse_scores(
    frame: pd.DataFrame,
    *,
    score_columns: tuple[str, ...],
    weights: dict[str, float],
    standardizer: ScoreStandardizer | None = None,
    reliability_aware: bool = False,
    output_col: str = "anomaly_score",
) -> pd.DataFrame:
    if not score_columns:
        raise ValueError("score_columns cannot be empty")
    normalized = normalize_prediction_frame(frame)
    if standardizer is not None:
        expected = set(standardizer.score_columns)
        if set(score_columns) != expected:
            raise ValueError("Fusion score_columns must match the supplied standardizer")
        normalized = standardize_scores(normalized, standardizer)
    for column in score_columns:
        if column not in normalized.columns:
            raise ValueError(f"Prediction frame is missing score column {column}")

    base_weights = _normalized_weights(score_columns, weights)
    score_matrix = np.column_stack(
        [
            pd.to_numeric(normalized[column], errors="coerce").to_numpy(dtype=float)
            for column in score_columns
        ]
    )
    available_matrix = np.isfinite(score_matrix)
    reliability_matrix = np.ones_like(score_matrix, dtype=float)

    for index, column in enumerate(score_columns):
        modality = _modality_name(column)
        availability_col = modality_available_column(modality)
        if availability_col in normalized.columns:
            available_matrix[:, index] &= normalized[availability_col].to_numpy(dtype=bool)
        if reliability_aware:
            reliability_col = modality_reliability_column(modality)
            if reliability_col in normalized.columns:
                reliability = pd.to_numeric(normalized[reliability_col], errors="coerce").to_numpy(
                    dtype=float
                )
                reliability_matrix[:, index] = np.clip(
                    np.nan_to_num(reliability, nan=0.0, posinf=1.0, neginf=0.0),
                    0.0,
                    1.0,
                )

    effective = available_matrix.astype(float) * base_weights[None, :] * reliability_matrix
    denominator = effective.sum(axis=1)
    safe_scores = np.nan_to_num(score_matrix, nan=0.0, posinf=0.0, neginf=0.0)
    numerator = (safe_scores * effective).sum(axis=1)
    fused = np.divide(
        numerator,
        denominator,
        out=np.full(len(normalized), np.nan, dtype=float),
        where=denominator > 0,
    )
    output = frame.copy()
    output[output_col] = fused
    output["fusion_available_modalities"] = available_matrix.sum(axis=1)
    output["fusion_effective_weight"] = denominator
    return output


def _simplex_weights(dimensions: int, step: float) -> list[np.ndarray]:
    if dimensions < 1:
        raise ValueError("dimensions must be positive")
    if not (0.0 < step <= 1.0):
        raise ValueError("step must be in (0, 1]")
    units = round(1.0 / step)
    if not np.isclose(units * step, 1.0, atol=1e-9):
        raise ValueError("step must divide 1.0 exactly within floating-point tolerance")

    candidates: list[np.ndarray] = []
    for cuts in itertools.combinations(range(units + dimensions - 1), dimensions - 1):
        separators = (-1, *cuts, units + dimensions - 1)
        counts = [separators[i + 1] - separators[i] - 1 for i in range(dimensions)]
        candidates.append(np.asarray(counts, dtype=float) / units)
    return candidates


def tune_convex_weights(
    validation: pd.DataFrame,
    *,
    score_columns: tuple[str, ...],
    label_col: str = "is_anomaly",
    standardizer: ScoreStandardizer | None = None,
    reliability_aware: bool = False,
    step: float = 0.1,
    objective: FusionObjective = "roc_auc",
) -> FusionSearchResult:
    from sklearn.metrics import average_precision_score, roc_auc_score

    if label_col not in validation.columns:
        raise ValueError(f"Validation frame is missing {label_col}")
    labels = pd.to_numeric(validation[label_col], errors="raise").astype(int).to_numpy()
    if len(np.unique(labels)) < 2:
        raise ValueError("Fusion validation requires both normal and anomalous labels")
    if len(score_columns) > 5:
        raise ValueError("Grid-search fusion is bounded to at most five modalities")

    best_value = -np.inf
    best_weights: dict[str, float] | None = None
    evaluated = 0
    for candidate in _simplex_weights(len(score_columns), step):
        weights = {
            column: float(value) for column, value in zip(score_columns, candidate, strict=True)
        }
        fused = fuse_scores(
            validation,
            score_columns=score_columns,
            weights=weights,
            standardizer=standardizer,
            reliability_aware=reliability_aware,
        )
        scores = fused["anomaly_score"].to_numpy(dtype=float)
        mask = np.isfinite(scores)
        if mask.sum() < 2 or len(np.unique(labels[mask])) < 2:
            continue
        if objective == "roc_auc":
            value = float(roc_auc_score(labels[mask], scores[mask]))
        elif objective == "pr_auc":
            value = float(average_precision_score(labels[mask], scores[mask]))
        else:  # pragma: no cover
            raise ValueError(f"Unsupported fusion objective: {objective}")
        evaluated += 1
        key = tuple(weights[column] for column in score_columns)
        best_key = (
            tuple(best_weights[column] for column in score_columns)
            if best_weights is not None
            else None
        )
        if value > best_value + 1e-12 or (
            np.isclose(value, best_value, atol=1e-12) and (best_key is None or key > best_key)
        ):
            best_value = value
            best_weights = weights

    if best_weights is None:
        raise ValueError("No valid fusion candidate could be evaluated")
    return FusionSearchResult(
        objective=objective,
        objective_value=float(best_value),
        weights=best_weights,
        candidates_evaluated=evaluated,
        validation_rows=len(validation),
    )


def fusion_ablation_report(
    frame: pd.DataFrame,
    *,
    score_columns: tuple[str, ...],
    weights: dict[str, float],
    label_col: str = "is_anomaly",
    standardizer: ScoreStandardizer | None = None,
    reliability_aware: bool = False,
) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    if label_col not in frame.columns:
        raise ValueError(f"Prediction frame is missing {label_col}")
    labels = pd.to_numeric(frame[label_col], errors="raise").astype(int).to_numpy()
    report: dict[str, Any] = {"unimodal": {}}
    for column in score_columns:
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(values)
        metrics: dict[str, Any]
        if mask.sum() == 0 or len(np.unique(labels[mask])) < 2:
            metrics = {"roc_auc": None, "pr_auc": None, "samples": int(mask.sum())}
        else:
            metrics = {
                "roc_auc": float(roc_auc_score(labels[mask], values[mask])),
                "pr_auc": float(average_precision_score(labels[mask], values[mask])),
                "samples": int(mask.sum()),
            }
        report["unimodal"][_modality_name(column)] = metrics

    fused = fuse_scores(
        frame,
        score_columns=score_columns,
        weights=weights,
        standardizer=standardizer,
        reliability_aware=reliability_aware,
    )
    values = fused["anomaly_score"].to_numpy(dtype=float)
    mask = np.isfinite(values)
    report["fusion"] = {
        "weights": dict(weights),
        "reliability_aware": reliability_aware,
        "standardizer": standardizer.to_dict() if standardizer else None,
        "samples": int(mask.sum()),
        "roc_auc": (
            float(roc_auc_score(labels[mask], values[mask]))
            if mask.sum() and len(np.unique(labels[mask])) >= 2
            else None
        ),
        "pr_auc": (
            float(average_precision_score(labels[mask], values[mask]))
            if mask.sum() and len(np.unique(labels[mask])) >= 2
            else None
        ),
    }
    return report
