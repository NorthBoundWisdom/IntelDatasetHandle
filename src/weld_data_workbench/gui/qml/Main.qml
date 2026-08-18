import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtMultimedia
import "components"

ApplicationWindow {
    id: window
    width: 1540
    height: 920
    minimumWidth: 1180
    minimumHeight: 720
    visible: true
    title: "WeldDataWorkbench"

    property var selected: controller.selectedSample
    property var previews: controller.previewBundle

    function humanBytes(value) {
        if (value === undefined || value === null) return "—"
        let units = ["B", "KB", "MB", "GB", "TB"]
        let size = Number(value)
        let index = 0
        while (size >= 1024 && index < units.length - 1) {
            size /= 1024
            index += 1
        }
        return size.toFixed(index === 0 ? 0 : 1) + " " + units[index]
    }

    FileDialog {
        id: workspaceDialog
        title: "Select workbench.yaml or its workspace folder"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Workbench configuration (workbench.yaml)", "All files (*)"]
        onAccepted: controller.open_workspace(selectedFile)
    }

    MessageDialog {
        id: errorDialog
        title: "WeldDataWorkbench"
        buttons: MessageDialog.Ok
    }

    Connections {
        target: controller
        function onErrorOccurred(message) {
            errorDialog.text = message
            errorDialog.open()
        }
    }

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 10

            Label {
                text: "WeldDataWorkbench"
                font.pixelSize: 18
                font.bold: true
            }
            Rectangle { width: 1; height: 26; color: palette.mid }
            Label {
                text: controller.workspacePath.length ? controller.workspacePath : "No workspace open"
                elide: Text.ElideMiddle
                Layout.fillWidth: true
                color: controller.workspacePath.length ? palette.text : palette.mid
            }
            BusyIndicator {
                running: controller.busy
                visible: running
                implicitWidth: 28
                implicitHeight: 28
            }
            Button {
                text: "Open"
                onClicked: workspaceDialog.open()
            }
            Button {
                text: "Refresh"
                enabled: controller.workspacePath.length > 0 && !controller.busy
                onClicked: controller.refresh()
            }
            Button {
                text: "Rebuild index"
                enabled: controller.workspacePath.length > 0 && !controller.busy
                onClicked: controller.rebuild_index()
            }
        }
    }

    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            Label {
                text: controller.statusText
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Label {
                text: controller.sampleCount + " matching samples"
                color: palette.mid
            }
        }
    }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        Pane {
            SplitView.preferredWidth: 260
            SplitView.minimumWidth: 220
            padding: 12

            ScrollView {
                anchors.fill: parent
                clip: true
                ColumnLayout {
                    width: parent.width
                    spacing: 10

                    Label { text: "Dataset"; font.bold: true; font.pixelSize: 16 }
                    StatCard {
                        label: "Samples"
                        value: controller.stats.total_samples === undefined ? "—" : controller.stats.total_samples.toLocaleString()
                        detail: controller.stats.total_sessions === undefined ? "" : controller.stats.total_sessions + " sessions"
                    }
                    StatCard {
                        label: "Indexed media"
                        value: window.humanBytes(controller.stats.total_bytes)
                        detail: controller.stats.total_assets === undefined ? "" : controller.stats.total_assets + " assets"
                    }
                    StatCard {
                        label: "Issues"
                        value: controller.stats.total_issues === undefined ? "—" : controller.stats.total_issues.toLocaleString()
                        detail: controller.stats.issues_by_severity === undefined ? "" :
                                ((controller.stats.issues_by_severity.error || 0) + " errors · " +
                                 (controller.stats.issues_by_severity.warning || 0) + " warnings")
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: palette.mid }
                    Label { text: "Filters"; font.bold: true; font.pixelSize: 16 }
                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        placeholderText: "ID, path, category, material…"
                        onAccepted: applyFilters()
                    }
                    ComboBox {
                        id: categoryCombo
                        Layout.fillWidth: true
                        model: ["All"].concat(controller.categories)
                    }
                    ComboBox {
                        id: splitCombo
                        Layout.fillWidth: true
                        model: ["All"].concat(controller.splits)
                    }
                    ComboBox {
                        id: healthCombo
                        Layout.fillWidth: true
                        model: ["All", "ok", "warning", "error", "unprobed"]
                    }
                    Button {
                        text: "Apply filters"
                        Layout.fillWidth: true
                        onClicked: applyFilters()
                    }
                    Button {
                        text: "Clear"
                        flat: true
                        Layout.fillWidth: true
                        onClicked: {
                            searchField.text = ""
                            categoryCombo.currentIndex = 0
                            splitCombo.currentIndex = 0
                            healthCombo.currentIndex = 0
                            applyFilters()
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }

        Pane {
            SplitView.preferredWidth: 430
            SplitView.minimumWidth: 320
            padding: 0

            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                Label {
                    text: "Samples"
                    font.pixelSize: 16
                    font.bold: true
                    padding: 12
                    Layout.fillWidth: true
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: palette.mid }
                ListView {
                    id: sampleList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: sampleModel
                    clip: true
                    currentIndex: -1
                    ScrollBar.vertical: ScrollBar {}

                    delegate: ItemDelegate {
                        required property string sampleId
                        required property string sessionId
                        required property string relpath
                        required property string category
                        required property string split
                        required property string healthStatus
                        required property double totalBytes
                        required property int imageCount

                        width: sampleList.width
                        height: 88
                        highlighted: ListView.isCurrentItem
                        onClicked: {
                            sampleList.currentIndex = index
                            controller.select_sample(sampleId)
                        }

                        contentItem: RowLayout {
                            spacing: 10
                            Rectangle {
                                width: 8
                                Layout.fillHeight: true
                                radius: 4
                                color: healthStatus === "error" ? "#c84a4a" :
                                       healthStatus === "warning" ? "#d2a33b" : "#4c9f70"
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Label {
                                    text: category || "Unknown category"
                                    font.bold: true
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Label {
                                    text: sampleId
                                    color: palette.mid
                                    font.family: "monospace"
                                    elide: Text.ElideMiddle
                                    Layout.fillWidth: true
                                }
                                RowLayout {
                                    Label { text: split || "no split"; font.pixelSize: 11 }
                                    Label { text: "·"; color: palette.mid }
                                    Label { text: imageCount + " images"; font.pixelSize: 11 }
                                    Label { text: "·"; color: palette.mid }
                                    Label { text: window.humanBytes(totalBytes); font.pixelSize: 11 }
                                    Item { Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }
            }
        }

        Pane {
            SplitView.fillWidth: true
            SplitView.minimumWidth: 520
            padding: 0

            EmptyState {
                anchors.fill: parent
                visible: !window.selected || !window.selected.sample_id
                title: "Select a weld sample"
                detail: "The detail panel combines annotations, media, cached previews, and integrity issues from the local SQLite index."
            }

            ScrollView {
                anchors.fill: parent
                visible: window.selected && window.selected.sample_id
                clip: true

                ColumnLayout {
                    width: parent.width
                    spacing: 0

                    Pane {
                        Layout.fillWidth: true
                        padding: 18
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 8
                            RowLayout {
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Label {
                                        text: window.selected.category || "Unknown category"
                                        font.pixelSize: 24
                                        font.bold: true
                                        Layout.fillWidth: true
                                    }
                                    Label {
                                        text: window.selected.sample_id || ""
                                        font.family: "monospace"
                                        color: palette.mid
                                    }
                                }
                                AssetPill {
                                    text: window.selected.health_status || "unknown"
                                    status: window.selected.health_status || "warning"
                                }
                                Button {
                                    text: "Reveal"
                                    onClicked: controller.open_path(window.selected.file_url || window.selected.absolute_path)
                                }
                                Button {
                                    text: "Copy path"
                                    onClicked: controller.copy_text(window.selected.absolute_path || "")
                                }
                            }
                            Label {
                                text: window.selected.relpath || ""
                                wrapMode: Text.WrapAnywhere
                                color: palette.mid
                                Layout.fillWidth: true
                            }
                        }
                    }

                    TabBar {
                        id: detailTabs
                        Layout.fillWidth: true
                        TabButton { text: "Overview" }
                        TabButton { text: "Video" }
                        TabButton { text: "Audio & sensors" }
                        TabButton { text: "Assets" }
                        TabButton { text: "Issues (" + ((window.selected.issues || []).length) + ")" }
                    }

                    StackLayout {
                        currentIndex: detailTabs.currentIndex
                        Layout.fillWidth: true

                        Pane {
                            padding: 18
                            ColumnLayout {
                                width: parent.width
                                spacing: 14
                                GridLayout {
                                    columns: 4
                                    columnSpacing: 14
                                    rowSpacing: 8
                                    Layout.fillWidth: true
                                    Label { text: "Split"; color: palette.mid }
                                    Label { text: window.selected.split || "—" }
                                    Label { text: "Session"; color: palette.mid }
                                    Label { text: window.selected.session_id || "—" }
                                    Label { text: "Weld type"; color: palette.mid }
                                    Label { text: window.selected.weld_type || "—" }
                                    Label { text: "Steel"; color: palette.mid }
                                    Label { text: window.selected.steel_type || "—" }
                                    Label { text: "Thickness"; color: palette.mid }
                                    Label { text: window.selected.thickness_mm === null ? "—" : window.selected.thickness_mm + " mm" }
                                    Label { text: "Current"; color: palette.mid }
                                    Label { text: window.selected.current_a === null ? "—" : window.selected.current_a + " A" }
                                    Label { text: "Voltage"; color: palette.mid }
                                    Label { text: window.selected.voltage_v === null ? "—" : window.selected.voltage_v + " V" }
                                    Label { text: "Robot speed"; color: palette.mid }
                                    Label { text: window.selected.robot_speed_cpm === null ? "—" : window.selected.robot_speed_cpm + " CPM" }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "Cached previews"; font.bold: true; font.pixelSize: 16 }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: window.previews.sample_id ? "Regenerate" : "Generate previews"
                                        enabled: !controller.busy
                                        onClicked: controller.generate_previews(window.selected.sample_id, window.previews.sample_id !== undefined)
                                    }
                                }
                                Image {
                                    source: window.previews.video_contact_sheet_url || ""
                                    visible: status === Image.Ready
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    sourceSize.width: 1100
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: visible ? Math.min(420, implicitHeight) : 0
                                }
                                Flow {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Repeater {
                                        model: window.previews.image_thumbnail_urls || []
                                        delegate: Image {
                                            required property string modelData
                                            source: modelData
                                            width: 170
                                            height: 130
                                            fillMode: Image.PreserveAspectFit
                                            asynchronous: true
                                            MouseArea {
                                                anchors.fill: parent
                                                onDoubleClicked: controller.open_path(parent.source)
                                            }
                                        }
                                    }
                                }
                                Label {
                                    visible: (window.previews.warnings || []).length > 0
                                    text: (window.previews.warnings || []).join("\n")
                                    color: "#d2a33b"
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        Pane {
                            padding: 18
                            ColumnLayout {
                                width: parent.width
                                spacing: 10
                                MediaPlayer {
                                    id: mediaPlayer
                                    source: window.selected.primary_video_url || ""
                                    audioOutput: AudioOutput { volume: volumeSlider.value }
                                    videoOutput: videoOutput
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 500
                                    color: "black"
                                    VideoOutput {
                                        id: videoOutput
                                        anchors.fill: parent
                                        fillMode: VideoOutput.PreserveAspectFit
                                    }
                                    Label {
                                        anchors.centerIn: parent
                                        visible: !window.selected.primary_video_url
                                        text: "No indexed video"
                                        color: "white"
                                    }
                                }
                                RowLayout {
                                    Button { text: mediaPlayer.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"; onClicked: mediaPlayer.playbackState === MediaPlayer.PlayingState ? mediaPlayer.pause() : mediaPlayer.play() }
                                    Button { text: "Stop"; onClicked: mediaPlayer.stop() }
                                    Slider {
                                        Layout.fillWidth: true
                                        from: 0
                                        to: Math.max(mediaPlayer.duration, 1)
                                        value: mediaPlayer.position
                                        onMoved: mediaPlayer.position = value
                                    }
                                    Label { text: Math.floor(mediaPlayer.position / 1000) + " / " + Math.floor(mediaPlayer.duration / 1000) + " s" }
                                    Label { text: "Volume" }
                                    Slider { id: volumeSlider; from: 0; to: 1; value: 0.5; Layout.preferredWidth: 100 }
                                }
                            }
                        }

                        Pane {
                            padding: 18
                            ColumnLayout {
                                width: parent.width
                                spacing: 14
                                RowLayout {
                                    Label { text: "Derived views"; font.bold: true; font.pixelSize: 16 }
                                    Item { Layout.fillWidth: true }
                                    Button {
                                        text: "Generate / refresh"
                                        enabled: !controller.busy
                                        onClicked: controller.generate_previews(window.selected.sample_id, true)
                                    }
                                }
                                Label { text: "Audio waveform"; font.bold: true }
                                Image {
                                    source: window.previews.audio_waveform_url || ""
                                    visible: status === Image.Ready
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    sourceSize.width: 1200
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: visible ? 260 : 0
                                }
                                Label { text: "Audio spectrogram"; font.bold: true }
                                Image {
                                    source: window.previews.audio_spectrogram_url || ""
                                    visible: status === Image.Ready
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    sourceSize.width: 1200
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: visible ? 340 : 0
                                }
                                Label { text: "Sensor time series"; font.bold: true }
                                Image {
                                    source: window.previews.sensor_plot_url || ""
                                    visible: status === Image.Ready
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    sourceSize.width: 1200
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: visible ? 420 : 0
                                }
                                EmptyState {
                                    visible: !window.previews.sample_id
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 280
                                    title: "Previews are generated on demand"
                                    detail: "Generation is bounded to one selected sample and cached in the workspace."
                                }
                            }
                        }

                        Pane {
                            padding: 18
                            ColumnLayout {
                                width: parent.width
                                spacing: 8
                                Repeater {
                                    model: window.selected.assets || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        implicitHeight: assetColumn.implicitHeight + 20
                                        radius: 6
                                        color: palette.alternateBase
                                        border.color: palette.mid
                                        ColumnLayout {
                                            id: assetColumn
                                            anchors.fill: parent
                                            anchors.margins: 10
                                            RowLayout {
                                                Layout.fillWidth: true
                                                AssetPill { text: modelData.kind + " #" + modelData.ordinal; status: modelData.status }
                                                Label { text: window.humanBytes(modelData.size_bytes); color: palette.mid }
                                                Item { Layout.fillWidth: true }
                                                Button { text: "Open"; onClicked: controller.open_path(modelData.file_url) }
                                            }
                                            Label { text: modelData.relpath; font.family: "monospace"; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                            Label {
                                                text: JSON.stringify(modelData.metadata_json || {}, null, 2)
                                                font.family: "monospace"
                                                font.pixelSize: 10
                                                wrapMode: Text.WrapAnywhere
                                                color: palette.mid
                                                Layout.fillWidth: true
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Pane {
                            padding: 18
                            ColumnLayout {
                                width: parent.width
                                spacing: 8
                                EmptyState {
                                    visible: (window.selected.issues || []).length === 0
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 280
                                    title: "No indexed issues"
                                    detail: "This does not prove semantic correctness; it means the configured structural and media checks passed."
                                }
                                Repeater {
                                    model: window.selected.issues || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        implicitHeight: issueColumn.implicitHeight + 20
                                        radius: 6
                                        color: palette.alternateBase
                                        border.color: modelData.severity === "error" ? "#c84a4a" : modelData.severity === "warning" ? "#d2a33b" : palette.mid
                                        ColumnLayout {
                                            id: issueColumn
                                            anchors.fill: parent
                                            anchors.margins: 10
                                            RowLayout {
                                                IssueBadge { severity: modelData.severity }
                                                Label { text: modelData.code; font.bold: true }
                                                Item { Layout.fillWidth: true }
                                            }
                                            Label { text: modelData.message; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                            Label { text: modelData.relpath || ""; font.family: "monospace"; color: palette.mid; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    function applyFilters() {
        controller.set_filters(searchField.text, categoryCombo.currentText, splitCombo.currentText, healthCombo.currentText)
    }
}
