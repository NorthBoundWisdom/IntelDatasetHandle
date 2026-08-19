import QtQuick

Item {
    id: root
    visible: false
    width: 0
    height: 0

    property var api
    property var task: ({})
    property string taskId: ""
    property bool active: taskId.length > 0
    property string errorText: ""

    signal succeeded(var result)
    signal failed(string message)
    signal cancelled()
    signal changed(var task)

    function track(record) {
        task = record || ({})
        taskId = String(task.task_id || "")
        errorText = ""
        changed(task)
        if (taskId.length)
            pollTimer.start()
    }

    function submit(path, body) {
        if (!api)
            return
        api.post(path, body, function(record) {
            root.track(record)
        }, function(status, message) {
            root.errorText = message
            root.failed(message)
        }, false)
    }

    function refresh() {
        if (!api || !taskId.length)
            return
        api.get("/api/tasks/" + encodeURIComponent(taskId), function(record) {
            root.task = record
            root.changed(record)
            let state = String(record.state || "")
            if (state === "succeeded") {
                let result = record.result || ({})
                pollTimer.stop()
                root.taskId = ""
                root.task = ({})
                root.succeeded(result)
            } else if (state === "failed") {
                let message = String(record.error || "Task failed")
                pollTimer.stop()
                root.taskId = ""
                root.task = ({})
                root.errorText = message
                root.failed(message)
            } else if (state === "cancelled") {
                pollTimer.stop()
                root.taskId = ""
                root.task = ({})
                root.cancelled()
            }
        }, function(status, message) {
            if (status === 404) {
                pollTimer.stop()
                root.taskId = ""
                root.task = ({})
                root.errorText = message
                root.failed(message)
            }
        }, true)
    }

    function cancel() {
        if (!api || !taskId.length)
            return
        api.post("/api/tasks/" + encodeURIComponent(taskId) + "/cancel", null, function(record) {
            root.task = record
            root.changed(record)
        }, null, false)
    }

    Timer {
        id: pollTimer
        interval: 300
        repeat: true
        onTriggered: root.refresh()
    }
}
