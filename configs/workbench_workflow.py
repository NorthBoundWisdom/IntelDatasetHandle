#!/usr/bin/env python3
"""FreeCM-facing Config, Build, Run, and Test workflow.

The command manifest stays declarative. This script owns machine-local path
discovery and keeps absolute dataset/workspace paths out of Git.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VENV_ROOT = REPO_ROOT / ".venv"
FREECM_BUILD_ROOT = REPO_ROOT / "build" / "freecm"
CONFIG_RECEIPT = FREECM_BUILD_ROOT / "configured.json"
ENVIRONMENT_MARKER = FREECM_BUILD_ROOT / "environment.json"
WHEEL_ROOT = FREECM_BUILD_ROOT / "wheel"
NATIVE_LAUNCHER_SOURCE = (
    REPO_ROOT / "src" / "weld_data_workbench" / "gui" / "native" / "qml_launcher.cpp"
)
NATIVE_APP_BUNDLE = FREECM_BUILD_ROOT / "Demo.app"
NATIVE_LAUNCHER = NATIVE_APP_BUNDLE / "Contents" / "MacOS" / "Demo"
ICON_SOURCE = (
    REPO_ROOT / "src" / "weld_data_workbench" / "gui" / "qml" / "assets" / "demo_icon_source.png"
)
ICON_PNG = REPO_ROOT / "src" / "weld_data_workbench" / "gui" / "qml" / "assets" / "demo_icon.png"
ICON_ICNS = REPO_ROOT / "src" / "weld_data_workbench" / "gui" / "qml" / "assets" / "Demo.icns"

MANIFEST_SUFFIXES = {".csv", ".tsv", ".txt"}
MANIFEST_SIGNATURE_COLUMNS = {"CATEGORY", "DIRECTORY", "SUBDIRS", "SPLIT"}
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz")
APP_CONFIG_KEYS = (
    "WELD_QML_RUNTIME",
    "WELD_DATASET_HOME",
    "WELD_DATASET_ROOT",
    "WELD_DATASET_ARCHIVE",
    "WELD_EXTRACTED_ROOT",
    "WELD_WORKSPACE",
    "WELD_SCAN_WORKERS",
)


class WorkflowError(RuntimeError):
    """A user-actionable local workflow failure."""


@dataclass(frozen=True, slots=True)
class ExistingWorkspace:
    dataset_root: Path
    workspace_root: Path


def _normalize_column(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]+", "_", str(value).strip().upper())
    return text.strip("_")


def _read_header(path: Path) -> set[str]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            sample = handle.read(16 * 1024)
    except OSError:
        return set()
    if not sample:
        return set()

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        row = next(csv.reader(io.StringIO(sample), dialect=dialect), [])
    except csv.Error:
        row = next(csv.reader(io.StringIO(sample)), [])
    return {_normalize_column(column) for column in row}


def _iter_limited_delimited_files(root: Path, max_depth: int = 4):
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        dirnames.sort(key=str.casefold)
        filenames.sort(key=str.casefold)
        if depth >= max_depth:
            dirnames[:] = []
        for filename in filenames:
            path = current_path / filename
            if path.suffix.casefold() in MANIFEST_SUFFIXES:
                yield path


def discover_dataset_root(extraction_root: Path) -> Path | None:
    """Find a dataset root by manifest columns, independent of names/wrappers."""
    extraction_root = extraction_root.expanduser().resolve()
    if not extraction_root.is_dir():
        return None

    best: tuple[int, int, Path] | None = None
    for path in _iter_limited_delimited_files(extraction_root):
        columns = _read_header(path)
        matched = columns & MANIFEST_SIGNATURE_COLUMNS
        if "CATEGORY" not in matched or "SPLIT" not in matched:
            continue
        if not ({"DIRECTORY", "SUBDIRS"} & matched):
            continue
        score = len(matched)
        depth = len(path.relative_to(extraction_root).parts)
        candidate = (score, -depth, path)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
        if matched == MANIFEST_SIGNATURE_COLUMNS:
            return path.parent.resolve()
    return best[2].parent.resolve() if best else None


def find_dataset_archive(data_home: Path, explicit: Path | None = None) -> Path | None:
    """Return an explicit or unique tar.gz/tgz archive in the dataset home."""
    if explicit is not None:
        archive = explicit.expanduser().resolve()
        if not archive.is_file():
            raise WorkflowError(f"Dataset archive does not exist: {archive}")
        return archive

    data_home = data_home.expanduser().resolve()
    if not data_home.is_dir():
        return None
    candidates = sorted(
        path.resolve()
        for path in data_home.iterdir()
        if path.is_file() and path.name.casefold().endswith(ARCHIVE_SUFFIXES)
    )
    return candidates[0] if len(candidates) == 1 else None


def _qt_version_key(path: Path) -> tuple[int, ...]:
    for part in reversed(path.parts):
        if re.fullmatch(r"\d+(?:\.\d+)+", part):
            return tuple(int(value) for value in part.split("."))
    return ()


def find_qml_runtime(explicit: Path | None = None) -> Path | None:
    """Locate an executable Qt QML runtime without committing a host path."""
    if explicit is not None:
        runtime = explicit.expanduser().resolve()
        if not runtime.is_file() or not os.access(runtime, os.X_OK):
            raise WorkflowError(f"QML runtime is not executable: {runtime}")
        return runtime

    candidates: set[Path] = set()
    for command in ("qml", "qml6"):
        discovered = shutil.which(command)
        if discovered:
            candidates.add(Path(discovered).resolve())
    candidates.update(
        path.resolve()
        for path in (Path.home() / "Qt").glob("*/macos/bin/qml")
        if path.is_file() and os.access(path, os.X_OK)
    )
    return (
        max(candidates, key=lambda path: (_qt_version_key(path), str(path))) if candidates else None
    )


def qt_multimedia_module(qml_runtime: Path) -> Path:
    return (qml_runtime.expanduser().resolve().parent.parent / "qml" / "QtMultimedia").resolve()


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_ROOT / "Scripts" / "python.exe"
    return VENV_ROOT / "bin" / "python"


def load_app_configs() -> dict[str, str]:
    """Load the project configuration directly from the active FreeCM lock."""

    # Keep ordinary module imports/tests independent from the checked-out FreeCM
    # submodule. The real Config action loads it only when lock access is needed.
    from configs.source_roots import WORKFLOW

    lock_data = WORKFLOW.load_lock_file(REPO_ROOT)
    raw_configs = lock_data.get("AppConfigs")
    if not isinstance(raw_configs, dict):
        raise WorkflowError("source_roots.lock.jsonc must contain an AppConfigs object")

    result: dict[str, str] = {}
    for key in APP_CONFIG_KEYS:
        value = raw_configs.get(key)
        if not isinstance(value, str) or not value:
            raise WorkflowError(f"AppConfigs.{key} must be a non-empty string")
        result[key] = value
    return result


def _path_from_configs(configs: Mapping[str, str], name: str, default: Path) -> Path:
    raw = configs.get(name)
    return Path(raw).expanduser().resolve() if raw else default.expanduser().resolve()


def _display_command(args: Sequence[str | Path]) -> str:
    return shlex.join(str(item) for item in args)


def _run_command(
    args: Sequence[str | Path],
    *,
    capture_output: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [str(item) for item in args]
    print(f"+ {_display_command(args)}", flush=True)
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=capture_output,
        env=env,
    )
    if result.returncode != 0:
        if capture_output:
            if result.stdout:
                print(result.stdout, file=sys.stderr, end="")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
        raise WorkflowError(
            f"Command failed with exit code {result.returncode}: {_display_command(args)}"
        )
    return result


def _pyproject_sha256() -> str:
    return hashlib.sha256((REPO_ROOT / "pyproject.toml").read_bytes()).hexdigest()


def _environment_marker_is_current(python: Path) -> bool:
    if not python.is_file() or not ENVIRONMENT_MARKER.is_file():
        return False
    try:
        marker = json.loads(ENVIRONMENT_MARKER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if marker.get("python") != str(python) or marker.get("pyproject_sha256") != _pyproject_sha256():
        return False
    probe = subprocess.run(
        [python, "-c", "import build, fastapi, pandas, weld_data_workbench"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


def _write_environment_marker(python: Path) -> None:
    ENVIRONMENT_MARKER.parent.mkdir(parents=True, exist_ok=True)
    temporary = ENVIRONMENT_MARKER.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "configured_at": datetime.now(UTC).isoformat(),
                "python": str(python),
                "pyproject_sha256": _pyproject_sha256(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(ENVIRONMENT_MARKER)


def _ensure_environment() -> Path:
    if sys.version_info < (3, 11):  # noqa: UP036 - bootstrap runs before package install
        raise WorkflowError("Config requires Python 3.11 or newer")

    python = _venv_python()
    if _environment_marker_is_current(python):
        print(f"Reusing configured environment: {python}")
        return python
    if not python.is_file():
        _run_command([sys.executable, "-m", "venv", VENV_ROOT])
    _run_command([python, "-m", "pip", "install", "--upgrade", "pip", "setuptools>=68", "wheel"])
    _run_command([python, "-m", "pip", "install", "-e", ".[all,dev]"])
    _write_environment_marker(python)
    return python


def _require_environment() -> Path:
    python = _venv_python()
    if not _environment_marker_is_current(python):
        raise WorkflowError(
            "Environment is not initialized; run `python3 configs/source_root_workflow.py --init`"
        )
    return python


def initialize_environment() -> Path:
    """Install/update the project environment; intended for FreeCM --init."""
    python = _ensure_environment()
    print(f"Environment ready: {python}")
    return python


def _load_existing_workspace(python: Path, workspace_root: Path) -> ExistingWorkspace | None:
    config_path = workspace_root / "workbench.yaml"
    if not config_path.is_file():
        return None
    query = (
        "import json, sys; "
        "from pathlib import Path; "
        "from weld_data_workbench.config import load_config; "
        "config = load_config(Path(sys.argv[1])); "
        "print(json.dumps({'dataset_root': str(config.dataset_root), "
        "'workspace_root': str(config.workspace_root)}))"
    )
    result = _run_command(
        [python, "-c", query, workspace_root],
        capture_output=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    return ExistingWorkspace(
        dataset_root=Path(payload["dataset_root"]).resolve(),
        workspace_root=Path(payload["workspace_root"]).resolve(),
    )


def _resolve_dataset_root(
    python: Path,
    *,
    data_home: Path,
    extraction_root: Path,
    existing: ExistingWorkspace | None,
    app_configs: Mapping[str, str],
) -> Path:
    explicit_root = app_configs.get("WELD_DATASET_ROOT")
    if explicit_root:
        requested_root = Path(explicit_root).expanduser().resolve()
        discovered = discover_dataset_root(requested_root)
        if discovered is None:
            raise WorkflowError(
                f"WELD_DATASET_ROOT does not contain a compatible manifest: {requested_root}"
            )
        return discovered

    if (
        existing is not None
        and existing.dataset_root.is_dir()
        and discover_dataset_root(existing.dataset_root) is not None
    ):
        return existing.dataset_root

    discovered = discover_dataset_root(extraction_root)
    if discovered is not None:
        return discovered

    explicit_archive = app_configs.get("WELD_DATASET_ARCHIVE")
    archive = find_dataset_archive(
        data_home,
        Path(explicit_archive) if explicit_archive else None,
    )
    if archive is None:
        raise WorkflowError(
            "No extracted dataset or unambiguous archive was found. Set "
            "WELD_DATASET_ROOT or WELD_DATASET_ARCHIVE."
        )
    _run_command([python, "-m", "weld_data_workbench", "extract", archive, extraction_root])
    discovered = discover_dataset_root(extraction_root)
    if discovered is None:
        raise WorkflowError(f"No compatible manifest found after extracting {archive}")
    return discovered


def _scan_workers(app_configs: Mapping[str, str]) -> int:
    raw = app_configs.get("WELD_SCAN_WORKERS")
    workers = int(raw) if raw else min(8, max(1, os.cpu_count() or 1))
    if not 1 <= workers <= 128:
        raise WorkflowError("WELD_SCAN_WORKERS must be between 1 and 128")
    return workers


def _write_receipt(payload: dict[str, object]) -> None:
    CONFIG_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_RECEIPT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(CONFIG_RECEIPT)


def _configure_workbench(*, force_refresh_index: bool) -> None:
    CONFIG_RECEIPT.unlink(missing_ok=True)
    app_configs = load_app_configs()
    scan_workers = _scan_workers(app_configs)
    explicit_qml = app_configs.get("WELD_QML_RUNTIME")
    qml_runtime = find_qml_runtime(Path(explicit_qml) if explicit_qml else None)
    if qml_runtime is None:
        raise WorkflowError(
            "No native Qt QML runtime found. Set WELD_QML_RUNTIME to the qml executable."
        )
    multimedia_module = qt_multimedia_module(qml_runtime)
    if not multimedia_module.is_dir():
        raise WorkflowError(f"Qt Multimedia QML module is missing: {multimedia_module}")
    python = _require_environment()

    data_home = _path_from_configs(
        app_configs,
        "WELD_DATASET_HOME",
        Path.home() / "Datasets" / "IntelWelding",
    )
    extraction_root = _path_from_configs(
        app_configs,
        "WELD_EXTRACTED_ROOT",
        data_home / "extracted",
    )
    workspace_root = _path_from_configs(
        app_configs,
        "WELD_WORKSPACE",
        data_home / "workspace",
    )
    existing = _load_existing_workspace(python, workspace_root)
    dataset_root = _resolve_dataset_root(
        python,
        data_home=data_home,
        extraction_root=extraction_root,
        existing=existing,
        app_configs=app_configs,
    )

    same_config = (
        existing is not None
        and existing.dataset_root == dataset_root
        and existing.workspace_root == workspace_root
    )
    if not same_config:
        init_args: list[str | Path] = [
            python,
            "-m",
            "weld_data_workbench",
            "init",
            "--dataset-root",
            dataset_root,
            "--workspace",
            workspace_root,
        ]
        if (workspace_root / "workbench.yaml").exists():
            init_args.append("--force")
        _run_command(init_args)

    index_path = workspace_root / "index.sqlite3"
    refresh_required = force_refresh_index or not same_config or not index_path.is_file()
    if refresh_required:
        _run_command(
            [
                python,
                "-m",
                "weld_data_workbench",
                "scan",
                "--workspace",
                workspace_root,
                "--workers",
                str(scan_workers),
                "--probe",
                "light",
                "--persist-options",
            ]
        )
    if not index_path.is_file():
        raise WorkflowError(f"Config completed without creating the index: {index_path}")

    receipt = {
        "configured_at": datetime.now(UTC).isoformat(),
        "dataset_root": str(dataset_root),
        "index_action": "refreshed" if refresh_required else "reused",
        "index_path": str(index_path),
        "python": str(python),
        "qml_runtime": str(qml_runtime),
        "qt_multimedia_module": str(multimedia_module),
        "scan_workers": scan_workers,
        "workspace_root": str(workspace_root),
    }
    _write_receipt(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


def configure() -> None:
    """Apply active-lock settings and reuse an existing local index."""

    _configure_workbench(force_refresh_index=False)


def refresh_index() -> None:
    """Apply active-lock settings and explicitly rebuild the incremental index."""

    _configure_workbench(force_refresh_index=True)


def _require_configuration() -> tuple[Path, Path, Path]:
    python = _venv_python()
    if not python.is_file() or not CONFIG_RECEIPT.is_file():
        raise WorkflowError("Run the FreeCM Config action before this command")
    try:
        receipt = json.loads(CONFIG_RECEIPT.read_text(encoding="utf-8"))
        workspace_root = Path(receipt["workspace_root"]).expanduser().resolve()
        qml_runtime = Path(receipt["qml_runtime"]).expanduser().resolve()
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Invalid FreeCM Config receipt: {CONFIG_RECEIPT}") from exc
    if not (workspace_root / "workbench.yaml").is_file():
        raise WorkflowError(f"Workspace configuration is missing: {workspace_root}")
    if not (workspace_root / "index.sqlite3").is_file():
        raise WorkflowError(f"Workspace index is missing: {workspace_root}")
    if not qml_runtime.is_file() or not os.access(qml_runtime, os.X_OK):
        raise WorkflowError(f"Configured QML runtime is unavailable: {qml_runtime}")
    multimedia_module = qt_multimedia_module(qml_runtime)
    if not multimedia_module.is_dir():
        raise WorkflowError(f"Configured Qt Multimedia module is unavailable: {multimedia_module}")
    return python, workspace_root, qml_runtime


def _clean_python_build_staging() -> None:
    build_root = REPO_ROOT / "build"
    stale_paths = [build_root / "lib", *build_root.glob("bdist.*")]
    for path in stale_paths:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def prepare_native_app_bundle(app_bundle: Path, icon_source: Path = ICON_ICNS) -> Path:
    """Create the macOS bundle metadata/resources and return its executable path."""

    if not icon_source.is_file():
        raise WorkflowError(f"Native app icon is missing: {icon_source}")
    contents = app_bundle / "Contents"
    executable = contents / "MacOS" / "Demo"
    resources = contents / "Resources"
    executable.parent.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_source, resources / "Demo.icns")

    metadata = {
        "CFBundleDevelopmentRegion": "English",
        "CFBundleDisplayName": "Demo",
        "CFBundleExecutable": "Demo",
        "CFBundleIconFile": "Demo.icns",
        "CFBundleIdentifier": "com.northboundwisdom.WeldDataWorkbench",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Demo",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    }
    info_plist = contents / "Info.plist"
    temporary = info_plist.with_suffix(".plist.tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(metadata, handle, sort_keys=True)
    temporary.replace(info_plist)
    return executable


def build_native_launcher(qml_runtime: Path) -> Path:
    if sys.platform != "darwin":
        raise WorkflowError("The native Qt icon launcher currently requires macOS")
    compiler_name = os.environ.get("CXX", "clang++")
    compiler = shutil.which(compiler_name)
    if compiler is None:
        raise WorkflowError(f"C++ compiler not found: {compiler_name}")
    qt_root = qml_runtime.expanduser().resolve().parent.parent
    if not NATIVE_LAUNCHER_SOURCE.is_file():
        raise WorkflowError(f"Native QML launcher source is missing: {NATIVE_LAUNCHER_SOURCE}")

    launcher = prepare_native_app_bundle(NATIVE_APP_BUNDLE)
    command: list[str | Path] = [
        compiler,
        "-std=c++17",
        "-O2",
        "-F",
        qt_root / "lib",
        "-I",
        qt_root / "include",
        "-I",
        qt_root / "lib" / "QtCore.framework" / "Headers",
        "-I",
        qt_root / "lib" / "QtGui.framework" / "Headers",
        "-I",
        qt_root / "lib" / "QtQml.framework" / "Headers",
        "-I",
        qt_root / "lib" / "QtQuick.framework" / "Headers",
        NATIVE_LAUNCHER_SOURCE,
        "-framework",
        "QtCore",
        "-framework",
        "QtGui",
        "-framework",
        "QtQml",
        "-framework",
        "QtQuick",
        f"-Wl,-rpath,{qt_root / 'lib'}",
        "-o",
        launcher,
    ]
    _run_command(command)
    os.utime(NATIVE_APP_BUNDLE, None)
    return launcher


def build_wheel() -> None:
    python, _workspace_root, qml_runtime = _require_configuration()
    build_native_launcher(qml_runtime)
    qmllint = qml_runtime.with_name("qmllint")
    qml_root = REPO_ROOT / "src" / "weld_data_workbench" / "gui" / "qml"
    if qmllint.is_file():
        _run_command([qmllint, "-I", qml_root, qml_root / "Main.qml"])
    _clean_python_build_staging()
    WHEEL_ROOT.mkdir(parents=True, exist_ok=True)
    _run_command([python, "-m", "build", "--wheel", "--no-isolation", "--outdir", WHEEL_ROOT])
    wheels = sorted(
        WHEEL_ROOT.glob("weld_data_workbench-*.whl"), key=lambda path: path.stat().st_mtime
    )
    if not wheels:
        raise WorkflowError(f"Build produced no wheel in {WHEEL_ROOT}")
    wheel = wheels[-1]
    with zipfile.ZipFile(wheel) as archive:
        resources = set(archive.namelist())
        metadata_paths = [name for name in resources if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise WorkflowError(f"Built wheel has an invalid METADATA layout: {wheel}")
        metadata = archive.read(metadata_paths[0]).decode("utf-8")
    required_resources = {
        "weld_data_workbench/gui/qml/Main.qml",
        "weld_data_workbench/gui/qml/assets/demo_icon.png",
        "weld_data_workbench/gui/qml/assets/Demo.icns",
    }
    missing_resources = sorted(required_resources - resources)
    if missing_resources:
        raise WorkflowError(f"Built wheel is missing QML resources {missing_resources}: {wheel}")
    forbidden_resources = {
        "weld_data_workbench/gui/controller.py",
        "weld_data_workbench/gui/models.py",
    }
    unexpected = sorted(resources & forbidden_resources)
    if unexpected:
        raise WorkflowError(f"Built wheel contains removed PySide bridge files: {unexpected}")
    if re.search(r"^Requires-Dist:\s*PySide", metadata, flags=re.MULTILINE | re.IGNORECASE):
        raise WorkflowError(f"Built wheel still declares a PySide dependency: {wheel}")
    print(f"Built and verified {wheel}")


def run_tests() -> None:
    python, _workspace_root, _qml_runtime = _require_configuration()
    _run_command([python, "-m", "ruff", "check", "src", "tests", "scripts", "configs"])
    _run_command([python, "-m", "ruff", "format", "--check", "src", "tests", "scripts", "configs"])
    _run_command([python, "-m", "compileall", "-q", "src", "scripts", "tests", "configs"])
    _run_command([python, "-m", "pytest", "-q"])


def run_qml(*, check: bool) -> None:
    python, workspace_root, qml_runtime = _require_configuration()
    launcher = build_native_launcher(qml_runtime)
    command: list[str | Path] = [
        python,
        "-m",
        "weld_data_workbench",
        "gui",
        "--workspace",
        workspace_root,
    ]
    environment = os.environ.copy()
    environment["WELD_QML_RUNTIME"] = str(qml_runtime)
    environment["WELD_QML_LAUNCHER"] = str(launcher)
    if check:
        command.extend(["--smoke-ms", "750"])
        _run_command(command, env=environment)
        return

    print(f"+ {_display_command(command)}", flush=True)
    os.chdir(REPO_ROOT)
    os.execve(str(python), [str(item) for item in command], environment)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser(
        "config",
        help="Apply active-lock settings and reuse the existing dataset index",
    )
    subparsers.add_parser(
        "refresh-index",
        help="Apply active-lock settings and explicitly refresh the dataset index",
    )
    subparsers.add_parser("build", help="Build and verify the Python wheel")
    subparsers.add_parser("test", help="Run the precommit verification suite")
    run_parser = subparsers.add_parser("run", help="Launch the QML dataset workbench")
    run_parser.add_argument(
        "--check",
        action="store_true",
        help="Load QML offscreen and exit, for workflow verification",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "config":
            configure()
        elif args.action == "refresh-index":
            refresh_index()
        elif args.action == "build":
            build_wheel()
        elif args.action == "test":
            run_tests()
        elif args.action == "run":
            run_qml(check=args.check)
        else:  # pragma: no cover - argparse enforces the command set
            raise WorkflowError(f"Unsupported action: {args.action}")
    except (OSError, ValueError, WorkflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
