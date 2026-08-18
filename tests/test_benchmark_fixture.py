from __future__ import annotations

from pathlib import Path

from weld_data_workbench.benchmark_fixture import generate_benchmark_fixture
from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository


def test_large_benchmark_fixture_indexes_many_samples(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    summary = generate_benchmark_fixture(raw, sessions=3, samples_per_session=4)
    assert summary.samples == 12
    assert summary.sessions == 3
    assert summary.linked_files + summary.copied_files == 12 * 8

    config = init_workspace(raw, tmp_path / "workspace")
    built = IndexBuilder(config).build(workers=2)
    assert built.sample_count == 12
    assert built.asset_count == 12 * 8

    repo = DatasetRepository(config.index_path, config.dataset_root)
    assert repo.count_samples() == 12
    assert len(repo.splits()) == 3
