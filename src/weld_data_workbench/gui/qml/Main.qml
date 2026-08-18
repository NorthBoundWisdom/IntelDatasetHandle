import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "components"

ApplicationWindow {
    id: window
    width: 1480
    height: 900
    minimumWidth: 1120
    minimumHeight: 700
    visible: true
    title: "Demo"

    property color pageColor: "#202226"
    property color panelColor: "#282b30"
    property color textColor: "#f3f5f8"
    property color mutedTextColor: "#b8c0cc"

    palette {
        window: pageColor
        windowText: textColor
        base: panelColor
        alternateBase: "#33373e"
        text: textColor
        button: "#4b5058"
        buttonText: textColor
        brightText: "#ffffff"
        highlight: "#1558d6"
        highlightedText: "#ffffff"
        placeholderText: mutedTextColor
        mid: mutedTextColor
    }

    background: Rectangle { color: window.pageColor }

    property string apiBase: "http://127.0.0.1:8765"
    property int busyCount: 0
    property string statusText: "Connecting to local dataset API…"
    property var stats: ({})
    property var selected: ({})
    property var previews: ({})
    property var categories: []
    property var splits: []
    property int sampleCount: 0

    function argumentValue(prefix, fallbackValue) {
        let args = Qt.application.arguments
        for (let index = 0; index < args.length; ++index) {
            if (args[index].indexOf(prefix) === 0)
                return args[index].substring(prefix.length)
        }
        return fallbackValue
    }

    function request(method, path, onSuccess) {
        let xhr = new XMLHttpRequest()
        busyCount += 1
        xhr.open(method, apiBase + path)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return
            busyCount = Math.max(0, busyCount - 1)
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    onSuccess(JSON.parse(xhr.responseText))
                } catch (error) {
                    showError("Invalid API response: " + error)
                }
            } else {
                showError(method + " " + path + " failed (HTTP " + xhr.status + ")")
            }
        }
        xhr.send()
    }

    function showError(message) {
        statusText = message
        errorLabel.text = message
        errorDialog.open()
    }

    function humanBytes(value) {
        if (value === undefined || value === null)
            return "—"
        let units = ["B", "KB", "MB", "GB", "TB"]
        let size = Number(value)
        let index = 0
        while (size >= 1024 && index < units.length - 1) {
            size /= 1024
            index += 1
        }
        return size.toFixed(index === 0 ? 0 : 1) + " " + units[index]
    }

    function loadStats() {
        request("GET", "/api/stats", function(payload) {
            stats = payload
            categories = Object.keys(payload.by_category || {}).sort()
            splits = Object.keys(payload.by_split || {}).sort()
            statusText = "Connected to " + (payload.total_samples || 0) + " indexed samples"
        })
    }

    function loadSamples() {
        let parameters = ["limit=1000", "sort_by=relpath"]
        if (searchField.text.length)
            parameters.push("q=" + encodeURIComponent(searchField.text))
        if (categoryCombo.currentIndex > 0)
            parameters.push("category=" + encodeURIComponent(categoryCombo.currentText))
        if (splitCombo.currentIndex > 0)
            parameters.push("split=" + encodeURIComponent(splitCombo.currentText))
        if (healthCombo.currentIndex > 0)
            parameters.push("health=" + encodeURIComponent(healthCombo.currentText))

        request("GET", "/api/samples?" + parameters.join("&"), function(payload) {
            samplesModel.clear()
            for (let index = 0; index < payload.items.length; ++index) {
                let item = payload.items[index]
                samplesModel.append({
                    "sampleId": String(item.sample_id || ""),
                    "sessionId": String(item.session_id || ""),
                    "relpath": String(item.relpath || ""),
                    "category": String(item.category || "Unknown"),
                    "split": String(item.split || ""),
                    "healthStatus": String(item.health_status || "unprobed"),
                    "totalBytes": Number(item.total_bytes || 0),
                    "imageCount": Number(item.image_count || 0)
                })
            }
            sampleCount = Number(payload.total || 0)
        })
    }

    function refreshAll() {
        loadStats()
        loadSamples()
    }

    function selectSample(sampleId) {
        videoPlayer.stop()
        audioPlayer.stop()
        request("GET", "/api/samples/" + encodeURIComponent(sampleId), function(payload) {
            selected = payload
            previews = ({})
        })
    }

    function generatePreviews(force) {
        if (!selected.sample_id)
            return
        let path = "/api/samples/" + encodeURIComponent(selected.sample_id) + "/previews"
        if (force)
            path += "?force=true"
        request("POST", path, function(payload) {
            previews = payload.bundle || ({})
            statusText = "Previews ready for " + selected.sample_id
        })
    }

    function openUrl(value) {
        if (value)
            Qt.openUrlExternally(value)
    }

    Component.onCompleted: {
        apiBase = argumentValue("--api-base=", apiBase)
        let smokeValue = Number(argumentValue("--smoke-ms=", "0"))
        if (smokeValue > 0) {
            smokeTimer.interval = smokeValue
            smokeTimer.start()
        }
        refreshAll()
    }

    Timer {
        id: smokeTimer
        repeat: false
        onTriggered: Qt.quit()
    }

    ListModel { id: samplesModel }

    AudioOutput {
        id: videoAudioOutput
        volume: videoVolume.value
    }

    MediaPlayer {
        id: videoPlayer
        source: window.selected.primary_video_url || ""
        audioOutput: videoAudioOutput
        videoOutput: videoOutput
        onErrorOccurred: function(error, errorString) {
            window.statusText = "Video playback error: " + errorString
        }
    }

    AudioOutput {
        id: sampleAudioOutput
        volume: audioVolume.value
    }

    MediaPlayer {
        id: audioPlayer
        source: window.selected.primary_audio_url || ""
        audioOutput: sampleAudioOutput
        onErrorOccurred: function(error, errorString) {
            window.statusText = "Audio playback error: " + errorString
        }
    }

    Dialog {
        id: errorDialog
        title: "Demo"
        modal: true
        standardButtons: Dialog.Ok
        Label {
            id: errorLabel
            width: Math.min(560, implicitWidth)
            wrapMode: Text.WordWrap
        }
    }

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            Image {
                source: Qt.resolvedUrl("assets/demo_icon.png")
                sourceSize: Qt.size(64, 64)
                fillMode: Image.PreserveAspectFit
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
            }
            Label { text: "Demo"; font.pixelSize: 18; font.bold: true }
            Label {
                text: window.apiBase
                color: window.palette.mid
                Layout.fillWidth: true
                elide: Text.ElideMiddle
            }
            Label { text: "Working…"; visible: window.busyCount > 0; color: window.palette.mid }
            Button { text: "Refresh"; onClicked: window.refreshAll() }
        }
    }

    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            Label { text: window.statusText; Layout.fillWidth: true; elide: Text.ElideRight }
            Label { text: window.sampleCount + " matching samples"; color: window.palette.mid }
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
                id: filterScroll
                anchors.fill: parent
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: filterScroll.availableWidth
                    spacing: 10
                    Label { text: "Dataset"; font.bold: true; font.pixelSize: 16 }
                    StatCard {
                        label: "Samples"
                        value: window.stats.total_samples === undefined ? "—" : window.stats.total_samples.toLocaleString()
                        detail: window.stats.total_sessions === undefined ? "" : window.stats.total_sessions + " sessions"
                    }
                    StatCard {
                        label: "Indexed media"
                        value: window.humanBytes(window.stats.total_bytes)
                        detail: window.stats.total_assets === undefined ? "" : window.stats.total_assets + " assets"
                    }
                    StatCard {
                        label: "Issues"
                        value: window.stats.total_issues === undefined ? "—" : window.stats.total_issues.toLocaleString()
                        detail: window.stats.issues_by_severity === undefined ? "" :
                                ((window.stats.issues_by_severity.error || 0) + " errors · " +
                                 (window.stats.issues_by_severity.warning || 0) + " warnings")
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: window.palette.mid }
                    Label { text: "Filters"; font.bold: true; font.pixelSize: 16 }
                    TextField {
                        id: searchField
                        Layout.fillWidth: true
                        placeholderText: "ID, path, category, material…"
                        onAccepted: window.loadSamples()
                    }
                    ComboBox {
                        id: categoryCombo
                        Layout.fillWidth: true
                        model: ["All"].concat(window.categories)
                    }
                    ComboBox {
                        id: splitCombo
                        Layout.fillWidth: true
                        model: ["All"].concat(window.splits)
                    }
                    ComboBox {
                        id: healthCombo
                        Layout.fillWidth: true
                        model: ["All", "ok", "warning", "error", "unprobed"]
                    }
                    Button { text: "Apply filters"; Layout.fillWidth: true; onClicked: window.loadSamples() }
                    Button {
                        text: "Clear"
                        flat: true
                        Layout.fillWidth: true
                        onClicked: {
                            searchField.text = ""
                            categoryCombo.currentIndex = 0
                            splitCombo.currentIndex = 0
                            healthCombo.currentIndex = 0
                            window.loadSamples()
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }

        Pane {
            SplitView.preferredWidth: 410
            SplitView.minimumWidth: 320
            padding: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                Label { text: "Samples"; font.pixelSize: 16; font.bold: true; padding: 12 }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: window.palette.mid }
                ListView {
                    id: sampleList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: samplesModel
                    clip: true
                    currentIndex: -1
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ItemDelegate {
                        required property int index
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
                            window.selectSample(sampleId)
                        }
                        contentItem: RowLayout {
                            spacing: 10
                            Rectangle {
                                Layout.preferredWidth: 8
                                Layout.fillHeight: true
                                radius: 4
                                color: healthStatus === "error" ? "#c84a4a" :
                                       healthStatus === "warning" ? "#d2a33b" : "#4c9f70"
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Label { text: category; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                                Label { text: sampleId; color: window.palette.mid; elide: Text.ElideMiddle; Layout.fillWidth: true }
                                RowLayout {
                                    Label { text: split || "no split"; font.pixelSize: 11 }
                                    Label { text: "·"; color: window.palette.mid }
                                    Label { text: imageCount + " images"; font.pixelSize: 11 }
                                    Label { text: "·"; color: window.palette.mid }
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
            SplitView.minimumWidth: 480
            padding: 0
            EmptyState {
                anchors.fill: parent
                visible: !window.selected.sample_id
                title: "Select a weld sample"
                detail: "The native QML client reads metadata and previews from a loopback-only API."
            }
            ScrollView {
                id: detailScroll
                anchors.fill: parent
                visible: Boolean(window.selected.sample_id)
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: detailScroll.availableWidth
                    spacing: 14
                    Pane {
                        Layout.fillWidth: true
                        ColumnLayout {
                            anchors.fill: parent
                            Label { text: window.selected.category || "Unknown"; font.pixelSize: 24; font.bold: true }
                            Label { text: window.selected.sample_id || ""; color: window.palette.mid }
                            Label { text: window.selected.relpath || ""; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                            GridLayout {
                                columns: 4
                                Layout.fillWidth: true
                                Label { text: "Split"; color: window.palette.mid }
                                Label { text: window.selected.split || "—" }
                                Label { text: "Session"; color: window.palette.mid }
                                Label { text: window.selected.session_id || "—" }
                                Label { text: "Weld type"; color: window.palette.mid }
                                Label { text: window.selected.weld_type || "—" }
                                Label { text: "Steel"; color: window.palette.mid }
                                Label { text: window.selected.steel_type || "—" }
                            }
                            RowLayout {
                                Button { text: "Open video"; enabled: Boolean(window.selected.primary_video_url); onClicked: window.openUrl(window.selected.primary_video_url) }
                                Button { text: "Open audio"; enabled: Boolean(window.selected.primary_audio_url); onClicked: window.openUrl(window.selected.primary_audio_url) }
                                Button { text: "Open sensor CSV"; enabled: Boolean(window.selected.primary_sensor_url); onClicked: window.openUrl(window.selected.primary_sensor_url) }
                                Item { Layout.fillWidth: true }
                                Button { text: window.previews.sample_id ? "Regenerate previews" : "Generate previews"; onClicked: window.generatePreviews(Boolean(window.previews.sample_id)) }
                            }
                        }
                    }

                    Label {
                        text: "Video"
                        visible: Boolean(window.selected.primary_video_url)
                        font.pixelSize: 17
                        font.bold: true
                        leftPadding: 12
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 360 : 0
                        visible: Boolean(window.selected.primary_video_url)
                        color: "black"
                        VideoOutput {
                            id: videoOutput
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                        }
                    }
                    RowLayout {
                        visible: Boolean(window.selected.primary_video_url)
                        Layout.fillWidth: true
                        Button {
                            text: videoPlayer.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                            onClicked: videoPlayer.playbackState === MediaPlayer.PlayingState ? videoPlayer.pause() : videoPlayer.play()
                        }
                        Button { text: "Stop"; onClicked: videoPlayer.stop() }
                        Slider {
                            Layout.fillWidth: true
                            from: 0
                            to: Math.max(videoPlayer.duration, 1)
                            value: videoPlayer.position
                            onMoved: videoPlayer.position = value
                        }
                        Label { text: Math.floor(videoPlayer.position / 1000) + " / " + Math.floor(videoPlayer.duration / 1000) + " s" }
                        Label { text: "Volume" }
                        Slider { id: videoVolume; from: 0; to: 1; value: 0.5; Layout.preferredWidth: 100 }
                    }

                    Label {
                        text: "Audio"
                        visible: Boolean(window.selected.primary_audio_url)
                        font.pixelSize: 17
                        font.bold: true
                        leftPadding: 12
                    }
                    RowLayout {
                        visible: Boolean(window.selected.primary_audio_url)
                        Layout.fillWidth: true
                        Button {
                            text: audioPlayer.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                            onClicked: audioPlayer.playbackState === MediaPlayer.PlayingState ? audioPlayer.pause() : audioPlayer.play()
                        }
                        Button { text: "Stop"; onClicked: audioPlayer.stop() }
                        Slider {
                            Layout.fillWidth: true
                            from: 0
                            to: Math.max(audioPlayer.duration, 1)
                            value: audioPlayer.position
                            onMoved: audioPlayer.position = value
                        }
                        Label { text: Math.floor(audioPlayer.position / 1000) + " / " + Math.floor(audioPlayer.duration / 1000) + " s" }
                        Label { text: "Volume" }
                        Slider { id: audioVolume; from: 0; to: 1; value: 0.7; Layout.preferredWidth: 100 }
                    }

                    Image {
                        source: window.previews.video_contact_sheet_url || ""
                        visible: status === Image.Ready
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        sourceSize.width: 1000
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 360 : 0
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: window.previews.image_thumbnail_urls || []
                            delegate: Image {
                                required property string modelData
                                source: modelData
                                width: 160
                                height: 120
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                MouseArea { anchors.fill: parent; onDoubleClicked: window.openUrl(parent.source) }
                            }
                        }
                    }
                    Label { text: "Audio waveform"; visible: waveform.visible; font.bold: true }
                    Image {
                        id: waveform
                        source: window.previews.audio_waveform_url || ""
                        visible: status === Image.Ready
                        fillMode: Image.PreserveAspectFit
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 240 : 0
                    }
                    Label { text: "Audio spectrogram"; visible: spectrogram.visible; font.bold: true }
                    Image {
                        id: spectrogram
                        source: window.previews.audio_spectrogram_url || ""
                        visible: status === Image.Ready
                        fillMode: Image.PreserveAspectFit
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 300 : 0
                    }
                    Label { text: "Sensor time series"; visible: sensorPlot.visible; font.bold: true }
                    Image {
                        id: sensorPlot
                        source: window.previews.sensor_plot_url || ""
                        visible: status === Image.Ready
                        fillMode: Image.PreserveAspectFit
                        Layout.fillWidth: true
                        Layout.preferredHeight: visible ? 360 : 0
                    }

                    Label { text: "Assets"; font.pixelSize: 17; font.bold: true; leftPadding: 12 }
                    Repeater {
                        model: window.selected.assets || []
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            implicitHeight: assetRow.implicitHeight + 20
                            color: window.palette.alternateBase
                            border.color: window.palette.mid
                            radius: 6
                            RowLayout {
                                id: assetRow
                                anchors.fill: parent
                                anchors.margins: 10
                                AssetPill { text: modelData.kind + " #" + modelData.ordinal; status: modelData.status }
                                Label { text: modelData.relpath; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                Label { text: window.humanBytes(modelData.size_bytes); color: window.palette.mid }
                                Button { text: "Open"; onClicked: window.openUrl(modelData.file_url) }
                            }
                        }
                    }

                    Label { text: "Issues (" + ((window.selected.issues || []).length) + ")"; font.pixelSize: 17; font.bold: true; leftPadding: 12 }
                    EmptyState {
                        visible: (window.selected.issues || []).length === 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: 180
                        title: "No indexed issues"
                        detail: "All configured structural and media probes passed for this sample."
                    }
                    Repeater {
                        model: window.selected.issues || []
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            implicitHeight: issueColumn.implicitHeight + 20
                            color: window.palette.alternateBase
                            border.color: modelData.severity === "error" ? "#c84a4a" : "#d2a33b"
                            radius: 6
                            ColumnLayout {
                                id: issueColumn
                                anchors.fill: parent
                                anchors.margins: 10
                                RowLayout {
                                    IssueBadge { severity: modelData.severity }
                                    Label { text: modelData.code; font.bold: true }
                                }
                                Label { text: modelData.message; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            }
                        }
                    }
                    Item { Layout.preferredHeight: 12 }
                }
            }
        }
    }
}
