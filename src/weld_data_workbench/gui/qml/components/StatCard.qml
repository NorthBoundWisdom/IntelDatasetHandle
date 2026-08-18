import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property string label: ""
    property string value: "—"
    property string detail: ""
    radius: 8
    color: palette.alternateBase
    border.color: palette.mid
    implicitHeight: 78
    Layout.fillWidth: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 2
        Label {
            text: root.label
            color: palette.mid
            font.pixelSize: 11
        }
        Label {
            text: root.value
            font.pixelSize: 22
            font.bold: true
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Label {
            text: root.detail
            visible: text.length > 0
            color: palette.mid
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }
}
