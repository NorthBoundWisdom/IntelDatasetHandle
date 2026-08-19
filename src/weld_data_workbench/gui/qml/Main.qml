import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: window
    width: 1480
    height: 900
    minimumWidth: 1120
    minimumHeight: 700
    visible: true
    title: "Demo"

    property color pageColor: "#202226"
    property color panelColor: "#282b30"
    property color listPanelColor: "#25282d"
    property color listRowColor: "#353a42"
    property color listRowAlternateColor: "#30353c"
    property color listRowHoverColor: "#4c5868"
    property color listRowSeparatorColor: "#252a31"
    property color textColor: "#f3f5f8"
    property color mutedTextColor: "#b8c0cc"

    property var stats: ({})
    property var samples: []
    property var selected: ({})
    property var previews: ({})
    property var alignment: ({})
    property var categories: []
    property var splits: []
    property int sampleCount: 0
    property int pageOffset: 0
    property int pageLimit: 100
    property var activeFilters: ({"q": "", "category": "", "split": "", "health": ""})
    property string statusText: "Connecting to local dataset API…"

    palette {
        window: pageColor
        windowText: textColor
        base: panelColor
        alternateBase: "#33373e"
        text: textColor
        button: "#4b5058"
        buttonText: textColor
        brightText: "#ffffff"
        highlight: "#1558d6"
        highlightedText: "#ffffff"
        placeholderText: mutedTextColor
        mid: mutedTextColor
    }

    background: Rectangle { color: window.pageColor }

    function argumentValue(prefix, fallbackValue) {
        let args = Qt.application.arguments
        for (let index = 0; index < args.length; ++index) {
            if (args[index].indexOf(prefix) === 0)
                return args[index].substring(prefix.length)
        }
        return fallbackValue
    }

    function filterParameters() {
        let parameters = ["limit=" + pageLimit, "offset=" + pageOffset, "sort_by=relpath"]
        if (activeFilters.q) parameters.push("q=" + encodeURIComponent(activeFilters.q))
        if (activeFilters.category) parameters.push("category=" + encodeURIComponent(activeFilters.category))
        if (activeFilters.split) parameters.push("split=" + encodeURIComponent(activeFilters.split))
        if (activeFilters.health) parameters.push("health=" + encodeURIComponent(activeFilters.health))
        return parameters
    }

    function loadStats() {
        api.get("/api/stats", function(payload) {
            stats = payload
            categories = Object.keys(payload.by_category || {}).sort()
            splits = Object.keys(payload.by_split || {}).sort()
            statusText = "Connected to " + Number(payload.total_samples || 0) + " indexed samples"
        }, null, false)
    }

    function loadSamples() {
        api.get("/api/samples?" + filterParameters().join("&"), function(payload) {
            samples = payload.items || []
            sampleCount = Number(payload.total || 0)
            if (selected.sample_id) {
                let present = false
                for (let index = 0; index < samples.length; ++index) {
                    if (String(samples[index].sample_id || "") === String(selected.sample_id || "")) {
                        present = true
                        break
                    }
                }
                if (!present && pageOffset >= sampleCount) {
                    pageOffset = Math.max(0, Math.floor(Math.max(sampleCount - 1, 0) / pageLimit) * pageLimit)
                    loadSamples()
                }
            }
        }, null, false)
    }

    function refreshAll() {
        loadStats()
        loadSamples()
        taskPanel.refresh()
    }

    function selectSample(sampleId) {
        if (!sampleId.length)
            return
        api.get("/api/samples/" + encodeURIComponent(sampleId), function(payload) {
            selected = payload
            previews = ({})
            alignment = ({})
            detailTab.currentIndex = 0
        }, null, false)
    }

    function applyFilters(queryText, category, split, health) {
        activeFilters = ({"q": queryText, "category": category, "split": split, "health": health})
        pageOffset = 0
        loadSamples()
    }

    function requestPreviews(force) {
        if (!selected.sample_id)
            return
        let suffix = force ? "?force=true" : ""
        previewPoller.submit("/api/tasks/previews/" + encodeURIComponent(selected.sample_id) + suffix, null)
    }

    function requestAlignment() {
        if (!selected.sample_id)
            return
        alignmentPoller.submit("/api/tasks/alignment/" + encodeURIComponent(selected.sample_id), null)
    }

    ApiClient {
        id: api
        onRequestFailed: function(method, path, status, message) {
            window.statusText = message
            errorLabel.text = message
            errorDialog.open()
        }
        onConnectionChanged: function(connected) {
            if (!connected)
                window.statusText = "Dataset API disconnected; retrying…"
        }
    }

    TaskPoller {
        id: previewPoller
        api: api
        onSucceeded: function(result) {
            window.previews = result.bundle || ({})
            window.statusText = "Previews ready for " + String(result.sample_id || window.selected.sample_id || "")
            taskPanel.refresh()
        }
        onFailed: function(message) { window.statusText = message; taskPanel.refresh() }
        onCancelled: function() { window.statusText = "Preview task cancelled"; taskPanel.refresh() }
    }

    TaskPoller {
        id: alignmentPoller
        api: api
        onSucceeded: function(result) {
            window.alignment = result || ({})
            window.statusText = "Alignment ready for " + String(window.selected.sample_id || "")
            taskPanel.refresh()
        }
        onFailed: function(message) { window.statusText = message; taskPanel.refresh() }
        onCancelled: function() { window.statusText = "Alignment task cancelled"; taskPanel.refresh() }
    }

    Timer {
        interval: 2000
        repeat: true
        running: !api.connected
        onTriggered: api.get("/api/health", function(payload) {
            window.statusText = "Reconnected to local dataset API"
            window.refreshAll()
        }, null, true)
    }

    Timer {
        id: smokeTimer
        repeat: false
        onTriggered: Qt.quit()
    }

    Dialog {
        id: errorDialog
        title: "Demo"
        modal: true
        standardButtons: Dialog.Ok
        Label {
            id: errorLabel
            width: Math.min(560, implicitWidth)
            wrapMode: Text.WordWrap
        }
    }

    Component.onCompleted: {
        api.baseUrl = argumentValue("--api-base=", api.baseUrl)
        let smokeValue = Number(argumentValue("--smoke-ms=", "0"))
        if (smokeValue > 0) {
            smokeTimer.interval = smokeValue
            smokeTimer.start()
        }
        refreshAll()
    }

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            Image {
                source: Qt.resolvedUrl("assets/demo_icon.png")
                sourceSize: Qt.size(64, 64)
                fillMode: Image.PreserveAspectFit
                Layout.preferredWidth: 28
                Layout.preferredHeight: 28
            }
            Label { text: "Demo"; font.pixelSize: 18; font.bold: true }
            Label {
                text: api.baseUrl
                color: window.palette.mid
                Layout.fillWidth: true
                elide: Text.ElideMiddle
            }
            Rectangle {
                radius: 6
                implicitWidth: connectionLabel.implicitWidth + 12
                implicitHeight: connectionLabel.implicitHeight + 6
                color: api.connected ? "#2f6e4d" : "#7b4b31"
                Label { id: connectionLabel; anchors.centerIn: parent; text: api.connected ? "Connected" : "Offline"; font.pixelSize: 11 }
            }
            Label { text: "Working…"; visible: api.busyCount > 0; color: window.palette.mid }
            Button { text: "Refresh"; onClicked: window.refreshAll() }
        }
    }

    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            Label { text: window.statusText; Layout.fillWidth: true; elide: Text.ElideRight }
            Label { text: window.sampleCount + " matching samples"; color: window.palette.mid }
        }
    }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        FilterPanel {
            SplitView.preferredWidth: 260
            SplitView.minimumWidth: 220
            padding: 12
            stats: window.stats
            categories: window.categories
            splits: window.splits
            mutedTextColor: window.mutedTextColor
            onFiltersApplied: function(queryText, category, split, health) {
                window.applyFilters(queryText, category, split, health)
            }
        }

        Pane {
            SplitView.preferredWidth: 410
            SplitView.minimumWidth: 320
            padding: 0
            background: Rectangle { color: window.listPanelColor }
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                SampleListPanel {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    items: window.samples
                    selectedSampleId: String(window.selected.sample_id || "")
                    panelColor: window.listPanelColor
                    rowColor: window.listRowColor
                    alternateRowColor: window.listRowAlternateColor
                    hoverColor: window.listRowHoverColor
                    separatorColor: window.listRowSeparatorColor
                    onSampleSelected: function(sampleId) { window.selectSample(sampleId) }
                }
                PaginationBar {
                    Layout.fillWidth: true
                    Layout.margins: 8
                    offset: window.pageOffset
                    limit: window.pageLimit
                    total: window.sampleCount
                    onPreviousRequested: {
                        window.pageOffset = Math.max(0, window.pageOffset - window.pageLimit)
                        window.loadSamples()
                    }
                    onNextRequested: {
                        window.pageOffset += window.pageLimit
                        window.loadSamples()
                    }
                    onPageSizeRequested: function(pageSize) {
                        window.pageLimit = pageSize
                        window.pageOffset = 0
                        window.loadSamples()
                    }
                }
            }
        }

        Pane {
            SplitView.fillWidth: true
            SplitView.minimumWidth: 480
            padding: 12

            EmptyState {
                anchors.fill: parent
                visible: !window.selected.sample_id
                title: "Select a weld sample"
                detail: "Browse, compare, review, align, and analyze indexed multimodal welding data."
            }

            ColumnLayout {
                anchors.fill: parent
                visible: Boolean(window.selected.sample_id)
                spacing: 8

                TabBar {
                    id: detailTab
                    Layout.fillWidth: true
                    TabButton { text: "Inspect" }
                    TabButton { text: "Compare" }
                    TabButton { text: "Analytics" }
                    TabButton { text: "Tasks" }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: detailTab.currentIndex

                    DetailPanel {
                        api: api
                        sample: window.selected
                        previews: window.previews
                        alignment: window.alignment
                        previewTask: previewPoller.task
                        alignmentTask: alignmentPoller.task
                        statusText: window.statusText
                        onPreviewRequested: function(force) { window.requestPreviews(force) }
                        onAlignmentRequested: window.requestAlignment()
                    }
                    ComparePanel { api: api; sample: window.selected }
                    AnalyticsPanel { api: api; filters: window.activeFilters }
                    TaskPanel { id: taskPanel; api: api }
                }
            }
        }
    }
}
