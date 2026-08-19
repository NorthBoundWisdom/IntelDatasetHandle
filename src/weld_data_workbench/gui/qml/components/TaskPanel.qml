import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: root

    property var api
    property var tasks: []
    property bool autoRefresh: true
    property string statusText: ""

    function refresh() {
        if (!api)
            return
        api.get("/api/tasks?limit=100", function(payload) {
            root.tasks = payload || []
            root.statusText = root.tasks.length + " recent tasks"
        }, function(status, message) {
            root.statusText = message
        }, true)
    }

    function cancel(taskId) {
        if (!api || !taskId)
            return
        api.post("/api/tasks/" + encodeURIComponent(taskId) + "/cancel", null, function(payload) {
            root.refresh()
        }, null, true)
    }

    Timer {
        interval: 1000
        repeat: true
        running: root.autoRefresh
        onTriggered: root.refresh()
    }

    Component.onCompleted: refresh()

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Background tasks"; font.bold: true; font.pixelSize: 17 }
            Item { Layout.fillWidth: true }
            CheckBox { text: "Auto refresh"; checked: root.autoRefresh; onToggled: root.autoRefresh = checked }
            Button { text: "Refresh"; onClicked: root.refresh() }
        }
        Label { text: root.statusText; color: palette.mid }
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: root.tasks || []
            clip: true
            spacing: 4
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                id: taskRow
                required property var modelData
                width: ListView.view.width
                height: 76
                radius: 6
                color: palette.alternateBase
                border.color: palette.mid
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 10
                    ColumnLayout {
                        Layout.fillWidth: true
                        Label { text: String(taskRow.modelData.kind || "task"); font.bold: true }
                        Label {
                            text: String(taskRow.modelData.state || "") + " · " + String(taskRow.modelData.progress_message || "")
                            color: palette.mid
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0
                            to: Math.max(1, Number(taskRow.modelData.progress_total || 1))
                            value: Number(taskRow.modelData.progress_current || 0)
                        }
                    }
                    Button {
                        text: "Cancel"
                        enabled: ["queued", "running"].indexOf(String(taskRow.modelData.state || "")) >= 0
                        onClicked: root.cancel(String(taskRow.modelData.task_id || ""))
                    }
                }
            }
        }
    }
}
