from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


@dataclass(slots=True)
class FusionResult:
    audio_weight: float
    video_weight: float
    validation_auc: float
    test_auc: float | None
    train_audio_mean: float
    train_audio_std: float
    train_video_mean: float
    train_video_std: float


def _standardize(values: pd.Series, mean: float, std: float) -> np.ndarray:
    denominator = std if std > 1e-12 else 1.0
    return (values.to_numpy(dtype=float) - mean) / denominator


def late_fusion_grid_search(
    frame: pd.DataFrame,
    *,
    audio_score_column: str = "audio_score",
    video_score_column: str = "video_score",
    steps: int = 101,
) -> tuple[FusionResult, pd.DataFrame]:
    required = {"split", "is_good", audio_score_column, video_score_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns for fusion: {sorted(missing)}")

    train = frame[(frame["split"] == "train") & (frame["is_good"] == 1)]
    validation = frame[frame["split"] == "validation"]
    if train.empty or validation.empty:
        raise ValueError("Fusion requires Good training samples and a non-empty validation split")

    audio_mean = float(train[audio_score_column].mean())
    audio_std = float(train[audio_score_column].std(ddof=0))
    video_mean = float(train[video_score_column].mean())
    video_std = float(train[video_score_column].std(ddof=0))

    output = frame.copy()
    output["audio_score_z"] = _standardize(output[audio_score_column], audio_mean, audio_std)
    output["video_score_z"] = _standardize(output[video_score_column], video_mean, video_std)

    y_validation = (validation["is_good"].to_numpy() == 0).astype(int)
    best_weight = 0.0
    best_auc = -np.inf
    for audio_weight in np.linspace(0.0, 1.0, num=max(steps, 2)):
        video_weight = 1.0 - audio_weight
        scores = (
            audio_weight * output.loc[validation.index, "audio_score_z"].to_numpy()
            + video_weight * output.loc[validation.index, "video_score_z"].to_numpy()
        )
        auc = float(roc_auc_score(y_validation, scores))
        if auc > best_auc:
            best_auc = auc
            best_weight = float(audio_weight)

    output["fusion_score"] = (
        best_weight * output["audio_score_z"] + (1.0 - best_weight) * output["video_score_z"]
    )
    test = output[output["split"] == "test"]
    test_auc = None
    if not test.empty and test["is_good"].nunique() >= 2:
        test_auc = float(
            roc_auc_score((test["is_good"].to_numpy() == 0).astype(int), test["fusion_score"])
        )

    result = FusionResult(
        audio_weight=best_weight,
        video_weight=1.0 - best_weight,
        validation_auc=float(best_auc),
        test_auc=test_auc,
        train_audio_mean=audio_mean,
        train_audio_std=audio_std,
        train_video_mean=video_mean,
        train_video_std=video_std,
    )
    return result, output
