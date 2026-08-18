from __future__ import annotations

from pathlib import Path

import pytest

from weld_data_workbench.config import AppConfig
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository


def test_failed_rebuild_preserves_previous_index(
    indexed_workspace: tuple[AppConfig, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _summary = indexed_workspace
    before = DatasetRepository(config.index_path, config.dataset_root).stats()
    original_bytes = config.index_path.read_bytes()

    def fail_insert(*_args, **_kwargs):
        raise OSError("injected sqlite write failure")

    monkeypatch.setattr("weld_data_workbench.index.builder.insert_probe", fail_insert)

    with pytest.raises(OSError, match="injected sqlite write failure"):
        IndexBuilder(config).build(workers=1)

    assert config.index_path.exists()
    assert config.index_path.read_bytes() == original_bytes
    assert not Path(str(config.index_path) + ".building").exists()

    after = DatasetRepository(config.index_path, config.dataset_root).stats()
    assert after["total_samples"] == before["total_samples"]
    assert after["total_assets"] == before["total_assets"]


def test_stale_building_database_is_removed_before_rebuild(
    indexed_workspace: tuple[AppConfig, object],
) -> None:
    config, _summary = indexed_workspace
    temporary = config.index_path.with_name(config.index_path.name + ".building")
    temporary.write_bytes(b"not a sqlite database")

    summary = IndexBuilder(config).build(workers=1)

    assert summary.sample_count > 0
    assert config.index_path.exists()
    assert not temporary.exists()


def test_keyboard_interrupt_preserves_previous_index_and_cleans_partial_build(
    indexed_workspace: tuple[AppConfig, object],
) -> None:
    config, _summary = indexed_workspace
    before = DatasetRepository(config.index_path, config.dataset_root).stats()
    original_bytes = config.index_path.read_bytes()
    temporary = config.index_path.with_name(config.index_path.name + ".building")

    def interrupt_after_first_sample(completed: int, _total: int, _relpath: str) -> None:
        if completed >= 1:
            raise KeyboardInterrupt("injected user interruption")

    with pytest.raises(KeyboardInterrupt, match="injected user interruption"):
        IndexBuilder(config).build(workers=1, progress=interrupt_after_first_sample)

    assert config.index_path.read_bytes() == original_bytes
    assert not temporary.exists()
    assert not Path(str(temporary) + "-wal").exists()
    assert not Path(str(temporary) + "-shm").exists()
    after = DatasetRepository(config.index_path, config.dataset_root).stats()
    assert after["total_samples"] == before["total_samples"]
    assert after["total_assets"] == before["total_assets"]


def test_previous_index_remains_queryable_while_replacement_is_built(
    indexed_workspace: tuple[AppConfig, object],
) -> None:
    config, _summary = indexed_workspace
    reader = DatasetRepository(config.index_path, config.dataset_root)
    expected = reader.count_samples()
    observations: list[int] = []

    def query_old_index(_completed: int, _total: int, _relpath: str) -> None:
        # Each repository read opens the active `index.sqlite3`, which must still
        # be the previous complete database until the atomic replacement step.
        observations.append(reader.count_samples())

    summary = IndexBuilder(config).build(workers=2, progress=query_old_index)

    assert summary.sample_count == expected
    assert observations
    assert all(value == expected for value in observations)
