from __future__ import annotations

from pathlib import Path

from weld_data_workbench.gui.app import build_native_qml_command, build_qml_command


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


def test_native_qml_launcher_command_passes_api_and_smoke_arguments(tmp_path: Path) -> None:
    command = build_native_qml_command(
        tmp_path / "demo_qml_launcher",
        api_base="http://127.0.0.1:43210",
        smoke_ms=750,
    )

    assert command == [
        str(tmp_path / "demo_qml_launcher"),
        "--api-base=http://127.0.0.1:43210",
        "--smoke-ms=750",
    ]


def test_native_qml_frontend_declares_multimedia_players() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert "import QtMultimedia" in source
    assert "MediaPlayer {" in source
    assert "VideoOutput {" in source
    assert "AudioOutput {" in source


def test_native_qml_frontend_has_explicit_dark_palette_and_full_width_scroll_content() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert "palette {" in source
    assert "windowText: textColor" in source
    assert "buttonText: textColor" in source
    assert source.count("contentWidth: availableWidth") == 2
    assert "width: filterScroll.availableWidth" in source
    assert "width: detailScroll.availableWidth" in source


def test_native_qml_frontend_uses_demo_name_and_icon() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert 'title: "Demo"' in source
    assert 'source: Qt.resolvedUrl("assets/demo_icon.png")' in source
    assert Path("src/weld_data_workbench/gui/qml/assets/demo_icon.png").is_file()
    assert Path("src/weld_data_workbench/gui/qml/assets/Demo.icns").is_file()


def test_native_launcher_sets_the_system_application_icon() -> None:
    source = Path("src/weld_data_workbench/gui/native/qml_launcher.cpp").read_text(encoding="utf-8")

    assert "setWindowIcon" in source
    assert "WELD_DEMO_ICON" in source
    assert 'setApplicationName(QStringLiteral("Demo"))' in source
