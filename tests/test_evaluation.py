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

    assert result["metric_schema_version"] == 2
    assert result["overall"]["roc_auc"] == 1.0
    assert result["overall"]["pr_auc"] == 1.0
    assert result["overall"]["eer"] == 0.0
    assert result["session_grouped_roc_auc_95ci"]["iterations"] > 0
    assert result["threshold_stability"]["threshold"] is None


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


def test_fixed_threshold_stability_reports_process_group_drift() -> None:
    frame = pd.DataFrame(
        {
            "session_id": ["a", "a", "a", "a", "b", "b", "b", "b"],
            "weld_type": ["FILLET"] * 4 + ["BUTT"] * 4,
            "steel_type": ["FE410"] * 8,
            "thickness_mm": [3.0] * 4 + [7.0] * 4,
            "category": ["Good", "Good", "Defect", "Defect"] * 2,
            "is_anomaly": [0, 0, 1, 1] * 2,
            # At threshold 0.5, group a is perfect while group b has one false
            # positive and one false negative.
            "anomaly_score": [0.1, 0.2, 0.8, 0.9, 0.2, 0.7, 0.4, 0.9],
        }
    )
    result = evaluate_anomaly_predictions(
        frame,
        bootstrap_iterations=0,
        threshold=0.5,
    )

    stability = result["threshold_stability"]
    assert stability["policy"] == "externally_calibrated_fixed_threshold"
    assert stability["threshold"] == 0.5
    assert stability["overall"]["fpr"] == 0.25
    assert stability["overall"]["fnr"] == 0.25

    by_weld = stability["by_dimension"]["weld_type"]
    assert by_weld["groups"]["FILLET"]["fpr"] == 0.0
    assert by_weld["groups"]["FILLET"]["fnr"] == 0.0
    assert by_weld["groups"]["BUTT"]["fpr"] == 0.5
    assert by_weld["groups"]["BUTT"]["fnr"] == 0.5
    assert by_weld["fpr_range"] == 0.5
    assert by_weld["fnr_range"] == 0.5
