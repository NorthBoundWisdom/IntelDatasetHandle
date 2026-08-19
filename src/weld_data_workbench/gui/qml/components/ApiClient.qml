import QtQuick

QtObject {
    id: root

    property string baseUrl: "http://127.0.0.1:8765"
    property int busyCount: 0
    property bool connected: false
    property string lastError: ""

    signal requestFailed(string method, string path, int status, string message)
    signal connectionChanged(bool connected)

    function _setConnected(value) {
        if (connected === value)
            return
        connected = value
        connectionChanged(value)
    }

    function _message(xhr, method, path) {
        let detail = ""
        try {
            let payload = JSON.parse(xhr.responseText || "{}")
            if (payload.detail !== undefined)
                detail = String(payload.detail)
        } catch (error) {
            detail = ""
        }
        if (!detail)
            detail = method + " " + path + " failed (HTTP " + xhr.status + ")"
        return detail
    }

    function request(method, path, body, onSuccess, onFailure, silent) {
        let xhr = new XMLHttpRequest()
        busyCount += 1
        xhr.open(method, baseUrl + path)
        if (body !== null && body !== undefined)
            xhr.setRequestHeader("Content-Type", "application/json")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return
            busyCount = Math.max(0, busyCount - 1)
            if (xhr.status >= 200 && xhr.status < 300) {
                root._setConnected(true)
                root.lastError = ""
                let payload = ({})
                if (xhr.responseText && xhr.responseText.length) {
                    try {
                        payload = JSON.parse(xhr.responseText)
                    } catch (error) {
                        let message = "Invalid API response from " + path + ": " + error
                        root.lastError = message
                        if (onFailure)
                            onFailure(xhr.status, message)
                        if (!silent)
                            root.requestFailed(method, path, xhr.status, message)
                        return
                    }
                }
                if (onSuccess)
                    onSuccess(payload)
                return
            }

            if (xhr.status === 0)
                root._setConnected(false)
            let message = root._message(xhr, method, path)
            root.lastError = message
            if (onFailure)
                onFailure(xhr.status, message)
            if (!silent)
                root.requestFailed(method, path, xhr.status, message)
        }
        xhr.onerror = function() {
            root._setConnected(false)
        }
        xhr.send(body === null || body === undefined ? null : JSON.stringify(body))
    }

    function get(path, onSuccess, onFailure, silent) {
        request("GET", path, null, onSuccess, onFailure, Boolean(silent))
    }

    function post(path, body, onSuccess, onFailure, silent) {
        request("POST", path, body, onSuccess, onFailure, Boolean(silent))
    }

    function put(path, body, onSuccess, onFailure, silent) {
        request("PUT", path, body, onSuccess, onFailure, Boolean(silent))
    }
}
