from __future__ import annotations

from pathlib import Path

import pytest

from weld_data_workbench.config import AppConfig, init_workspace
from weld_data_workbench.index.builder import IndexBuilder
from weld_data_workbench.synthetic import generate_synthetic_dataset


@pytest.fixture(scope="session")
def synthetic_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("synthetic") / "raw"
    generate_synthetic_dataset(root, profile="tiny")
    return root


@pytest.fixture(scope="session")
def indexed_workspace(
    tmp_path_factory: pytest.TempPathFactory,
    synthetic_root: Path,
) -> tuple[AppConfig, object]:
    workspace = tmp_path_factory.mktemp("workspace")
    config = init_workspace(synthetic_root, workspace)
    summary = IndexBuilder(config).build(workers=2)
    return config, summary
