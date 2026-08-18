from __future__ import annotations

from weld_data_workbench.features.pipeline import FeatureExtractor
from weld_data_workbench.ml.tabular import run_isolation_forest_baseline


def test_feature_extraction_and_baseline(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    feature_path = config.features_dir / "test_features.csv"
    summary = FeatureExtractor(config).extract(feature_path, workers=2)
    assert summary.samples_completed == 14
    assert summary.samples_failed == 0
    assert summary.feature_columns > 30

    result = run_isolation_forest_baseline(feature_path, config.models_dir / "test_baseline")
    assert result.train_samples == 4
    assert result.numeric_feature_count > 10
    assert result.validation_auc is not None
    assert result.test_auc is not None
    assert result.model_path.exists()
    assert result.scores_path.exists()
    assert result.report_path.exists()
