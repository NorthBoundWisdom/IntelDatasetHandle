from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from ..config import load_config
from ..index.repository import DatasetRepository


def _qt_version_key(path: Path) -> tuple[int, ...]:
    for part in reversed(path.parts):
        if re.fullmatch(r"\d+(?:\.\d+)+", part):
            return tuple(int(value) for value in part.split("."))
    return ()


def discover_qml_runtime(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None

    candidates: set[Path] = set()
    for command in ("qml", "qml6"):
        path = shutil.which(command)
        if path:
            candidates.add(Path(path).resolve())
    candidates.update(
        path.resolve()
        for path in (Path.home() / "Qt").glob("*/macos/bin/qml")
        if path.is_file() and os.access(path, os.X_OK)
    )
    return (
        max(candidates, key=lambda path: (_qt_version_key(path), str(path))) if candidates else None
    )


def build_qml_command(
    qml_runtime: Path,
    qml_file: Path,
    *,
    api_base: str,
    smoke_ms: int | None = None,
) -> list[str]:
    command = [
        str(qml_runtime),
        "-I",
        str(qml_file.parent),
        str(qml_file),
        "--",
        f"--api-base={api_base}",
    ]
    if smoke_ms is not None:
        command.append(f"--smoke-ms={smoke_ms}")
    return command


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_api(url: str, server: subprocess.Popen[bytes], timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"Local API exited before becoming ready (code {server.returncode})")
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for local API: {url}")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_gui(
    workspace: Path,
    *,
    smoke_ms: int | None = None,
    qml_runtime: Path | None = None,
) -> int:
    config = load_config(workspace)
    DatasetRepository(config.index_path, config.dataset_root).count_samples()

    explicit_runtime = qml_runtime
    if explicit_runtime is None and os.environ.get("WELD_QML_RUNTIME"):
        explicit_runtime = Path(os.environ["WELD_QML_RUNTIME"])
    runtime = discover_qml_runtime(explicit_runtime)
    if runtime is None:
        raise RuntimeError(
            "No native Qt QML runtime found; set WELD_QML_RUNTIME to the qml executable"
        )

    qml_file = Path(__file__).parent / "qml" / "Main.qml"
    port = _available_port()
    api_base = f"http://127.0.0.1:{port}"
    server_command = [
        sys.executable,
        "-m",
        "weld_data_workbench",
        "serve",
        "--workspace",
        str(config.workspace_root),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    server = subprocess.Popen(server_command)
    try:
        _wait_for_api(f"{api_base}/api/health", server)
        command = build_qml_command(runtime, qml_file, api_base=api_base, smoke_ms=smoke_ms)
        return subprocess.run(command, check=False).returncode
    finally:
        _stop_process(server)


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the native Qt QML dataset browser")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--smoke-ms", type=int, default=None)
    args = parser.parse_args()
    if args.smoke_ms is not None and args.smoke_ms < 1:
        parser.error("--smoke-ms must be positive")
    try:
        code = run_gui(args.workspace, smoke_ms=args.smoke_ms)
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
