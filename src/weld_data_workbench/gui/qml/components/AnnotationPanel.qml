import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: root

    property var api
    property string sampleId: ""
    property var record: ({})
    property string statusText: ""

    function reset() {
        record = ({})
        disposition.currentIndex = disposition.model.indexOf("needs_review")
        note.text = ""
        tags.text = ""
        statusText = ""
    }

    function load() {
        reset()
        if (!api || !sampleId.length)
            return
        api.get("/api/annotations/sample/" + encodeURIComponent(sampleId), function(payload) {
            root.record = payload
            let desired = String(payload.disposition || "needs_review")
            disposition.currentIndex = Math.max(0, disposition.model.indexOf(desired))
            note.text = String(payload.note || "")
            tags.text = (payload.tags || []).join(", ")
            root.statusText = "Revision " + Number(payload.revision || 0)
        }, function(status, message) {
            if (status !== 404)
                root.statusText = message
        }, true)
    }

    function save() {
        if (!api || !sampleId.length)
            return
        let tagList = []
        let raw = tags.text.split(",")
        for (let index = 0; index < raw.length; ++index) {
            let item = raw[index].trim()
            if (item.length)
                tagList.push(item)
        }
        let payload = {
            "target_type": "sample",
            "sample_id": sampleId,
            "disposition": disposition.currentText,
            "note": note.text,
            "tags": tagList
        }
        if (record.revision !== undefined)
            payload.expected_revision = Number(record.revision)
        api.put("/api/annotations", payload, function(result) {
            root.record = result
            root.statusText = "Saved revision " + Number(result.revision || 0)
        }, function(status, message) {
            root.statusText = status === 409 ? "Conflict: reload before saving again" : message
        }, true)
    }

    onSampleIdChanged: load()

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Label { text: "Review annotation"; font.bold: true; font.pixelSize: 16 }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Disposition" }
            ComboBox {
                id: disposition
                Layout.fillWidth: true
                model: ["open", "accepted", "rejected", "resolved", "needs_review", "ignored"]
                currentIndex: 4
            }
        }
        TextField {
            id: tags
            Layout.fillWidth: true
            placeholderText: "tags, comma separated"
        }
        TextArea {
            id: note
            Layout.fillWidth: true
            Layout.preferredHeight: 90
            placeholderText: "Review notes"
            wrapMode: TextEdit.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            Button { text: "Save"; enabled: root.sampleId.length > 0; onClicked: root.save() }
            Button { text: "Reload"; enabled: root.sampleId.length > 0; flat: true; onClicked: root.load() }
            Item { Layout.fillWidth: true }
            Label { text: root.statusText; color: palette.mid; elide: Text.ElideRight }
        }
    }
}
