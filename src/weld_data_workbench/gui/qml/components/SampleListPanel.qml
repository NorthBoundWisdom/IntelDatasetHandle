import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: root

    property var items: []
    property string selectedSampleId: ""
    property color panelColor: "#25282d"
    property color rowColor: "#353a42"
    property color alternateRowColor: "#30353c"
    property color hoverColor: "#4c5868"
    property color separatorColor: "#252a31"

    signal sampleSelected(string sampleId)

    padding: 0
    background: Rectangle { color: root.panelColor }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Label { text: "Samples"; font.pixelSize: 16; font.bold: true; padding: 12 }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: palette.mid }

        ListView {
            id: sampleList
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: root.items || []
            clip: true
            spacing: 1
            ScrollBar.vertical: ScrollBar {}

            delegate: ItemDelegate {
                id: sampleDelegate
                required property var modelData
                required property int index
                width: sampleList.width
                height: 88
                hoverEnabled: true
                highlighted: String(modelData.sample_id || "") === root.selectedSampleId

                background: Rectangle {
                    color: sampleDelegate.highlighted ? palette.highlight :
                           sampleDelegate.hovered ? root.hoverColor :
                           (sampleDelegate.index % 2 === 0 ? root.rowColor : root.alternateRowColor)
                    border.color: sampleDelegate.hovered && !sampleDelegate.highlighted ? "#86b5f2" : "transparent"
                    border.width: sampleDelegate.hovered && !sampleDelegate.highlighted ? 1 : 0
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: root.separatorColor
                        visible: !sampleDelegate.highlighted && !sampleDelegate.hovered
                    }
                }

                onClicked: root.sampleSelected(String(modelData.sample_id || ""))

                contentItem: RowLayout {
                    spacing: 10
                    Rectangle {
                        Layout.preferredWidth: 8
                        Layout.fillHeight: true
                        radius: 4
                        color: String(sampleDelegate.modelData.health_status || "") === "error" ? "#c84a4a" :
                               String(sampleDelegate.modelData.health_status || "") === "warning" ? "#d2a33b" : "#4c9f70"
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label {
                            text: String(sampleDelegate.modelData.category || "Unknown")
                            font.bold: true
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: String(sampleDelegate.modelData.sample_id || "")
                            color: palette.mid
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                        RowLayout {
                            Label { text: String(sampleDelegate.modelData.split || "no split"); font.pixelSize: 11 }
                            Label { text: "·"; color: palette.mid }
                            Label { text: Number(sampleDelegate.modelData.image_count || 0) + " images"; font.pixelSize: 11 }
                            Label { text: "·"; color: palette.mid }
                            Label { text: (Number(sampleDelegate.modelData.total_bytes || 0) / 1048576).toFixed(1) + " MiB"; font.pixelSize: 11 }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }
        }
    }
}
