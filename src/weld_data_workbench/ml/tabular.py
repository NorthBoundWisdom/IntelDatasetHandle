from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(slots=True)
class BaselineResult:
    feature_path: Path
    model_path: Path
    scores_path: Path
    report_path: Path
    numeric_feature_count: int
    train_samples: int
    validation_auc: float | None
    test_auc: float | None
    category_auc_validation: dict[str, float]
    category_auc_test: dict[str, float]


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.casefold() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.casefold() in {".jsonl", ".ndjson"}:
        return pd.read_json(path, orient="records", lines=True)
    return pd.read_csv(path)


def _auc(y_true: np.ndarray, scores: np.ndarray) -> float | None:
    if len(np.unique(y_true)) < 2:
        return None
    return float(roc_auc_score(y_true, scores))


def _category_auc(frame: pd.DataFrame, split: str) -> dict[str, float]:
    subset = frame[frame["split"] == split]
    good = subset[subset["is_good"] == 1]
    result: dict[str, float] = {}
    for category in sorted(subset.loc[subset["is_good"] == 0, "category"].dropna().unique()):
        defect = subset[subset["category"] == category]
        combined = pd.concat([good, defect], ignore_index=True)
        value = _auc(
            (combined["is_good"].to_numpy() == 0).astype(int), combined["anomaly_score"].to_numpy()
        )
        if value is not None:
            result[str(category)] = value
    return result


def run_isolation_forest_baseline(
    feature_path: Path,
    output_dir: Path,
    *,
    random_state: int = 42,
    contamination: str | float = "auto",
) -> BaselineResult:
    feature_path = feature_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = _read_table(feature_path)

    required = {"sample_id", "split", "is_good", "category"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Feature table is missing required columns: {sorted(missing)}")

    excluded = {
        "is_good",
        "feature_error",
        "thickness_mm",
        "current_a",
        "voltage_v",
        "gas_bar",
        "robot_speed_cpm",
    }
    numeric_columns = [
        column
        for column in frame.select_dtypes(include=["number"]).columns
        if column not in excluded
    ]
    if not numeric_columns:
        raise ValueError("Feature table contains no usable numeric modality features")

    train_mask = (frame["split"] == "train") & (frame["is_good"] == 1)
    train = frame.loc[train_mask, numeric_columns]
    if len(train) < 2:
        raise ValueError("At least two Good training samples are required")

    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                IsolationForest(
                    n_estimators=300,
                    contamination=contamination,
                    random_state=random_state,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipeline.fit(train)

    # sklearn decision_function is larger for normal samples. Negate it so larger means anomalous.
    frame = frame.copy()
    frame["anomaly_score"] = -pipeline.decision_function(frame[numeric_columns])

    validation = frame[frame["split"] == "validation"]
    test = frame[frame["split"] == "test"]
    validation_auc = _auc(
        (validation["is_good"].to_numpy() == 0).astype(int),
        validation["anomaly_score"].to_numpy(),
    )
    test_auc = _auc(
        (test["is_good"].to_numpy() == 0).astype(int),
        test["anomaly_score"].to_numpy(),
    )

    model_path = output_dir / "isolation_forest.joblib"
    scores_path = output_dir / "isolation_forest_scores.csv"
    report_path = output_dir / "isolation_forest_report.json"
    joblib.dump({"pipeline": pipeline, "feature_columns": numeric_columns}, model_path)
    frame.to_csv(scores_path, index=False)

    result = BaselineResult(
        feature_path=feature_path,
        model_path=model_path,
        scores_path=scores_path,
        report_path=report_path,
        numeric_feature_count=len(numeric_columns),
        train_samples=len(train),
        validation_auc=validation_auc,
        test_auc=test_auc,
        category_auc_validation=_category_auc(frame, "validation"),
        category_auc_test=_category_auc(frame, "test"),
    )
    report_path.write_text(
        json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return result
