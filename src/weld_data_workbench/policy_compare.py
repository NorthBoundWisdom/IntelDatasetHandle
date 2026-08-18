from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import AppConfig
from .evaluation import evaluate_anomaly_predictions
from .index.database import connect_database

POLICY_COMPARISON_SCHEMA_VERSION = 1


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _split_artifact_hash(body: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def load_verified_holdout_artifact(path: Path) -> dict[str, Any]:
    raw = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Split artifact root must be an object")
    declared = raw.get("split_artifact_id")
    if not isinstance(declared, str) or not declared:
        raise ValueError("Split artifact does not contain split_artifact_id")
    body = {key: value for key, value in raw.items() if key != "split_artifact_id"}
    if _split_artifact_hash(body) != declared:
        raise ValueError("Split artifact payload does not match split_artifact_id")
    if raw.get("mode") != "holdout":
        raise ValueError("Policy comparison currently requires a holdout split artifact")
    assignments = raw.get("sample_assignments")
    if not isinstance(assignments, dict):
        raise ValueError("Split artifact sample_assignments must be an object")
    valid = {"train", "validation", "test"}
    unexpected = {str(value) for value in assignments.values()} - valid
    if unexpected:
        raise ValueError(f"Unsupported holdout assignments: {sorted(unexpected)}")
    return raw


def load_predictions(path: Path) -> pd.DataFrame:
    source = path.expanduser().resolve()
    suffix = source.suffix.casefold()
    if suffix == ".parquet":
        return pd.read_parquet(source)
    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(source, lines=True)
    return pd.read_csv(source)


def _repository_metadata(config: AppConfig) -> pd.DataFrame:
    with connect_database(config.index_path, read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT
                sample_id,session_id,split,category,is_good,weld_type,
                steel_type,thickness_mm,current_a,voltage_v,gas_bar,robot_speed_cpm
            FROM samples
            ORDER BY sample_id
            """
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows]).rename(columns={"split": "upstream_split"})


def _session_overlap(frame: pd.DataFrame, split_col: str) -> dict[str, Any]:
    session_sets: dict[str, set[str]] = {}
    for split in ("train", "validation", "test"):
        subset = frame[frame[split_col] == split]
        session_sets[split] = set(subset["session_id"].dropna().astype(str))

    pairwise: dict[str, Any] = {}
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        shared = sorted(session_sets[left] & session_sets[right])
        pairwise[f"{left}_{right}"] = {
            "count": len(shared),
            "sessions": shared[:100],
            "truncated": len(shared) > 100,
        }
    all_shared = set().union(
        session_sets["train"] & session_sets["validation"],
        session_sets["train"] & session_sets["test"],
        session_sets["validation"] & session_sets["test"],
    )
    return {
        "sessions_by_partition": {key: len(value) for key, value in session_sets.items()},
        "pairwise": pairwise,
        "sessions_crossing_any_partition": len(all_shared),
    }


def _sample_summary(frame: pd.DataFrame) -> dict[str, Any]:
    labels = frame["is_anomaly"].astype(int)
    return {
        "samples": len(frame),
        "anomaly_samples": int(labels.sum()),
        "good_samples": int(len(labels) - labels.sum()),
        "sessions": int(frame["session_id"].nunique(dropna=True)),
    }


def _evaluate_policy(
    frame: pd.DataFrame,
    *,
    split_col: str,
    score_col: str,
    threshold: float | None,
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    counts: dict[str, Any] = {}
    for split in ("validation", "test"):
        subset = frame[frame[split_col] == split].copy()
        counts[split] = _sample_summary(subset)
        metrics[split] = evaluate_anomaly_predictions(
            subset,
            score_col=score_col,
            label_col="is_anomaly",
            threshold=threshold,
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        )

    evaluation = frame[frame[split_col].isin(["validation", "test"])].copy()
    counts["evaluation_combined"] = _sample_summary(evaluation)
    metrics["evaluation_combined"] = evaluate_anomaly_predictions(
        evaluation,
        score_col=score_col,
        label_col="is_anomaly",
        threshold=threshold,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    counts["train"] = _sample_summary(frame[frame[split_col] == "train"])

    return {
        "split_column": split_col,
        "counts": counts,
        "session_overlap": _session_overlap(frame, split_col),
        "metrics": metrics,
    }


def _metric_delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    if not np.isfinite(float(left)) or not np.isfinite(float(right)):
        return None
    return float(right) - float(left)


def compare_split_policies(
    config: AppConfig,
    predictions: pd.DataFrame,
    split_artifact: dict[str, Any],
    *,
    score_col: str = "anomaly_score",
    label_col: str | None = None,
    upstream_threshold: float | None = None,
    experimental_threshold: float | None = None,
    bootstrap_iterations: int = 500,
    bootstrap_seed: int = 0,
) -> dict[str, Any]:
    """Evaluate one immutable prediction set under two partition policies.

    This function never refits a model and never derives a threshold from test
    predictions. The same score attached to each sample is merely sliced according
    to the upstream split and a verified session-disjoint holdout artifact.
    """

    if "sample_id" not in predictions.columns:
        raise ValueError("Predictions must contain sample_id")
    if score_col not in predictions.columns:
        raise ValueError(f"Predictions must contain {score_col}")
    if predictions["sample_id"].duplicated().any():
        raise ValueError("Predictions contain duplicate sample_id rows")

    metadata = _repository_metadata(config)
    selected_columns = ["sample_id", score_col]
    if label_col is not None:
        if label_col not in predictions.columns:
            raise ValueError(f"Predictions must contain requested label column {label_col}")
        selected_columns.append(label_col)
    frame = predictions[selected_columns].copy()
    frame["sample_id"] = frame["sample_id"].astype(str)
    frame[score_col] = pd.to_numeric(frame[score_col], errors="coerce")
    frame = frame.merge(metadata, on="sample_id", how="left", validate="one_to_one")
    if frame["session_id"].isna().any():
        missing = frame.loc[frame["session_id"].isna(), "sample_id"].astype(str).tolist()[:20]
        raise ValueError(f"Predictions reference unknown sample IDs: {missing}")

    if label_col is None:
        if frame["is_good"].isna().any():
            raise ValueError("Cannot derive anomaly labels because some indexed samples lack is_good")
        frame["is_anomaly"] = 1 - frame["is_good"].astype(int)
        label_source = "index:is_good"
    else:
        labels = pd.to_numeric(frame[label_col], errors="raise").astype(int)
        if not labels.isin([0, 1]).all():
            raise ValueError(f"{label_col} must contain only 0/1 values")
        frame["is_anomaly"] = labels
        label_source = f"predictions:{label_col}"

    assignments = {str(key): str(value) for key, value in split_artifact["sample_assignments"].items()}
    frame["experimental_split"] = frame["sample_id"].map(assignments)
    if frame["experimental_split"].isna().any():
        missing = frame.loc[frame["experimental_split"].isna(), "sample_id"].astype(str).tolist()[:20]
        raise ValueError(f"Split artifact has no assignment for prediction samples: {missing}")

    upstream = _evaluate_policy(
        frame,
        split_col="upstream_split",
        score_col=score_col,
        threshold=upstream_threshold,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    experimental = _evaluate_policy(
        frame,
        split_col="experimental_split",
        score_col=score_col,
        threshold=experimental_threshold,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )

    upstream_overall = upstream["metrics"]["evaluation_combined"]["overall"]
    experimental_overall = experimental["metrics"]["evaluation_combined"]["overall"]
    return {
        "schema_version": POLICY_COMPARISON_SCHEMA_VERSION,
        "split_artifact_id": split_artifact["split_artifact_id"],
        "prediction_samples": len(frame),
        "score_column": score_col,
        "score_semantics": "higher_is_more_anomalous",
        "label_source": label_source,
        "threshold_policy": {
            "upstream": upstream_threshold,
            "session_disjoint": experimental_threshold,
            "note": "Thresholds, when supplied, must be calibrated outside the evaluated frame.",
        },
        "policies": {
            "upstream": upstream,
            "session_disjoint": experimental,
        },
        "evaluation_combined_delta_session_disjoint_minus_upstream": {
            "roc_auc": _metric_delta(
                upstream_overall.get("roc_auc"), experimental_overall.get("roc_auc")
            ),
            "pr_auc": _metric_delta(
                upstream_overall.get("pr_auc"), experimental_overall.get("pr_auc")
            ),
            "eer": _metric_delta(upstream_overall.get("eer"), experimental_overall.get("eer")),
        },
    }


def write_policy_comparison(report: dict[str, Any], output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
