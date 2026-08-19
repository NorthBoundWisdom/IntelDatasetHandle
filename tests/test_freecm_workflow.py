from __future__ import annotations

import json
import plistlib
from pathlib import Path

import pytest

import configs.workbench_workflow as workbench_workflow
from configs.workbench_workflow import (
    ExistingWorkspace,
    configure,
    discover_dataset_root,
    find_dataset_archive,
    find_qml_runtime,
    prepare_native_app_bundle,
    qt_multimedia_module,
    refresh_index,
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


def test_native_launcher_is_packaged_as_a_macos_app_bundle(tmp_path: Path) -> None:
    icon = tmp_path / "Demo.icns"
    icon.write_bytes(b"test-icon")
    app_bundle = tmp_path / "Demo.app"

    launcher = prepare_native_app_bundle(app_bundle, icon)

    assert launcher == app_bundle / "Contents" / "MacOS" / "Demo"
    assert (app_bundle / "Contents" / "Resources" / "Demo.icns").read_bytes() == b"test-icon"
    with (app_bundle / "Contents" / "Info.plist").open("rb") as handle:
        metadata = plistlib.load(handle)
    assert metadata["CFBundleExecutable"] == "Demo"
    assert metadata["CFBundleIconFile"] == "Demo.icns"
    assert metadata["CFBundleIdentifier"] == "com.northboundwisdom.WeldDataWorkbench"
    assert metadata["CFBundlePackageType"] == "APPL"


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
    assert configuration["args"] == ["configs/workbench_workflow.py", "config"]

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


def test_environment_installation_and_source_update_are_separate_from_config() -> None:
    source_root_workflow = Path("configs/source_root_workflow.py").read_text(encoding="utf-8")
    workbench_workflow = Path("configs/workbench_workflow.py").read_text(encoding="utf-8")

    assert "def _cmd_init" in source_root_workflow
    assert "initialize_environment()" in source_root_workflow
    assert "update_callback=" not in source_root_workflow
    assert "update_workbench" not in source_root_workflow
    assert "def _require_environment" in workbench_workflow
    assert '"refresh-index"' in workbench_workflow
    assert 'elif args.action == "refresh-index"' in workbench_workflow
    assert "python3 configs/source_root_workflow.py --init" in workbench_workflow


def test_config_reuses_index_and_refresh_index_scans_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_root = tmp_path / "dataset"
    workspace_root = tmp_path / "workspace"
    dataset_root.mkdir()
    workspace_root.mkdir()
    (workspace_root / "workbench.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (workspace_root / "index.sqlite3").touch()

    qml_runtime = tmp_path / "Qt" / "6.11.2" / "macos" / "bin" / "qml"
    qml_runtime.parent.mkdir(parents=True)
    qml_runtime.touch(mode=0o755)
    multimedia_module = qml_runtime.parent.parent / "qml" / "QtMultimedia"
    multimedia_module.mkdir(parents=True)
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch(mode=0o755)

    app_configs = {
        "WELD_QML_RUNTIME": str(qml_runtime),
        "WELD_DATASET_HOME": str(tmp_path),
        "WELD_DATASET_ROOT": str(dataset_root),
        "WELD_DATASET_ARCHIVE": str(tmp_path / "dataset.tar.gz"),
        "WELD_EXTRACTED_ROOT": str(tmp_path / "extracted"),
        "WELD_WORKSPACE": str(workspace_root),
        "WELD_SCAN_WORKERS": "3",
    }
    commands: list[list[str]] = []
    receipt = tmp_path / "build" / "freecm" / "configured.json"

    monkeypatch.setattr(workbench_workflow, "CONFIG_RECEIPT", receipt)
    monkeypatch.setattr(workbench_workflow, "load_app_configs", lambda: app_configs)
    monkeypatch.setattr(workbench_workflow, "find_qml_runtime", lambda _explicit: qml_runtime)
    monkeypatch.setattr(
        workbench_workflow,
        "qt_multimedia_module",
        lambda _runtime: multimedia_module,
    )
    monkeypatch.setattr(workbench_workflow, "_require_environment", lambda: python)
    monkeypatch.setattr(
        workbench_workflow,
        "_load_existing_workspace",
        lambda _python, _workspace: ExistingWorkspace(dataset_root, workspace_root),
    )
    monkeypatch.setattr(
        workbench_workflow,
        "_resolve_dataset_root",
        lambda _python, **_kwargs: dataset_root,
    )
    monkeypatch.setattr(
        workbench_workflow,
        "_run_command",
        lambda args, **_kwargs: commands.append([str(value) for value in args]),
    )

    configure()
    configured = json.loads(receipt.read_text(encoding="utf-8"))
    assert configured["index_action"] == "reused"
    assert not any("scan" in command for command in commands)

    refresh_index()
    refreshed = json.loads(receipt.read_text(encoding="utf-8"))
    assert refreshed["index_action"] == "refreshed"
    scan_commands = [command for command in commands if "scan" in command]
    assert len(scan_commands) == 1
    assert scan_commands[0][-5:] == ["--workers", "3", "--probe", "light", "--persist-options"]
