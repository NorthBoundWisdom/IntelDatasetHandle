import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: root

    property var api
    property var filters: ({})
    property var distribution: ({})
    property var pivot: ({})
    property string statusText: ""

    readonly property var distributionFields: [
        "category", "split", "weld_type", "steel_type", "thickness_mm",
        "session_id", "health_status", "current_a", "voltage_v", "gas_bar",
        "robot_speed_cpm", "total_bytes", "image_count"
    ]
    readonly property var pivotDimensions: [
        "category", "split", "weld_type", "steel_type", "thickness_mm", "session_id", "health_status"
    ]

    function filterQuery() {
        let parts = []
        if (filters.q) parts.push("q=" + encodeURIComponent(filters.q))
        if (filters.category) parts.push("category=" + encodeURIComponent(filters.category))
        if (filters.split) parts.push("split=" + encodeURIComponent(filters.split))
        if (filters.health) parts.push("health=" + encodeURIComponent(filters.health))
        return parts.length ? "&" + parts.join("&") : ""
    }

    function loadDistribution() {
        if (!api)
            return
        let field = distributionField.currentText
        api.get("/api/analytics/distribution?field=" + encodeURIComponent(field) + "&bins=20" + filterQuery(), function(payload) {
            root.distribution = payload
            root.statusText = "Distribution over " + Number(payload.sample_count || 0) + " samples"
        }, function(status, message) {
            root.statusText = message
        }, true)
    }

    function loadPivot() {
        if (!api)
            return
        let filterPayload = ({})
        if (filters.q) filterPayload.q = filters.q
        if (filters.category) filterPayload.category = filters.category
        if (filters.split) filterPayload.split = filters.split
        if (filters.health) filterPayload.health = filters.health
        let payload = {
            "row": pivotRow.currentText,
            "column": pivotColumn.currentIndex === 0 ? null : pivotColumn.currentText,
            "measure": "count",
            "filters": filterPayload,
            "limit": 5000
        }
        api.post("/api/analytics/pivot", payload, function(result) {
            root.pivot = result
            root.statusText = "Pivot returned " + Number((result.records || []).length) + " groups"
        }, function(status, message) {
            root.statusText = message
        }, true)
    }

    function distributionRows() {
        if (!distribution)
            return []
        if (distribution.kind === "numeric")
            return distribution.bins || []
        return distribution.items || []
    }

    function rowLabel(item) {
        if (distribution.kind === "numeric")
            return Number(item.left || 0).toFixed(2) + "–" + Number(item.right || 0).toFixed(2)
        return String(item.label || "Unknown")
    }

    function maxDistributionCount() {
        let rows = distributionRows()
        let result = 1
        for (let index = 0; index < rows.length; ++index)
            result = Math.max(result, Number(rows[index].count || 0))
        return result
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        Label { text: "Dataset analytics"; font.bold: true; font.pixelSize: 17 }
        RowLayout {
            Layout.fillWidth: true
            ComboBox { id: distributionField; Layout.fillWidth: true; model: root.distributionFields }
            Button { text: "Distribution"; onClicked: root.loadDistribution() }
        }
        ListView {
            Layout.fillWidth: true
            Layout.preferredHeight: 260
            clip: true
            model: root.distributionRows()
            ScrollBar.vertical: ScrollBar {}
            delegate: RowLayout {
                required property var modelData
                width: ListView.view.width
                spacing: 8
                Label { text: root.rowLabel(modelData); Layout.preferredWidth: 150; elide: Text.ElideRight }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 14
                    radius: 3
                    color: "#1d2024"
                    Rectangle {
                        width: parent.width * Number(modelData.count || 0) / root.maxDistributionCount()
                        height: parent.height
                        radius: 3
                        color: "#2b78d4"
                    }
                }
                Label { text: Number(modelData.count || 0); Layout.preferredWidth: 60; horizontalAlignment: Text.AlignRight }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: palette.mid }
        Label { text: "Pivot"; font.bold: true }
        RowLayout {
            Layout.fillWidth: true
            ComboBox { id: pivotRow; Layout.fillWidth: true; model: root.pivotDimensions }
            ComboBox { id: pivotColumn; Layout.fillWidth: true; model: ["None"].concat(root.pivotDimensions) }
            Button { text: "Run pivot"; onClicked: root.loadPivot() }
        }
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.pivot.records || []
            ScrollBar.vertical: ScrollBar {}
            delegate: Label {
                required property var modelData
                width: ListView.view.width
                text: JSON.stringify(modelData)
                elide: Text.ElideRight
                font.family: "monospace"
                font.pixelSize: 11
            }
        }
        Label { text: root.statusText; color: palette.mid; Layout.fillWidth: true; elide: Text.ElideRight }
    }
}
