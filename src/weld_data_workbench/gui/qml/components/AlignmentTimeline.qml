import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: root

    property var alignment: ({})
    property real cursorSeconds: 0
    property real timelineSeconds: _timelineSeconds()
    property bool interactive: Boolean(alignment && alignment.schema_version)

    signal seekRequested(real referenceSeconds)

    function _estimate(modality) {
        if (!alignment || !alignment.estimates)
            return ({})
        return alignment.estimates[modality] || ({})
    }

    function _timelineSeconds() {
        let result = 1.0
        let modalities = ["sensor", "audio", "video"]
        for (let index = 0; index < modalities.length; ++index) {
            let estimate = _estimate(modalities[index])
            let endValue = Number(estimate.end_s)
            if (isFinite(endValue) && endValue > result)
                result = endValue
        }
        return result
    }

    function _qualityColor(value) {
        if (value === "good") return "#4c9f70"
        if (value === "warning") return "#d2a33b"
        if (value === "poor") return "#c84a4a"
        return "#7d8794"
    }

    function _diagnostics(estimate) {
        let details = estimate && estimate.details ? estimate.details : ({})
        let labels = []
        if (details.end_censored)
            labels.push("censored")
        if (details.analysis_window_truncated)
            labels.push("window-truncated")
        if (details.time_gap_detected) {
            let gap = Number(details.max_time_gap_s || 0)
            labels.push("time-gap " + gap.toFixed(2) + "s")
        }
        return labels.join(" · ")
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            Label { text: "Alignment"; font.bold: true; font.pixelSize: 16 }
            Rectangle {
                visible: root.interactive
                radius: 8
                implicitWidth: qualityLabel.implicitWidth + 14
                implicitHeight: qualityLabel.implicitHeight + 6
                color: root._qualityColor(String(root.alignment.quality || "unknown"))
                Label {
                    id: qualityLabel
                    anchors.centerIn: parent
                    text: String(root.alignment.quality || "unknown")
                    font.pixelSize: 11
                }
            }
            Item { Layout.fillWidth: true }
            Label {
                visible: root.interactive
                text: "start spread " + Number(root.alignment.start_spread_s || 0).toFixed(3) + " s"
                color: palette.mid
            }
        }

        Label {
            visible: !root.interactive
            text: "Run alignment to inspect synchronized modality intervals."
            color: palette.mid
        }

        Repeater {
            model: root.interactive ? ["sensor", "audio", "video"] : []
            delegate: RowLayout {
                id: row
                required property string modelData
                property var estimate: root._estimate(modelData)
                Layout.fillWidth: true
                spacing: 8

                Label {
                    text: row.modelData
                    Layout.preferredWidth: 54
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 18
                    radius: 4
                    color: "#1d2024"
                    border.color: palette.mid
                    clip: true

                    Rectangle {
                        x: Math.max(0, Number(row.estimate.onset_s || 0) / root.timelineSeconds * parent.width)
                        width: Math.max(2, (Number(row.estimate.end_s || row.estimate.onset_s || 0) - Number(row.estimate.onset_s || 0)) / root.timelineSeconds * parent.width)
                        height: parent.height
                        color: row.estimate.error ? "#7d8794" : "#2b78d4"
                        opacity: 0.75
                    }
                    Row {
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        spacing: 1
                        Rectangle {
                            visible: Boolean(row.estimate.details && row.estimate.details.time_gap_detected)
                            width: visible ? 5 : 0
                            height: parent.height
                            color: "#c84a4a"
                        }
                        Rectangle {
                            visible: Boolean(row.estimate.details && row.estimate.details.analysis_window_truncated)
                            width: visible ? 5 : 0
                            height: parent.height
                            color: "#dd7b39"
                        }
                        Rectangle {
                            visible: Boolean(row.estimate.details && row.estimate.details.end_censored)
                            width: visible ? 5 : 0
                            height: parent.height
                            color: "#d2a33b"
                        }
                    }
                }
                Label {
                    Layout.preferredWidth: 260
                    text: row.estimate.error ? String(row.estimate.error) :
                          ("offset " + Number((root.alignment.offsets_s || ({}))[row.modelData] || 0).toFixed(3) + " s" +
                           (root._diagnostics(row.estimate).length ? " · " + root._diagnostics(row.estimate) : ""))
                    elide: Text.ElideRight
                    color: palette.mid
                    font.pixelSize: 11
                }
            }
        }

        Slider {
            id: masterSlider
            visible: root.interactive
            Layout.fillWidth: true
            from: 0
            to: Math.max(root.timelineSeconds, 0.001)
            value: Math.max(from, Math.min(to, root.cursorSeconds))
            onMoved: root.seekRequested(value)
        }
        Label {
            visible: root.interactive
            text: Number(root.cursorSeconds || 0).toFixed(2) + " s reference cursor"
            color: palette.mid
            font.pixelSize: 11
        }
    }
}
