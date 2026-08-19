import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: root

    property int offset: 0
    property int limit: 100
    property int total: 0
    readonly property int page: total === 0 ? 0 : Math.floor(offset / Math.max(limit, 1)) + 1
    readonly property int pages: total === 0 ? 0 : Math.ceil(total / Math.max(limit, 1))

    signal previousRequested()
    signal nextRequested()
    signal pageSizeRequested(int pageSize)

    Button {
        text: "Previous"
        enabled: root.offset > 0
        onClicked: root.previousRequested()
    }
    Label {
        text: root.total === 0 ? "0 results" : "Page " + root.page + " / " + root.pages
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignHCenter
    }
    ComboBox {
        id: pageSize
        model: [50, 100, 250, 500, 1000]
        currentIndex: Math.max(0, model.indexOf(root.limit))
        onActivated: root.pageSizeRequested(Number(currentText))
        ToolTip.visible: hovered
        ToolTip.text: "Samples per page"
    }
    Button {
        text: "Next"
        enabled: root.offset + root.limit < root.total
        onClicked: root.nextRequested()
    }
}
