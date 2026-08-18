from __future__ import annotations

import pandas as pd

from weld_data_workbench.evaluation import evaluate_anomaly_predictions


def test_anomaly_evaluation_perfect_separation() -> None:
    frame = pd.DataFrame(
        {
            "session_id": ["a", "a", "b", "b", "c", "c"],
            "category": ["Good", "Defect", "Good", "Defect", "Good", "Defect"],
            "is_anomaly": [0, 1, 0, 1, 0, 1],
            "anomaly_score": [0.1, 0.9, 0.2, 0.8, 0.3, 0.7],
        }
    )
    result = evaluate_anomaly_predictions(frame, bootstrap_iterations=20, bootstrap_seed=4)

    assert result["overall"]["roc_auc"] == 1.0
    assert result["overall"]["pr_auc"] == 1.0
    assert result["overall"]["eer"] == 0.0
    assert result["session_grouped_roc_auc_95ci"]["iterations"] > 0


def test_anomaly_evaluation_handles_single_class_category() -> None:
    frame = pd.DataFrame(
        {
            "session_id": ["a", "a", "b", "b"],
            "category": ["Good", "Good", "Porosity", "Porosity"],
            "is_anomaly": [0, 0, 1, 1],
            "anomaly_score": [0.1, 0.2, 0.8, 0.9],
        }
    )
    result = evaluate_anomaly_predictions(frame, bootstrap_iterations=0)

    assert result["overall"]["roc_auc"] == 1.0
    assert result["by_category"]["Good"]["roc_auc"] is None
    assert result["by_category"]["Porosity"]["roc_auc"] is None
