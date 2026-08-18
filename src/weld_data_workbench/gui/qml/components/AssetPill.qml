import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    property string text: "asset"
    property string status: "ok"
    radius: height / 2
    implicitHeight: 28
    implicitWidth: label.implicitWidth + 22
    color: status === "error" ? "#5b2525" : status === "warning" ? "#5a481f" : "#24384c"
    border.color: status === "error" ? "#e07070" : status === "warning" ? "#d9ae53" : "#6fa8dc"

    Label {
        id: label
        anchors.centerIn: parent
        text: root.text
        font.pixelSize: 11
    }
}
