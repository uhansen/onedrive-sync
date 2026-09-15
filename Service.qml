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
  property string backend: stringSetting("backend", "rclone_mount")
  readonly property bool isDavfsBackend: backend === "wasm_davfs"
  property string davfsUrl: stringSetting("davfsUrl", "http://127.0.0.1:8765/")
  property string daemonServiceUnit: stringSetting("daemonServiceUnit", "onedrive-davfs.service")
  property string mountServiceUnit: stringSetting("mountServiceUnit", "onedrive-davfs-mount.service")
  property string stateDir: stringSetting("stateDir", "~/.local/state/onedrive-davfs")
  property string reconnectCommand: stringSetting("reconnectCommand", "")
  property string envFile: stringSetting("envFile", "~/.config/onedrive-davfs/env")
  property double lastSyncTs: 0
  property var pendingFiles: []
  property int pendingCount: 0
  property double bytesQueued: 0
  property double transferredBytes: 0
  property int errorCount: 0
  property var errors: []
  property string actionStatus: ""
  property string lastError: ""
  property bool mountServiceExists: false
  property bool mountServiceRunning: false
  property bool daemonReachable: false
  property double tokenExpiresInSec: 0
  property bool indexEnabled: false
  property bool crawlComplete: false
  property double totalDirs: 0
  property double totalFiles: 0
  property double itemsPerSec: 0
  property double lastTickAt: 0
  property double lastTickApplied: 0
  property double lastTickDurationMs: 0
  property var treeByPath: ({})
  property var treeExpanded: ({})
  property string treeError: ""
  property string selectedTreePath: "/"
  property string searchQuery: ""
  property var searchResults: []
  property bool searchReady: true
  property bool searchTruncated: false
  property string searchError: ""
  property string searchSubmittedQuery: ""
  property string copyDestination: stringSetting("copyDestination", "~/Downloads/OneDrive")
  property var pendingCopyEntry: null

  readonly property int refreshIntervalSec: intSetting("refreshIntervalSec", 30, 5, 3600)
  readonly property bool treeLoading: treeProcess.running
  readonly property bool searchLoading: searchProcess.running
  readonly property bool busy: statusProcess.running || controlProcess.running || syncProcess.running || authProcess.running || indexStatsProcess.running || treeProcess.running || pickFolderProcess.running
  readonly property bool canToggle: serviceExists && !controlProcess.running
  readonly property bool canSyncNow: !isDavfsBackend && installed && running && rcAvailable && !syncProcess.running && !statusProcess.running
  readonly property bool canReconnect: isDavfsBackend
    ? (reconnectCommand !== "" && !authProcess.running)
    : (installed && !authProcess.running)
  readonly property bool canOpenFolder: mountPointExpanded !== ""
  readonly property string helperPath: decodeURIComponent(String(Qt.resolvedUrl("status.py")).replace(/^file:\/\//, ""))
  readonly property string helperPathDavfs: decodeURIComponent(String(Qt.resolvedUrl("status_davfs.py")).replace(/^file:\/\//, ""))
  readonly property string helperPathTree: decodeURIComponent(String(Qt.resolvedUrl("tree_davfs.py")).replace(/^file:\/\//, ""))
  readonly property string helperPathPickFolder: decodeURIComponent(String(Qt.resolvedUrl("pick_folder.py")).replace(/^file:\/\//, ""))

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
    if (isDavfsBackend) {
      statusProcess.command = ["python3", helperPathDavfs, mountPoint, daemonServiceUnit, mountServiceUnit, stateDir, davfsUrl]
      fetchIndexStats()
    } else {
      statusProcess.command = ["python3", helperPath, remoteName, mountPoint, serviceUnit, rcAddr, "25"]
    }
    statusProcess.running = true
  }

  function refreshView() {
    refresh()
    if (isDavfsBackend) {
      treeByPath = ({})
      treeExpanded = ({})
      treeError = ""
      browserRefreshTimer.restart()
    }
    actionStatus = "Refreshing OneDrive view…"
    actionStatusTimer.restart()
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
    mountServiceExists = parsed.mountServiceExists === true
    mountServiceRunning = parsed.mountServiceRunning === true
    daemonReachable = parsed.daemonReachable === true
    tokenExpiresInSec = Number(parsed.tokenExpiresInSec || 0)
    if (_desired !== -1 && running === (_desired === 1)) _desired = -1
    statusText = String(parsed.statusText || (installed ? "Stopped" : "Not installed"))
    mountPointExpanded = String(parsed.mountPointExpanded || expandHome(mountPoint))
    lastSyncTs = Number(parsed.lastSyncTs || 0)
    if (isDavfsBackend && lastTickAt > 0) lastSyncTs = lastTickAt
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

  function backendServiceUnits() {
    if (!isDavfsBackend) return [serviceUnit]
    var units = [daemonServiceUnit]
    if (mountServiceUnit !== "") units.push(mountServiceUnit)
    return units
  }

  function pause() {
    var units = backendServiceUnits().slice().reverse()
    runControl(["systemctl", "--user", "stop"].concat(units), 0)
  }

  function resume() {
    var units = backendServiceUnits()
    runControl(["systemctl", "--user", "start"].concat(units), 1)
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
    if (isDavfsBackend) return
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
    if (isDavfsBackend) {
      reconnectDavfs()
      return
    }
    if (authProcess.running || !installed) return
    _authOutput = ""
    _authError = ""
    _authUrlOpened = false
    actionStatus = "Starting OneDrive authorization…"
    authProcess.command = ["bash", "-lc", "rclone config reconnect " + shellQuote(remoteName + ":") + " --auto-confirm || rclone authorize onedrive"]
    authProcess.running = true
  }

  function reconnectDavfs() {
    if (reconnectCommand === "") {
      actionStatus = "Set a Reconnect command in plugin settings first"
      actionStatusTimer.restart()
      return
    }
    // Runs the user-configured sign-in command (e.g. tools/device-code-login.sh)
    // in a floating terminal via Omarchy's own presentation helper -- the
    // same mechanism Omarchy's install-app flows use. The plugin never
    // touches OAuth tokens or client secrets itself; it only launches the
    // command the user configured once in settings.
    actionStatus = "Opening OneDrive sign-in terminal…"
    actionStatusTimer.restart()
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation", reconnectCommand])
    delayedRefresh.restart()
  }

  function shellQuote(text) {
    return "'" + String(text || "").replace(/'/g, "'\\''") + "'"
  }

  function fetchIndexStats() {
    if (!isDavfsBackend || indexStatsProcess.running) return
    indexStatsProcess.command = ["python3", helperPathTree, "status", envFile, davfsUrl]
    indexStatsProcess.running = true
  }

  function fetchTree(path) {
    if (!isDavfsBackend || treeProcess.running) return
    var target = String(path || "/")
    if (target.indexOf("..") !== -1) return
    treeError = ""
    treeProcess.command = ["python3", helperPathTree, "tree", envFile, davfsUrl, target]
    treeProcess.running = true
  }

  function ensureTreeRoot() {
    if (!isDavfsBackend) return
    if (!treeByPath["/"]) fetchTree("/")
  }

  function toggleTreeExpand(path) {
    var next = Object.assign({}, treeExpanded)
    if (next[path]) {
      delete next[path]
    } else {
      next[path] = true
      if (!treeByPath[path]) fetchTree(path)
    }
    treeExpanded = next
  }

  function applyIndexStats(raw) {
    var parsed = Model.parseIndexStatus(raw)
    if (!parsed.ok) {
      treeError = parsed.error || parsed.lastError || ""
      return
    }
    indexEnabled = parsed.indexEnabled === true
    crawlComplete = parsed.crawlComplete === true
    totalDirs = Number(parsed.totalDirs || 0)
    totalFiles = Number(parsed.totalFiles || 0)
    itemsPerSec = Number(parsed.itemsPerSec || 0)
    lastTickAt = Number(parsed.lastTickAt || 0)
    lastTickApplied = Number(parsed.lastTickApplied || 0)
    lastTickDurationMs = Number(parsed.lastTickDurationMs || 0)
    if (lastTickAt > 0) lastSyncTs = lastTickAt
  }

  function applyTree(raw) {
    var parsed = Model.parseTree(raw)
    if (!parsed.ok) {
      treeError = parsed.error || parsed.lastError || "Failed to list folder"
      return
    }
    var next = Object.assign({}, treeByPath)
    next[parsed.path] = parsed
    treeByPath = next
    if (!selectedTreePath || selectedTreePath === "") selectedTreePath = parsed.path
  }

  function updateSearchQuery(text) {
    searchQuery = String(text || "")
    if (searchQuery.length < 2) {
      searchDebounce.stop()
      searchResults = []
      searchReady = true
      searchTruncated = false
      searchError = ""
      return
    }
    searchDebounce.restart()
  }

  function runSearch() {
    if (!isDavfsBackend) return
    if (searchQuery.length < 2) return
    if (searchProcess.running) {
      searchDebounce.restart()
      return
    }
    searchSubmittedQuery = searchQuery
    searchProcess.command = ["python3", helperPathTree, "search", envFile, davfsUrl, searchQuery]
    searchProcess.running = true
  }

  function applySearchResults(raw) {
    var parsed = Model.parseSearchResults(raw)
    if (!parsed.ok) {
      searchError = parsed.error || "Search failed"
      searchResults = []
      return
    }
    searchError = ""
    searchReady = parsed.ready !== false
    searchTruncated = parsed.truncated === true
    searchResults = parsed.results || []
  }

  function copyEntry(path, isDir, name, copyContents) {
    if (pickFolderProcess.running) return
    pendingCopyEntry = {
      path: path,
      isDir: isDir,
      name: name,
      copyContents: isDir && copyContents === true
    }
    pickFolderProcess.command = ["/usr/bin/python3", helperPathPickFolder, copyDestination]
    pickFolderProcess.running = true
  }

  function mailEntry(path) {
    var abs = localPathFor(path)
    if (!abs) return
    Quickshell.execDetached(["xdg-email", "--attach", abs])
    actionStatus = "Opened mail compose"
    actionStatusTimer.restart()
  }

  function openEntry(path) {
    var abs = localPathFor(path)
    if (!abs) return
    Quickshell.execDetached(["xdg-open", abs])
    actionStatus = "Opened"
    actionStatusTimer.restart()
  }

  function openFolderAt(path) {
    var abs = localPathFor(path)
    if (!abs) return
    Quickshell.execDetached(["uwsm-app", "--", "nautilus", abs])
    actionStatus = "Opened folder"
    actionStatusTimer.restart()
  }

  function localPathFor(relPath) {
    var base = String(mountPointExpanded || "").replace(/\/+$/, "")
    var rel = String(relPath || "/")
    if (rel.indexOf("..") !== -1) return base
    if (rel === "/" || rel === "") return base
    if (rel.charAt(0) !== "/") rel = "/" + rel
    return base + rel
  }

  function openTerminalAt(relPath) {
    var abs = localPathFor(relPath)
    if (!abs) return
    Quickshell.execDetached(["uwsm-app", "--", "xdg-terminal-exec", "--dir=" + abs])
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

  Timer {
    id: searchDebounce
    interval: 250
    repeat: false
    onTriggered: root.runSearch()
  }

  Timer {
    id: browserRefreshTimer
    interval: 250
    repeat: false
    onTriggered: {
      if (treeProcess.running || searchProcess.running) {
        browserRefreshTimer.restart()
        return
      }
      root.fetchTree("/")
      if (root.searchQuery.length >= 2) root.runSearch()
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
    id: indexStatsProcess
    running: false
    command: []
    stdout: StdioCollector { id: indexStatsStdout; waitForEnd: true }
    stderr: StdioCollector { id: indexStatsStderr; waitForEnd: true }
    onExited: function(exitCode) {
      var stdout = String(indexStatsStdout.text || "")
      var stderr = String(indexStatsStderr.text || "")
      if (exitCode === 0) root.applyIndexStats(stdout)
      else root.treeError = root.elideStatus(stderr || stdout || "Could not read index status")
    }
  }

  Process {
    id: treeProcess
    running: false
    command: []
    stdout: StdioCollector { id: treeStdout; waitForEnd: true }
    stderr: StdioCollector { id: treeStderr; waitForEnd: true }
    onExited: function(exitCode) {
      var stdout = String(treeStdout.text || "")
      var stderr = String(treeStderr.text || "")
      if (exitCode === 0) root.applyTree(stdout)
      else root.treeError = root.elideStatus(stderr || stdout || "Could not list folder")
    }
  }

  Process {
    id: searchProcess
    running: false
    command: []
    stdout: StdioCollector { id: searchStdout; waitForEnd: true }
    stderr: StdioCollector { id: searchStderr; waitForEnd: true }
    onExited: function(exitCode) {
      var stdout = String(searchStdout.text || "")
      var stderr = String(searchStderr.text || "")
      var submittedQuery = root.searchSubmittedQuery
      root.searchSubmittedQuery = ""
      if (submittedQuery !== root.searchQuery) {
        if (root.searchQuery.length >= 2) searchDebounce.restart()
        return
      }
      if (exitCode === 0) root.applySearchResults(stdout)
      else {
        root.searchError = root.elideStatus(stderr || stdout || "Search failed")
        root.searchResults = []
      }
    }
  }

  Process {
    id: pickFolderProcess
    running: false
    command: []
    stdout: StdioCollector { id: pickFolderStdout; waitForEnd: true }
    stderr: StdioCollector { id: pickFolderStderr; waitForEnd: true }
    onExited: function(exitCode) {
      var dest = String(pickFolderStdout.text || "").trim()
      var entry = root.pendingCopyEntry
      root.pendingCopyEntry = null
      if (exitCode !== 0 || dest === "" || !entry) return
      var src = root.localPathFor(entry.path)
      if (!src) return
      var source = entry.copyContents ? root.shellQuote(src + "/.") : root.shellQuote(src)
      var cmd = "mkdir -p -- " + root.shellQuote(dest) + " && cp -R -n -- " + source + " " + root.shellQuote(dest) + "/"
      Quickshell.execDetached(["sh", "-c", cmd])
      root.actionStatus = (entry.copyContents ? "Copied folder contents to " : "Copied to ") + dest
      actionStatusTimer.restart()
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
