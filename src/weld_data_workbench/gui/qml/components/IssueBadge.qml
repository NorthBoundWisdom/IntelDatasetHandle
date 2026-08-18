import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    property string severity: "info"
    property string text: severity.toUpperCase()
    radius: 4
    implicitHeight: 22
    implicitWidth: label.implicitWidth + 14
    color: severity === "error" ? "#6d2525" : severity === "warning" ? "#6b541d" : "#254b6d"

    Label {
        id: label
        anchors.centerIn: parent
        text: root.text
        font.pixelSize: 10
        font.bold: true
    }
}
