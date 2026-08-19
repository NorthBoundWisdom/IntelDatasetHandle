import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: root

    property var stats: ({})
    property var categories: []
    property var splits: []
    property color mutedTextColor: "#b8c0cc"

    signal filtersApplied(string queryText, string category, string split, string health)

    function clearFilters() {
        searchField.text = ""
        categoryCombo.currentIndex = 0
        splitCombo.currentIndex = 0
        healthCombo.currentIndex = 0
        filtersApplied("", "", "", "")
    }

    ScrollView {
        id: filterScroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: filterScroll.availableWidth
            spacing: 10

            Label { text: "Dataset"; font.bold: true; font.pixelSize: 16 }
            StatCard {
                label: "Samples"
                value: root.stats.total_samples === undefined ? "—" : root.stats.total_samples.toLocaleString()
                detail: root.stats.total_sessions === undefined ? "" : root.stats.total_sessions + " sessions"
            }
            StatCard {
                label: "Indexed media"
                value: root.stats.total_assets === undefined ? "—" : root.stats.total_assets.toLocaleString()
                detail: root.stats.total_bytes === undefined ? "" : (Number(root.stats.total_bytes) / 1073741824).toFixed(1) + " GiB"
            }
            StatCard {
                label: "Issues"
                value: root.stats.total_issues === undefined ? "—" : root.stats.total_issues.toLocaleString()
                detail: root.stats.issues_by_severity === undefined ? "" :
                        ((root.stats.issues_by_severity.error || 0) + " errors · " +
                         (root.stats.issues_by_severity.warning || 0) + " warnings")
            }

            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: root.mutedTextColor }
            Label { text: "Filters"; font.bold: true; font.pixelSize: 16 }
            TextField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: "ID, path, category, material…"
                onAccepted: applyButton.clicked()
            }
            ComboBox {
                id: categoryCombo
                Layout.fillWidth: true
                model: ["All"].concat(root.categories || [])
            }
            ComboBox {
                id: splitCombo
                Layout.fillWidth: true
                model: ["All"].concat(root.splits || [])
            }
            ComboBox {
                id: healthCombo
                Layout.fillWidth: true
                model: ["All", "ok", "warning", "error", "unprobed"]
            }
            Button {
                id: applyButton
                text: "Apply filters"
                Layout.fillWidth: true
                onClicked: root.filtersApplied(
                    searchField.text,
                    categoryCombo.currentIndex > 0 ? categoryCombo.currentText : "",
                    splitCombo.currentIndex > 0 ? splitCombo.currentText : "",
                    healthCombo.currentIndex > 0 ? healthCombo.currentText : ""
                )
            }
            Button {
                text: "Clear"
                flat: true
                Layout.fillWidth: true
                onClicked: root.clearFilters()
            }
            Item { Layout.fillHeight: true }
        }
    }
}
