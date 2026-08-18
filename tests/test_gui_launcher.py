from __future__ import annotations

from pathlib import Path

from weld_data_workbench.gui.app import build_qml_command


def test_qml_command_passes_api_and_smoke_arguments_after_separator(tmp_path: Path) -> None:
    runtime = tmp_path / "qml"
    qml_file = tmp_path / "ui" / "Main.qml"

    command = build_qml_command(
        runtime,
        qml_file,
        api_base="http://127.0.0.1:43210",
        smoke_ms=750,
    )

    assert command == [
        str(runtime),
        "-I",
        str(qml_file.parent),
        str(qml_file),
        "--",
        "--api-base=http://127.0.0.1:43210",
        "--smoke-ms=750",
    ]
