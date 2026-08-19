from __future__ import annotations

from pathlib import Path

from weld_data_workbench.gui.app import (
    build_native_qml_command,
    build_qml_command,
    discover_qml_launcher,
)


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
    launcher = tmp_path / "Demo.app" / "Contents" / "MacOS" / "Demo"
    command = build_native_qml_command(
        launcher,
        api_base="http://127.0.0.1:43210",
        smoke_ms=750,
    )

    assert command == [
        str(launcher),
        "--api-base=http://127.0.0.1:43210",
        "--smoke-ms=750",
    ]


def test_native_qml_launcher_discovery_prefers_macos_app_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = tmp_path / "build" / "freecm" / "Demo.app" / "Contents" / "MacOS" / "Demo"
    launcher.parent.mkdir(parents=True)
    launcher.touch(mode=0o755)
    monkeypatch.chdir(tmp_path)

    assert discover_qml_launcher() == launcher.resolve()


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
    assert source.count("contentWidth: availableWidth") == 1
    assert "width: filterScroll.availableWidth" in source
    assert "width: detailScroll.contentWidth" in source


def test_sample_delegate_has_distinct_hover_background() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert "id: sampleDelegate" in source
    assert "hoverEnabled: true" in source
    assert "sampleDelegate.hovered" in source
    assert "color: sampleDelegate.highlighted ? window.palette.highlight :" in source
    assert "property color listRowColor" in source
    assert "property color listRowAlternateColor" in source
    assert "window.listRowHoverColor" in source
    assert '"#86b5f2"' in source


def test_detail_panel_has_inner_padding() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert "SplitView.minimumWidth: 480\n            padding: 12" in source


def test_sample_list_has_dark_alternating_rows_and_separators() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert "property color listPanelColor" in source
    assert "spacing: 1" in source
    assert "index % 2 === 0" in source
    assert "listRowSeparatorColor" in source


def test_detail_scroll_view_reserves_scrollbar_gutter() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert "id: detailScroll" in source
    assert "id: detailVerticalScrollBar" in source
    assert "width: 12" in source
    assert "anchors.right: detailScroll.right" in source
    assert "anchors.top: detailScroll.top" in source
    assert "anchors.bottom: detailScroll.bottom" in source
    assert "policy: ScrollBar.AlwaysOn" in source
    assert "property int scrollbarGutter: detailVerticalScrollBar.width + 8" in source
    assert "contentWidth: Math.max(0, availableWidth - scrollbarGutter)" in source
    assert "width: detailScroll.contentWidth" in source


def test_video_preview_supports_double_click_play_stop_toggle() -> None:
    source = Path("src/weld_data_workbench/gui/qml/Main.qml").read_text(encoding="utf-8")

    assert "MouseArea {" in source
    assert "onDoubleClicked:" in source
    assert "videoPlayer.playbackState === MediaPlayer.PlayingState" in source
    assert "videoPlayer.pause()" in source
    assert "videoPlayer.play()" in source


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
