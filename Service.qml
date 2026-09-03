import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "Model.js" as Model

Item {
  id: root

  property var settings: ({})

  property bool installed: false
  property bool serviceExists: false
  property bool running: false
  property bool mounted: false
  property bool authenticated: false
  property bool rcAvailable: false

  property int _desired: -1
  readonly property bool active: _desired === -1 ? running : (_desired === 1)
  property bool refreshing: false
  property string statusText: "Checking…"
  property string remoteName: stringSetting("remoteName", "onedrive")
  property string mountPoint: stringSetting("mountPoint", "~/OneDrive")
  property string mountPointExpanded: expandHome(mountPoint)
  property string serviceUnit: stringSetting("serviceUnit", "rclone-onedrive.service")
  property string rcAddr: stringSetting("rcAddr", "127.0.0.1:5572")
  property double lastSyncTs: 0
  property var pendingFiles: []
  property int pendingCount: 0
  property double bytesQueued: 0
  property double transferredBytes: 0
  property int errorCount: 0
  property var errors: []
  property string actionStatus: ""
  property string lastError: ""

  readonly property int refreshIntervalSec: intSetting("refreshIntervalSec", 30, 5, 3600)
  readonly property bool busy: statusProcess.running || controlProcess.running || syncProcess.running || authProcess.running
  readonly property bool canToggle: serviceExists && !controlProcess.running
  readonly property bool canSyncNow: installed && running && rcAvailable && !syncProcess.running && !statusProcess.running
  readonly property bool canReconnect: installed && !authProcess.running
  readonly property bool canOpenFolder: mountPointExpanded !== ""
  readonly property string helperPath: decodeURIComponent(String(Qt.resolvedUrl("status.py")).replace(/^file:\/\//, ""))

  property string _statusOutput: ""
  property string _statusError: ""
  property string _controlOutput: ""
  property string _controlError: ""
  property string _syncOutput: ""
  property string _syncError: ""
  property string _authOutput: ""
  property string _authError: ""
  property bool _authUrlOpened: false

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function stringSetting(name, fallback) {
    return String(setting(name, fallback) || fallback)
  }

  function intSetting(name, fallback, min, max) {
    var n = parseInt(String(setting(name, fallback)), 10)
    if (!isFinite(n)) n = fallback
    if (n < min) n = min
    if (n > max) n = max
    return n
  }

  function expandHome(path) {
    var value = String(path || "")
    var home = Quickshell.env("HOME") || ""
    if (value.indexOf("~/") === 0 && home !== "") return home + value.substring(1)
    if (value === "~" && home !== "") return home
    return value
  }

  function refresh() {
    if (statusProcess.running) return
    _statusOutput = ""
    _statusError = ""
    refreshing = true
    statusProcess.command = ["python3", helperPath, remoteName, mountPoint, serviceUnit, rcAddr, "25"]
    statusProcess.running = true
  }

  function applyStatus(raw) {
    var parsed = Model.parseStatus(raw)
    if (!parsed.ok) {
      lastError = parsed.lastError || "Failed to read OneDrive status"
      return
    }
    installed = parsed.installed === true
    serviceExists = parsed.serviceExists === true
    running = parsed.running === true
    mounted = parsed.mounted === true
    authenticated = parsed.authenticated === true
    rcAvailable = parsed.rcAvailable === true
    if (_desired !== -1 && running === (_desired === 1)) _desired = -1
    statusText = String(parsed.statusText || (installed ? "Stopped" : "Not installed"))
    mountPointExpanded = String(parsed.mountPointExpanded || expandHome(mountPoint))
    lastSyncTs = Number(parsed.lastSyncTs || 0)
    pendingFiles = parsed.pendingFiles || []
    pendingCount = Number(parsed.pendingCount || pendingFiles.length || 0)
    bytesQueued = Number(parsed.bytesQueued || 0)
    transferredBytes = Number(parsed.transferredBytes || 0)
    errorCount = Number(parsed.errorCount || 0)
    errors = parsed.errors || []
    if (errors.length > 0 && !lastError) lastError = String(errors[0])
    else if (errors.length === 0) lastError = ""
  }

  function elideStatus(text) {
    var value = String(text || "").replace(/\s+/g, " ").trim()
    return value.length > 140 ? value.substring(0, 137) + "…" : value
  }

  function pause() {
    runControl(["systemctl", "--user", "stop", serviceUnit], 0)
  }

  function resume() {
    runControl(["systemctl", "--user", "start", serviceUnit], 1)
  }

  function toggleRunning() {
    if (active) pause()
    else resume()
  }

  function runControl(command, desired) {
    if (controlProcess.running || !serviceExists) return
    _desired = desired
    _controlOutput = ""
    _controlError = ""
    controlProcess.command = command
    controlProcess.running = true
  }

  function syncNow() {
    if (!installed) return
    if (!running) {
      actionStatus = "Start the mount service first"
      actionStatusTimer.restart()
      return
    }
    if (!rcAvailable) {
      actionStatus = "rclone RC is unavailable"
      actionStatusTimer.restart()
      return
    }
    if (syncProcess.running) return
    _syncOutput = ""
    _syncError = ""
    syncProcess.command = ["rclone", "rc", "--rc-addr", rcAddr, "vfs/refresh", "recursive=true"]
    syncProcess.running = true
  }

  function reconnect() {
    if (authProcess.running || !installed) return
    _authOutput = ""
    _authError = ""
    _authUrlOpened = false
    actionStatus = "Starting OneDrive authorization…"
    authProcess.command = ["bash", "-lc", "rclone config reconnect " + shellQuote(remoteName + ":") + " --auto-confirm || rclone authorize onedrive"]
    authProcess.running = true
  }

  function shellQuote(text) {
    return "'" + String(text || "").replace(/'/g, "'\\''") + "'"
  }

  function openFolder() {
    if (mountPointExpanded === "") return
    Quickshell.execDetached(["uwsm-app", "--", "nautilus", mountPointExpanded])
  }

  function openFile(file) {
    if (!file || !file.path) {
      openFolder()
      return
    }
    Quickshell.execDetached(["uwsm-app", "--", "nautilus", "--select", fileUri(String(file.path))])
  }

  function fileUri(path) {
    var parts = String(path || "").split("/")
    for (var i = 0; i < parts.length; i++) parts[i] = encodeURIComponent(parts[i])
    return "file://" + parts.join("/")
  }

  function openAuthUrlFrom(text) {
    if (_authUrlOpened) return true
    var match = String(text || "").match(/https?:\/\/\S+/)
    if (match && match[0]) {
      _authUrlOpened = true
      Qt.openUrlExternally(match[0])
      actionStatus = "Opened OneDrive authorization"
      actionStatusTimer.restart()
      return true
    }
    return false
  }

  function handleAuthOutput(data, isError) {
    var text = String(data || "")
    if (isError) _authError += text + "\n"
    else _authOutput += text + "\n"
    openAuthUrlFrom(text)
  }

  Timer {
    id: refreshTimer
    interval: root.refreshIntervalSec * 1000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    id: startupRamp
    property int ticks: 0
    interval: 2000
    repeat: true
    running: true
    onTriggered: {
      ticks += 1
      if (root.running || ticks >= 15) startupRamp.running = false
      else root.refresh()
    }
  }

  Timer {
    id: delayedRefresh
    interval: 1000
    repeat: false
    onTriggered: root.refresh()
  }

  Timer {
    id: actionStatusTimer
    interval: 2200
    repeat: false
    onTriggered: root.actionStatus = ""
  }

  Timer {
    id: settleTimer
    property int ticks: 0
    interval: 1500
    repeat: true
    running: false
    onTriggered: {
      settleTimer.ticks += 1
      root.refresh()
      if (settleTimer.ticks >= 4) {
        settleTimer.ticks = 0
        settleTimer.running = false
        root._desired = -1
      }
    }
  }

  Process {
    id: statusProcess
    running: false
    command: []
    stdout: StdioCollector { id: statusStdout; waitForEnd: true; onStreamFinished: root._statusOutput = text }
    stderr: StdioCollector { id: statusStderr; waitForEnd: true; onStreamFinished: root._statusError = text }
    onExited: function(exitCode) {
      root.refreshing = false
      var stdout = String(statusStdout.text || root._statusOutput || "")
      var stderr = String(statusStderr.text || root._statusError || "")
      if (exitCode === 0) root.applyStatus(stdout)
      else root.lastError = root.elideStatus(stderr || stdout || "Could not read OneDrive status")
    }
  }

  Process {
    id: controlProcess
    running: false
    command: []
    stdout: StdioCollector { id: controlStdout; waitForEnd: true; onStreamFinished: root._controlOutput = text }
    stderr: StdioCollector { id: controlStderr; waitForEnd: true; onStreamFinished: root._controlError = text }
    onExited: function(exitCode) {
      var stdout = String(controlStdout.text || root._controlOutput || "")
      var stderr = String(controlStderr.text || root._controlError || "")
      if (exitCode !== 0) {
        root._desired = -1
        root.lastError = root.elideStatus(stderr || stdout || "Service command failed")
        root.actionStatus = root.lastError
      } else {
        root.lastError = ""
        root.actionStatus = ""
      }
      settleTimer.ticks = 0
      settleTimer.restart()
      delayedRefresh.restart()
    }
  }

  Process {
    id: syncProcess
    running: false
    command: []
    stdout: StdioCollector { id: syncStdout; waitForEnd: true; onStreamFinished: root._syncOutput = text }
    stderr: StdioCollector { id: syncStderr; waitForEnd: true; onStreamFinished: root._syncError = text }
    onExited: function(exitCode) {
      var stdout = String(syncStdout.text || root._syncOutput || "")
      var stderr = String(syncStderr.text || root._syncError || "")
      if (exitCode !== 0) {
        root.lastError = root.elideStatus(stderr || stdout || "rclone refresh failed")
        root.actionStatus = root.lastError
      } else {
        root.lastError = ""
        root.actionStatus = "Refresh requested"
        actionStatusTimer.restart()
      }
      delayedRefresh.restart()
    }
  }

  Process {
    id: authProcess
    running: false
    command: []
    stdout: SplitParser { onRead: function(data) { root.handleAuthOutput(data, false) } }
    stderr: SplitParser { onRead: function(data) { root.handleAuthOutput(data, true) } }
    onExited: function(exitCode) {
      var combined = String(root._authOutput || "") + "\n" + String(root._authError || "")
      var opened = root.openAuthUrlFrom(combined)
      if (exitCode !== 0 && !opened) {
        root.lastError = root.elideStatus(combined || "OneDrive authorization failed")
        root.actionStatus = root.lastError
      } else if (!opened) {
        root.actionStatus = "Authorization finished"
        root.lastError = ""
        actionStatusTimer.restart()
      } else {
        root.lastError = ""
      }
      delayedRefresh.restart()
    }
  }
}
