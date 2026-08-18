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
