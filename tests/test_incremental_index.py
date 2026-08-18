from __future__ import annotations

from pathlib import Path

import pytest

import weld_data_workbench.index.builder as builder_module
from weld_data_workbench.config import init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.index.repository import DatasetRepository
from weld_data_workbench.synthetic import generate_synthetic_dataset


def test_incremental_index_reuses_unchanged_samples_and_reprobes_one_touch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_synthetic_dataset(raw, profile="tiny")
    config = init_workspace(raw, workspace)

    first = IndexBuilder(config).build(workers=2)
    assert first.sample_count == 14
    assert first.reused_sample_count == 0
    assert first.probed_sample_count == 14

    original_probe = builder_module.probe_sample
    called: list[str] = []

    def counting_probe(candidate, app_config, **kwargs):
        called.append(candidate.relpath)
        return original_probe(candidate, app_config, **kwargs)

    monkeypatch.setattr(builder_module, "probe_sample", counting_probe)

    second = IndexBuilder(config).build(workers=2)
    assert second.sample_count == 14
    assert second.reused_sample_count == 14
    assert second.probed_sample_count == 0
    assert called == []

    repo = DatasetRepository(config.index_path, config.dataset_root)
    sample = repo.get_sample("good-train-000")
    assert sample is not None
    audio = next(asset for asset in sample["assets"] if asset["kind"] == "audio")
    Path(audio["absolute_path"]).touch()

    third = IndexBuilder(config).build(workers=2)
    assert third.sample_count == 14
    assert third.reused_sample_count == 13
    assert third.probed_sample_count == 1
    assert third.failed_probe_count == 0
    assert called == [str(sample["relpath"])]


def test_incremental_index_reprobes_when_probe_contract_gets_stricter(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    workspace = tmp_path / "workspace"
    generate_synthetic_dataset(raw, profile="tiny")
    config = init_workspace(raw, workspace)
    IndexBuilder(config).build(workers=2)

    config.scan.probe_mode = "full"
    summary = IndexBuilder(config).build(workers=2)
    assert summary.reused_sample_count == 0
    assert summary.probed_sample_count == 14
