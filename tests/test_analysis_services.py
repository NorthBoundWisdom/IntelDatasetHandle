from __future__ import annotations

import pytest

from weld_data_workbench.analysis_services import AnalysisService
from weld_data_workbench.index.repository import DatasetRepository


def test_good_matching_is_deterministic_and_returns_good_samples(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    repository = DatasetRepository(config.index_path, config.dataset_root)
    service = AnalysisService(repository)

    defect = next(record for record in repository.iter_samples() if not bool(record["is_good"]))
    first = service.good_matches(defect["sample_id"], limit=4)
    second = service.good_matches(defect["sample_id"], limit=4)

    assert first == second
    assert first
    assert [item["distance"] for item in first] == sorted(item["distance"] for item in first)
    assert all(repository.get_sample(item["sample_id"])["is_good"] == 1 for item in first)

    same_split = service.good_matches(defect["sample_id"], limit=20, same_split=True)
    assert all(item["split"] == defect["split"] for item in same_split)


def test_distribution_and_pivot_cover_index(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    repository = DatasetRepository(config.index_path, config.dataset_root)
    service = AnalysisService(repository)
    total = repository.count_samples()

    category = service.distribution("category")
    assert category["kind"] == "categorical"
    assert sum(item["count"] for item in category["items"]) == total

    thickness = service.distribution("thickness_mm", bins=4)
    assert thickness["kind"] == "numeric"
    assert sum(item["count"] for item in thickness["bins"]) + thickness["null_count"] == total

    pivot = service.pivot(row="category", column="split", measure="count")
    assert sum(int(item["value"]) for item in pivot["records"]) == total

    means = service.pivot(row="split", measure="mean", value="current_a")
    assert means["measure"] == "mean"
    assert means["records"]


def test_analysis_service_validation_and_unknown_sample(indexed_workspace) -> None:
    config, _summary = indexed_workspace
    repository = DatasetRepository(config.index_path, config.dataset_root)
    service = AnalysisService(repository)

    with pytest.raises(KeyError):
        service.good_matches("missing-sample")
    with pytest.raises(ValueError):
        service.distribution("not-a-field")
    with pytest.raises(ValueError):
        service.pivot(row="not-a-field")
    with pytest.raises(ValueError):
        service.pivot(row="category", measure="mean", value="category")
