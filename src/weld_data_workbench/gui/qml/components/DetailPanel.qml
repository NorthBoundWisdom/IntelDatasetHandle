import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Pane {
    id: root

    property var api
    property var sample: ({})
    property var previews: ({})
    property var alignment: ({})
    property var previewTask: ({})
    property var alignmentTask: ({})
    property string statusText: ""

    signal previewRequested(bool force)
    signal alignmentRequested()

    function openUrl(value) {
        if (value)
            Qt.openUrlExternally(value)
    }

    function setIssueDisposition(issue, disposition) {
        if (!api || !sample.sample_id)
            return
        api.put("/api/annotations", {
            "target_type": "issue",
            "sample_id": String(sample.sample_id),
            "code": String(issue.code || ""),
            "relpath": issue.relpath === undefined ? null : issue.relpath,
            "message": issue.message === undefined ? null : issue.message,
            "disposition": disposition,
            "note": "Reviewed from QML workbench",
            "tags": []
        }, function(result) {
            root.statusText = "Issue " + String(issue.code || "") + " marked " + disposition
        }, function(status, message) {
            root.statusText = message
        }, true)
    }

    function alignmentOffset(modality) {
        if (!alignment || !alignment.offsets_s)
            return 0
        let value = Number(alignment.offsets_s[modality])
        return isFinite(value) ? value : 0
    }

    function seekReference(referenceSeconds) {
        if (sample.primary_video_url) {
            let videoSeconds = referenceSeconds + alignmentOffset("video")
            videoPlayer.position = Math.max(0, Math.min(videoPlayer.duration, videoSeconds * 1000))
        }
        if (sample.primary_audio_url) {
            let audioSeconds = referenceSeconds + alignmentOffset("audio")
            audioPlayer.position = Math.max(0, Math.min(audioPlayer.duration, audioSeconds * 1000))
        }
        timeline.cursorSeconds = referenceSeconds
    }

    function currentReferenceSeconds() {
        let reference = String(alignment.reference_modality || "")
        if (reference === "video" && videoPlayer.duration > 0)
            return videoPlayer.position / 1000
        if (reference === "audio" && audioPlayer.duration > 0)
            return audioPlayer.position / 1000
        if (videoPlayer.playbackState === MediaPlayer.PlayingState)
            return videoPlayer.position / 1000 - alignmentOffset("video")
        if (audioPlayer.playbackState === MediaPlayer.PlayingState)
            return audioPlayer.position / 1000 - alignmentOffset("audio")
        if (videoPlayer.duration > 0)
            return videoPlayer.position / 1000 - alignmentOffset("video")
        if (audioPlayer.duration > 0)
            return audioPlayer.position / 1000 - alignmentOffset("audio")
        return timeline.cursorSeconds
    }

    onSampleChanged: {
        videoPlayer.stop()
        audioPlayer.stop()
        timeline.cursorSeconds = 0
    }

    AudioOutput {
        id: videoAudioOutput
        volume: videoVolume.value
    }

    MediaPlayer {
        id: videoPlayer
        source: root.sample.primary_video_url || ""
        audioOutput: videoAudioOutput
        videoOutput: videoOutput
        onErrorOccurred: function(error, errorString) {
            root.statusText = "Video playback error: " + errorString
        }
    }

    AudioOutput {
        id: sampleAudioOutput
        volume: audioVolume.value
    }

    MediaPlayer {
        id: audioPlayer
        source: root.sample.primary_audio_url || ""
        audioOutput: sampleAudioOutput
        onErrorOccurred: function(error, errorString) {
            root.statusText = "Audio playback error: " + errorString
        }
    }

    Timer {
        interval: 100
        repeat: true
        running: videoPlayer.playbackState === MediaPlayer.PlayingState || audioPlayer.playbackState === MediaPlayer.PlayingState
        onTriggered: timeline.cursorSeconds = Math.max(0, root.currentReferenceSeconds())
    }

    ScrollView {
        id: detailScroll
        anchors.fill: parent
        clip: true
        property int scrollbarGutter: detailVerticalScrollBar.width + 8
        contentWidth: Math.max(0, availableWidth - scrollbarGutter)
        ScrollBar.vertical: ScrollBar {
            id: detailVerticalScrollBar
            width: 12
            anchors.top: detailScroll.top
            anchors.right: detailScroll.right
            anchors.bottom: detailScroll.bottom
            z: 2
            policy: ScrollBar.AlwaysOn
        }

        ColumnLayout {
            width: detailScroll.contentWidth
            spacing: 14

            Pane {
                Layout.fillWidth: true
                ColumnLayout {
                    anchors.fill: parent
                    Label { text: root.sample.category || "Unknown"; font.pixelSize: 24; font.bold: true }
                    Label { text: root.sample.sample_id || ""; color: palette.mid }
                    Label { text: root.sample.relpath || ""; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                    GridLayout {
                        columns: 4
                        Layout.fillWidth: true
                        Label { text: "Split"; color: palette.mid }
                        Label { text: root.sample.split || "—" }
                        Label { text: "Session"; color: palette.mid }
                        Label { text: root.sample.session_id || "—" }
                        Label { text: "Weld type"; color: palette.mid }
                        Label { text: root.sample.weld_type || "—" }
                        Label { text: "Steel"; color: palette.mid }
                        Label { text: root.sample.steel_type || "—" }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Button { text: "Open video"; enabled: Boolean(root.sample.primary_video_url); onClicked: root.openUrl(root.sample.primary_video_url) }
                        Button { text: "Open audio"; enabled: Boolean(root.sample.primary_audio_url); onClicked: root.openUrl(root.sample.primary_audio_url) }
                        Button { text: "Open sensor CSV"; enabled: Boolean(root.sample.primary_sensor_url); onClicked: root.openUrl(root.sample.primary_sensor_url) }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: root.previewTask.task_id ? "Preview queued…" : (root.previews.sample_id ? "Regenerate previews" : "Generate previews")
                            enabled: !root.previewTask.task_id
                            onClicked: root.previewRequested(Boolean(root.previews.sample_id))
                        }
                        Button {
                            text: root.alignmentTask.task_id ? "Aligning…" : (root.alignment.schema_version ? "Re-run alignment" : "Run alignment")
                            enabled: !root.alignmentTask.task_id
                            onClicked: root.alignmentRequested()
                        }
                    }
                }
            }

            AlignmentTimeline {
                id: timeline
                Layout.fillWidth: true
                alignment: root.alignment
                onSeekRequested: function(referenceSeconds) { root.seekReference(referenceSeconds) }
            }

            Label {
                text: "Video"
                visible: Boolean(root.sample.primary_video_url)
                font.pixelSize: 17
                font.bold: true
                leftPadding: 12
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? 360 : 0
                visible: Boolean(root.sample.primary_video_url)
                color: "black"
                VideoOutput {
                    id: videoOutput
                    anchors.fill: parent
                    fillMode: VideoOutput.PreserveAspectFit
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: Boolean(root.sample.primary_video_url)
                    acceptedButtons: Qt.LeftButton
                    onDoubleClicked: {
                        if (videoPlayer.playbackState === MediaPlayer.PlayingState)
                            videoPlayer.pause()
                        else
                            videoPlayer.play()
                    }
                }
            }
            RowLayout {
                visible: Boolean(root.sample.primary_video_url)
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
                    onMoved: {
                        videoPlayer.position = value
                        timeline.cursorSeconds = Math.max(0, value / 1000 - root.alignmentOffset("video"))
                    }
                }
                Label { text: Math.floor(videoPlayer.position / 1000) + " / " + Math.floor(videoPlayer.duration / 1000) + " s" }
                Label { text: "Volume" }
                Slider { id: videoVolume; from: 0; to: 1; value: 0.5; Layout.preferredWidth: 100 }
            }

            Label {
                text: "Audio"
                visible: Boolean(root.sample.primary_audio_url)
                font.pixelSize: 17
                font.bold: true
                leftPadding: 12
            }
            RowLayout {
                visible: Boolean(root.sample.primary_audio_url)
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
                    onMoved: {
                        audioPlayer.position = value
                        timeline.cursorSeconds = Math.max(0, value / 1000 - root.alignmentOffset("audio"))
                    }
                }
                Label { text: Math.floor(audioPlayer.position / 1000) + " / " + Math.floor(audioPlayer.duration / 1000) + " s" }
                Label { text: "Volume" }
                Slider { id: audioVolume; from: 0; to: 1; value: 0.7; Layout.preferredWidth: 100 }
            }

            Image {
                source: root.previews.video_contact_sheet_url || ""
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
                    model: root.previews.image_thumbnail_urls || []
                    delegate: Image {
                        required property string modelData
                        source: modelData
                        width: 160
                        height: 120
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        MouseArea { anchors.fill: parent; onDoubleClicked: root.openUrl(parent.source) }
                    }
                }
            }
            Label { text: "Audio waveform"; visible: waveform.visible; font.bold: true }
            Image {
                id: waveform
                source: root.previews.audio_waveform_url || ""
                visible: status === Image.Ready
                fillMode: Image.PreserveAspectFit
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? 240 : 0
            }
            Label { text: "Audio spectrogram"; visible: spectrogram.visible; font.bold: true }
            Image {
                id: spectrogram
                source: root.previews.audio_spectrogram_url || ""
                visible: status === Image.Ready
                fillMode: Image.PreserveAspectFit
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? 300 : 0
            }
            Label { text: "Sensor time series"; visible: sensorPlot.visible; font.bold: true }
            Image {
                id: sensorPlot
                source: root.previews.sensor_plot_url || ""
                visible: status === Image.Ready
                fillMode: Image.PreserveAspectFit
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? 360 : 0
            }

            AnnotationPanel {
                Layout.fillWidth: true
                api: root.api
                sampleId: String(root.sample.sample_id || "")
            }

            Label { text: "Assets"; font.pixelSize: 17; font.bold: true; leftPadding: 12 }
            Repeater {
                model: root.sample.assets || []
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: assetRow.implicitHeight + 20
                    color: palette.alternateBase
                    border.color: palette.mid
                    radius: 6
                    RowLayout {
                        id: assetRow
                        anchors.fill: parent
                        anchors.margins: 10
                        AssetPill { kind: String(modelData.kind || "asset") }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Label { text: String(modelData.relpath || ""); Layout.fillWidth: true; elide: Text.ElideMiddle }
                            Label { text: String(modelData.status || "") + " · " + (Number(modelData.size_bytes || 0) / 1048576).toFixed(1) + " MiB"; color: palette.mid; font.pixelSize: 11 }
                        }
                        Button { text: "Open"; enabled: Boolean(modelData.file_url); onClicked: root.openUrl(modelData.file_url) }
                    }
                }
            }

            Label { text: "Issues"; visible: (root.sample.issues || []).length > 0; font.pixelSize: 17; font.bold: true; leftPadding: 12 }
            Repeater {
                model: root.sample.issues || []
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    IssueBadge { severity: String(modelData.severity || "info") }
                    Label { text: String(modelData.code || "issue"); font.bold: true }
                    Label { text: String(modelData.message || ""); Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    Button { text: "Ignore"; onClicked: root.setIssueDisposition(modelData, "ignored") }
                    Button { text: "Resolve"; onClicked: root.setIssueDisposition(modelData, "resolved") }
                }
            }

            Label { text: root.statusText; color: palette.mid; Layout.fillWidth: true; wrapMode: Text.WordWrap }
        }
    }
}
