from __future__ import annotations

from pathlib import Path

from weld_data_workbench.gui.app import (
    build_native_qml_command,
    build_qml_command,
    discover_qml_launcher,
)

QML_ROOT = Path("src/weld_data_workbench/gui/qml")
COMPONENTS = QML_ROOT / "components"


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


def test_native_qml_frontend_is_componentized_workbench() -> None:
    source = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
    assert 'import "components"' in source
    for component in (
        "ApiClient.qml",
        "TaskPoller.qml",
        "FilterPanel.qml",
        "SampleListPanel.qml",
        "PaginationBar.qml",
        "DetailPanel.qml",
        "AlignmentTimeline.qml",
        "AnnotationPanel.qml",
        "ComparePanel.qml",
        "AnalyticsPanel.qml",
        "TaskPanel.qml",
    ):
        assert (COMPONENTS / component).is_file(), component


def test_native_qml_frontend_uses_background_tasks_and_reconnect() -> None:
    source = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
    api_source = (COMPONENTS / "ApiClient.qml").read_text(encoding="utf-8")
    poller_source = (COMPONENTS / "TaskPoller.qml").read_text(encoding="utf-8")
    assert "/api/tasks/previews/" in source
    assert "/api/tasks/alignment/" in source
    assert "/api/tasks/" in poller_source
    assert "interval: 2000" in source
    assert "/api/health" in source
    assert "property bool connected" in api_source


def test_native_qml_frontend_exposes_pagination_compare_analytics_and_annotations() -> None:
    main = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
    pagination = (COMPONENTS / "PaginationBar.qml").read_text(encoding="utf-8")
    compare = (COMPONENTS / "ComparePanel.qml").read_text(encoding="utf-8")
    analytics = (COMPONENTS / "AnalyticsPanel.qml").read_text(encoding="utf-8")
    annotations = (COMPONENTS / "AnnotationPanel.qml").read_text(encoding="utf-8")
    assert "property int pageOffset: 0" in main
    assert "property int pageLimit: 100" in main
    assert "pageSizeRequested" in pagination
    assert "/matches/good" in compare
    assert "same_split=" in compare
    assert "/api/analytics/distribution" in analytics
    assert "/api/analytics/pivot" in analytics
    assert "/api/annotations" in annotations
    assert "/history?limit=20" in annotations
    assert "expected_revision" in annotations
    assert 'pivotMeasures: ["count", "mean", "median", "sum", "min", "max"]' in analytics


def test_native_qml_frontend_declares_multimedia_and_synchronized_timeline() -> None:
    detail = (COMPONENTS / "DetailPanel.qml").read_text(encoding="utf-8")
    timeline = (COMPONENTS / "AlignmentTimeline.qml").read_text(encoding="utf-8")
    assert "import QtMultimedia" in detail
    assert "MediaPlayer {" in detail
    assert "VideoOutput {" in detail
    assert "AudioOutput {" in detail
    assert "seekReference" in detail
    assert "alignmentOffset" in detail
    assert "seekRequested" in timeline
    assert "end_censored" in timeline
    assert "analysis_window_truncated" in timeline
    assert "time_gap_detected" in timeline


def test_detail_panel_uses_repository_asset_fields_and_issue_overlay() -> None:
    source = (COMPONENTS / "DetailPanel.qml").read_text(encoding="utf-8")
    assert "modelData.file_url" in source
    assert "modelData.status" in source
    assert '"target_type": "issue"' in source
    assert '"ignored"' in source
    assert '"resolved"' in source


def test_sample_delegate_retains_hover_and_alternating_rows() -> None:
    source = (COMPONENTS / "SampleListPanel.qml").read_text(encoding="utf-8")
    assert "id: sampleDelegate" in source
    assert "hoverEnabled: true" in source
    assert "sampleDelegate.hovered" in source
    assert "sampleDelegate.index % 2 === 0" in source
    assert '"#86b5f2"' in source


def test_detail_scroll_view_reserves_scrollbar_gutter() -> None:
    source = (COMPONENTS / "DetailPanel.qml").read_text(encoding="utf-8")
    assert "id: detailScroll" in source
    assert "id: detailVerticalScrollBar" in source
    assert "width: 12" in source
    assert "anchors.right: detailScroll.right" in source
    assert "policy: ScrollBar.AlwaysOn" in source
    assert "property int scrollbarGutter: detailVerticalScrollBar.width + 8" in source
    assert "contentWidth: Math.max(0, availableWidth - scrollbarGutter)" in source
    assert "width: detailScroll.contentWidth" in source


def test_video_preview_supports_double_click_play_pause_toggle() -> None:
    source = (COMPONENTS / "DetailPanel.qml").read_text(encoding="utf-8")
    assert "onDoubleClicked:" in source
    assert "videoPlayer.playbackState === MediaPlayer.PlayingState" in source
    assert "videoPlayer.pause()" in source
    assert "videoPlayer.play()" in source


def test_native_qml_frontend_uses_demo_name_and_icon() -> None:
    source = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
    assert 'title: "Demo"' in source
    assert 'source: Qt.resolvedUrl("assets/demo_icon.png")' in source
    assert (QML_ROOT / "assets" / "demo_icon.png").is_file()
    assert (QML_ROOT / "assets" / "Demo.icns").is_file()


def test_native_launcher_sets_the_system_application_icon() -> None:
    source = Path("src/weld_data_workbench/gui/native/qml_launcher.cpp").read_text(encoding="utf-8")
    assert "setWindowIcon" in source
    assert "WELD_DEMO_ICON" in source
    assert 'setApplicationName(QStringLiteral("Demo"))' in source
