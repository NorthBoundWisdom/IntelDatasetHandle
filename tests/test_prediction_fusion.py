from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weld_data_workbench.evaluation import evaluate_anomaly_predictions
from weld_data_workbench.fusion import (
    fit_good_standardizer,
    fuse_scores,
    fusion_ablation_report,
    tune_convex_weights,
)
from weld_data_workbench.prediction_contract import (
    InferenceTelemetry,
    attach_telemetry,
    availability_pattern,
    measure_inference,
    normalize_prediction_frame,
    prediction_metadata,
    write_prediction_artifact,
)


def _prediction_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample_id": [f"s{i}" for i in range(8)],
            "session_id": ["a", "a", "b", "b", "c", "c", "d", "d"],
            "category": ["Good", "Good", "Good", "Good", "Defect", "Defect", "Defect", "Defect"],
            "is_anomaly": [0, 0, 0, 0, 1, 1, 1, 1],
            "score_audio": [0.0, 0.1, 0.2, 0.15, 0.8, 0.9, 1.0, 1.1],
            "score_sensor": [0.2, 0.1, 0.15, 0.05, 0.7, 0.8, 0.9, 1.0],
            "available_audio": [True] * 8,
            "available_sensor": [True, True, True, True, True, True, False, False],
            "reliability_audio": [1.0] * 8,
            "reliability_sensor": [1.0, 0.8, 1.0, 0.9, 1.0, 0.7, 0.0, 0.0],
        }
    )


def test_prediction_contract_normalizes_availability_and_rejects_duplicates() -> None:
    frame = _prediction_frame()
    normalized = normalize_prediction_frame(
        frame, modalities=("audio", "sensor"), require_labels=True
    )
    assert normalized["available_audio"].dtype == bool
    assert availability_pattern(normalized.iloc[-1], ("audio", "sensor")) == (
        "available=audio;missing=sensor"
    )

    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate sample_id"):
        normalize_prediction_frame(duplicate)


def test_measure_and_attach_inference_telemetry() -> None:
    value, telemetry = measure_inference(lambda: sum(range(1000)), device="cpu", batch_size=4)
    assert value == 499500
    assert telemetry.latency_ms >= 0.0
    frame = attach_telemetry(_prediction_frame(), telemetry)
    assert np.isfinite(frame["inference_latency_ms"]).all()
    assert set(frame["device"]) == {"cpu"}
    assert set(frame["batch_size"]) == {4}


def test_prediction_artifact_writes_sidecar_metadata(tmp_path: Path) -> None:
    frame = _prediction_frame().copy()
    frame["anomaly_score"] = frame[["score_audio", "score_sensor"]].mean(axis=1)
    metadata = prediction_metadata(model_name="fixture", modalities=("audio", "sensor"))
    output = write_prediction_artifact(frame, tmp_path / "predictions.csv", metadata=metadata)
    assert output.exists()
    assert output.with_suffix(".csv.meta.json").exists()


def test_good_standardization_and_reliability_aware_fusion() -> None:
    frame = _prediction_frame()
    standardizer = fit_good_standardizer(
        frame,
        score_columns=("score_audio", "score_sensor"),
    )
    fused = fuse_scores(
        frame,
        score_columns=("score_audio", "score_sensor"),
        weights={"audio": 0.5, "sensor": 0.5},
        standardizer=standardizer,
        reliability_aware=True,
    )
    assert np.isfinite(fused["anomaly_score"]).all()
    assert fused.loc[7, "fusion_available_modalities"] == 1
    expected_audio = (
        frame.loc[7, "score_audio"] - standardizer.center["score_audio"]
    ) / standardizer.scale["score_audio"]
    assert fused.loc[7, "anomaly_score"] == pytest.approx(expected_audio)


def test_validation_only_convex_weight_search_and_ablation() -> None:
    frame = _prediction_frame()
    standardizer = fit_good_standardizer(
        frame.iloc[:4],
        score_columns=("score_audio", "score_sensor"),
    )
    result = tune_convex_weights(
        frame,
        score_columns=("score_audio", "score_sensor"),
        standardizer=standardizer,
        step=0.25,
    )
    assert result.objective_value == 1.0
    assert sum(result.weights.values()) == pytest.approx(1.0)
    report = fusion_ablation_report(
        frame,
        score_columns=("score_audio", "score_sensor"),
        weights=result.weights,
        standardizer=standardizer,
    )
    assert report["fusion"]["roc_auc"] == 1.0


def test_evaluator_reports_missing_modality_and_runtime_contract() -> None:
    frame = _prediction_frame()
    frame["anomaly_score"] = frame[["score_audio", "score_sensor"]].mean(axis=1)
    frame.loc[~frame["available_sensor"], "anomaly_score"] = frame.loc[
        ~frame["available_sensor"], "score_audio"
    ]
    frame = attach_telemetry(
        frame,
        InferenceTelemetry(
            latency_ms=2.5,
            process_cpu_ms=2.0,
            peak_rss_mb=128.0,
            device="cpu",
            batch_size=8,
        ),
    )
    result = evaluate_anomaly_predictions(frame, bootstrap_iterations=0)
    robustness = result["missing_modality_robustness"]
    assert robustness["available"] is True
    assert robustness["pattern_count"] >= 2
    telemetry = result["inference_telemetry"]
    assert telemetry["available"] is True
    assert telemetry["distributions"]["latency_ms"]["median"] == 2.5
