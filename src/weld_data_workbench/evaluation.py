from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class MetricBundle:
    roc_auc: float | None
    pr_auc: float | None
    eer: float | None
    fnr_at_fpr: dict[str, float | None]
    samples: int
    positive_samples: int
    negative_samples: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "roc_auc": self.roc_auc,
            "pr_auc": self.pr_auc,
            "eer": self.eer,
            "fnr_at_fpr": self.fnr_at_fpr,
            "samples": self.samples,
            "positive_samples": self.positive_samples,
            "negative_samples": self.negative_samples,
        }


def _metric_bundle(
    labels: np.ndarray,
    scores: np.ndarray,
    *,
    fpr_targets: tuple[float, ...],
) -> MetricBundle:
    from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve

    mask = np.isfinite(scores)
    labels = labels[mask].astype(int)
    scores = scores[mask].astype(float)
    positives = int(labels.sum())
    negatives = int(len(labels) - positives)
    if len(labels) == 0 or positives == 0 or negatives == 0:
        return MetricBundle(
            roc_auc=None,
            pr_auc=None,
            eer=None,
            fnr_at_fpr={f"{target:g}": None for target in fpr_targets},
            samples=len(labels),
            positive_samples=positives,
            negative_samples=negatives,
        )

    roc_auc = float(roc_auc_score(labels, scores))
    pr_auc = float(average_precision_score(labels, scores))
    fpr, tpr, _thresholds = roc_curve(labels, scores)
    fnr = 1.0 - tpr
    eer_index = int(np.nanargmin(np.abs(fpr - fnr)))
    eer = float((fpr[eer_index] + fnr[eer_index]) / 2.0)

    at_fpr: dict[str, float | None] = {}
    for target in fpr_targets:
        eligible = np.flatnonzero(fpr <= target)
        if len(eligible) == 0:
            at_fpr[f"{target:g}"] = None
        else:
            best = int(eligible[np.argmax(tpr[eligible])])
            at_fpr[f"{target:g}"] = float(1.0 - tpr[best])

    return MetricBundle(
        roc_auc=roc_auc,
        pr_auc=pr_auc,
        eer=eer,
        fnr_at_fpr=at_fpr,
        samples=len(labels),
        positive_samples=positives,
        negative_samples=negatives,
    )


def _bootstrap_group_auc(
    frame: pd.DataFrame,
    *,
    score_col: str,
    label_col: str,
    group_col: str,
    iterations: int,
    seed: int,
) -> dict[str, float | int | None]:
    from sklearn.metrics import roc_auc_score

    if iterations <= 0 or group_col not in frame.columns:
        return {"iterations": 0, "low": None, "median": None, "high": None}
    groups = frame[group_col].dropna().astype(str).unique()
    if len(groups) < 2:
        return {"iterations": 0, "low": None, "median": None, "high": None}

    rng = np.random.default_rng(seed)
    values: list[float] = []
    grouped = {group: frame[frame[group_col].astype(str) == group] for group in groups}
    for _ in range(iterations):
        sampled = rng.choice(groups, size=len(groups), replace=True)
        sample = pd.concat([grouped[str(group)] for group in sampled], ignore_index=True)
        labels = sample[label_col].to_numpy(dtype=int)
        scores = pd.to_numeric(sample[score_col], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(scores)
        labels = labels[mask]
        scores = scores[mask]
        if len(labels) == 0 or len(np.unique(labels)) < 2:
            continue
        values.append(float(roc_auc_score(labels, scores)))

    if not values:
        return {"iterations": 0, "low": None, "median": None, "high": None}
    array = np.asarray(values, dtype=float)
    return {
        "iterations": len(values),
        "low": float(np.quantile(array, 0.025)),
        "median": float(np.quantile(array, 0.5)),
        "high": float(np.quantile(array, 0.975)),
    }


def evaluate_anomaly_predictions(
    frame: pd.DataFrame,
    *,
    score_col: str = "anomaly_score",
    label_col: str = "is_anomaly",
    category_col: str = "category",
    group_col: str = "session_id",
    fpr_targets: tuple[float, ...] = (0.001, 0.01, 0.05),
    bootstrap_iterations: int = 500,
    bootstrap_seed: int = 0,
) -> dict[str, Any]:
    """Evaluate anomaly scores where larger values mean more anomalous/defective."""

    required = {score_col, label_col}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing prediction columns: {sorted(missing)}")

    clean = frame.copy()
    clean[label_col] = pd.to_numeric(clean[label_col], errors="raise").astype(int)
    if not clean[label_col].isin([0, 1]).all():
        raise ValueError(f"{label_col} must contain only 0/1 values")
    clean[score_col] = pd.to_numeric(clean[score_col], errors="coerce")

    overall = _metric_bundle(
        clean[label_col].to_numpy(dtype=int),
        clean[score_col].to_numpy(dtype=float),
        fpr_targets=fpr_targets,
    )

    by_category: dict[str, Any] = {}
    if category_col in clean.columns:
        for category, subset in clean.groupby(category_col, dropna=False):
            key = "Unknown" if pd.isna(category) else str(category)
            by_category[key] = _metric_bundle(
                subset[label_col].to_numpy(dtype=int),
                subset[score_col].to_numpy(dtype=float),
                fpr_targets=fpr_targets,
            ).to_dict()

    bootstrap = _bootstrap_group_auc(
        clean,
        score_col=score_col,
        label_col=label_col,
        group_col=group_col,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed,
    )

    return {
        "metric_schema_version": 1,
        "score_semantics": "higher_is_more_anomalous",
        "overall": overall.to_dict(),
        "by_category": by_category,
        "session_grouped_roc_auc_95ci": bootstrap,
        "fpr_targets": list(fpr_targets),
    }
