import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    property string title: "Nothing selected"
    property string detail: "Choose an item to inspect it."

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 8
        Label {
            text: parent.parent.title
            font.pixelSize: 22
            font.bold: true
            Layout.alignment: Qt.AlignHCenter
        }
        Label {
            text: parent.parent.detail
            color: palette.mid
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.maximumWidth: 420
        }
    }
}
