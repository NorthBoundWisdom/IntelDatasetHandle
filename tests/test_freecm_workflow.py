from __future__ import annotations

import json
from pathlib import Path

from configs.workbench_workflow import (
    discover_dataset_root,
    find_dataset_archive,
    find_qml_runtime,
    qt_multimedia_module,
)


def test_dataset_discovery_uses_manifest_shape_not_filename(tmp_path: Path) -> None:
    extraction_root = tmp_path / "extracted"
    dataset_root = extraction_root / "wrapper" / "dataset"
    dataset_root.mkdir(parents=True)
    (dataset_root / "labels.csv").write_text(
        "CATEGORY,DIRECTORY,SUBDIRS,SPLIT\nGood,session-a,session-a/sample-001,TRAIN\n",
        encoding="utf-8",
    )
    sensor_dir = extraction_root / "wrapper" / "dataset" / "session-a" / "sample-001"
    sensor_dir.mkdir(parents=True)
    (sensor_dir / "sample-001.csv").write_text(
        "Date,Time,Pressure\n2026-08-18,12:00:00,1.0\n",
        encoding="utf-8",
    )

    assert discover_dataset_root(extraction_root) == dataset_root


def test_archive_discovery_requires_an_unambiguous_candidate(tmp_path: Path) -> None:
    archive = tmp_path / "dataset.tar.gz"
    archive.touch()
    assert find_dataset_archive(tmp_path) == archive

    (tmp_path / "other.tgz").touch()
    assert find_dataset_archive(tmp_path) is None


def test_qml_runtime_accepts_an_explicit_native_qt_binary(tmp_path: Path) -> None:
    runtime = tmp_path / "Qt" / "6.11.1" / "macos" / "bin" / "qml"
    runtime.parent.mkdir(parents=True)
    runtime.touch(mode=0o755)

    assert find_qml_runtime(runtime) == runtime.resolve()


def test_qt_multimedia_module_follows_the_runtime_version(tmp_path: Path) -> None:
    qt_root = tmp_path / "Qt" / "6.11.2" / "macos"
    runtime = qt_root / "bin" / "qml"
    runtime.parent.mkdir(parents=True)
    runtime.touch(mode=0o755)
    multimedia = qt_root / "qml" / "QtMultimedia"
    multimedia.mkdir(parents=True)

    assert qt_multimedia_module(runtime) == multimedia.resolve()


def test_freecm_manifest_exposes_config_build_run_and_test() -> None:
    manifest = json.loads(Path("configs/freecm.commands.jsonc").read_text(encoding="utf-8"))

    assert manifest["version"] == 2
    commands = manifest["commands"]
    configuration = commands["config"][0]
    assert configuration["id"] == "local-qml-workbench"
    assert configuration["default"] is True
    assert configuration["defaults"] == {
        "build": "python-wheel",
        "run": "qml-workbench",
        "test": "precommit",
    }
    assert configuration["readiness"]["outputs"] == ["build/freecm/configured.json"]
    assert configuration["args"] == ["configs/source_root_workflow.py", "--update"]

    for action in ("build", "run", "test"):
        assert commands[action]
        assert commands[action][0]["configurations"] == ["local-qml-workbench"]

    assert "PySide" not in Path("pyproject.toml").read_text(encoding="utf-8")


def test_source_roots_locks_store_the_same_user_configuration() -> None:
    template = json.loads(Path("source_roots.lock.jsonc.in").read_text(encoding="utf-8"))

    assert template["schemaVersion"] == 5
    assert template["AppConfigs"]["WELD_QML_RUNTIME"].endswith("/macos/bin/qml")
    assert template["AppConfigs"]["WELD_WORKSPACE"].endswith("/IntelWelding/workspace")
    assert template["depsMode"] == "pinned"
    assert template["depsManualPath"] == {}
    assert template["dependencies"] == {}

    active_path = Path("source_roots.lock.jsonc")
    if active_path.exists():
        active = json.loads(active_path.read_text(encoding="utf-8"))
        assert template["AppConfigs"] == active["AppConfigs"]
        assert template["terminalPath"] == active["terminalPath"]

    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "source_roots.lock.jsonc" in ignore
    assert ".source_roots.lock.jsonc.lock" in ignore
    assert ".freecm.workspace.lock" in ignore


def test_environment_installation_is_owned_by_init_not_update() -> None:
    source_root_workflow = Path("configs/source_root_workflow.py").read_text(encoding="utf-8")
    workbench_workflow = Path("configs/workbench_workflow.py").read_text(encoding="utf-8")

    assert "def _cmd_init" in source_root_workflow
    assert "initialize_environment()" in source_root_workflow
    assert "def _require_environment" in workbench_workflow
    assert "python3 configs/source_root_workflow.py --init" in workbench_workflow
