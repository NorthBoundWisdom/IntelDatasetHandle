import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: root

    property var api
    property var sample: ({})
    property var matches: []
    property var comparison: ({})
    property string statusText: ""

    function loadMatches() {
        matches = []
        comparison = ({})
        if (!api || !sample.sample_id)
            return
        let suffix = "?limit=10&same_split=" + (sameSplit.checked ? "true" : "false")
        api.get("/api/samples/" + encodeURIComponent(sample.sample_id) + "/matches/good" + suffix, function(payload) {
            root.matches = payload || []
            root.statusText = root.matches.length + " matched Good candidates"
            if (root.matches.length)
                root.loadComparison(String(root.matches[0].sample_id || ""))
        }, function(status, message) {
            root.statusText = message
        }, true)
    }

    function loadComparison(sampleId) {
        if (!api || !sampleId.length)
            return
        api.get("/api/samples/" + encodeURIComponent(sampleId), function(payload) {
            root.comparison = payload
        }, function(status, message) {
            root.statusText = message
        }, true)
    }

    function value(record, field) {
        let result = record ? record[field] : undefined
        return result === undefined || result === null || result === "" ? "—" : String(result)
    }

    onSampleChanged: loadMatches()

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Label { text: "Matched Good comparison"; font.bold: true; font.pixelSize: 17 }
            Item { Layout.fillWidth: true }
            CheckBox { id: sameSplit; text: "Same split"; onToggled: root.loadMatches() }
            Button { text: "Refresh matches"; enabled: Boolean(root.sample.sample_id); onClicked: root.loadMatches() }
        }
        Label { text: root.statusText; color: palette.mid }

        ComboBox {
            id: candidateCombo
            Layout.fillWidth: true
            enabled: root.matches.length > 0
            model: root.matches
            textRole: "sample_id"
            onActivated: {
                if (currentIndex >= 0 && currentIndex < root.matches.length)
                    root.loadComparison(String(root.matches[currentIndex].sample_id || ""))
            }
        }

        GridLayout {
            columns: 3
            Layout.fillWidth: true
            columnSpacing: 16
            Label { text: "Parameter"; font.bold: true }
            Label { text: "Selected"; font.bold: true }
            Label { text: "Matched Good"; font.bold: true }

            Repeater {
                model: ["category", "weld_type", "steel_type", "thickness_mm", "current_a", "voltage_v", "gas_bar", "robot_speed_cpm", "session_id", "split"]
                delegate: Item {
                    required property string modelData
                    Layout.columnSpan: 3
                    Layout.fillWidth: true
                    implicitHeight: compareRow.implicitHeight
                    RowLayout {
                        id: compareRow
                        anchors.fill: parent
                        spacing: 16
                        Label { text: modelData; Layout.preferredWidth: 130; color: palette.mid }
                        Label { text: root.value(root.sample, modelData); Layout.fillWidth: true }
                        Label { text: root.value(root.comparison, modelData); Layout.fillWidth: true }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Button {
                text: "Open selected video"
                enabled: Boolean(root.sample.primary_video_url)
                onClicked: Qt.openUrlExternally(root.sample.primary_video_url)
            }
            Button {
                text: "Open matched video"
                enabled: Boolean(root.comparison.primary_video_url)
                onClicked: Qt.openUrlExternally(root.comparison.primary_video_url)
            }
            Item { Layout.fillWidth: true }
        }
        Item { Layout.fillHeight: true }
    }
}
