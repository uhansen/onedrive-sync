import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "onedrive-sync"
  ipcTarget: "onedrive-sync"
  manageIpc: false

  property string focusSection: "login"
  property int actionIndex: 0
  property int fileIndex: 0
  property int treeIndex: 0
  property int searchIndex: 0
  property int browserActionIndex: 0
  property string browserFocus: "root"
  property bool cursorActive: false
  property int phraseIndex: 0
  property bool treePanelOpen: false
  property bool statisticsExpanded: false

  readonly property var activePhrases: [
    "Mounting memories",
    "Syncing safely",
    "Watching uploads",
    "Following writeback",
    "Checking queues"
  ]
  readonly property string heroPhraseText: activePhrases[phraseIndex % activePhrases.length]
  readonly property bool showHero: onedrive.installed || onedrive.serviceExists || onedrive.authenticated
  readonly property string heroMeta: heroMetaText()
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color iconColor: onedrive.authenticated && onedrive.active ? foreground : (onedrive.lastError !== "" ? urgent : dim)
  readonly property string toggleHint: onedrive.active ? "Pause the mount service" : "Resume the mount service"
  readonly property color barIconColor: onedrive.authenticated && onedrive.active ? barForeground : Qt.darker(barForeground, 1.55)
  readonly property bool headerHasCursor: cursorActive && focusSection === "header" && onedrive.serviceExists
  readonly property string loginTitle: onedrive.isDavfsBackend
    ? (onedrive.authenticated ? "Reconnect OneDrive" : "Sign in to OneDrive")
    : (!onedrive.installed
      ? "rclone is not installed"
      : (onedrive.authenticated ? "Reconnect OneDrive" : "Authorize OneDrive"))
  readonly property string loginSubtitle: onedrive.isDavfsBackend
    ? (onedrive.reconnectCommand === ""
      ? "Set a Reconnect command in plugin settings first"
      : (!onedrive.serviceExists
        ? "Create " + onedrive.daemonServiceUnit + " after signing in"
        : "Run the configured sign-in command in a floating terminal"))
    : (!onedrive.installed
      ? "Install rclone and configure a OneDrive remote first"
      : (!onedrive.serviceExists
        ? "Create " + onedrive.serviceUnit + " after authorizing the remote"
        : "Open rclone's OAuth flow in the browser"))

  function tokenExpiryText() {
    var remaining = Number(onedrive.tokenExpiresInSec || 0)
    if (!isFinite(remaining) || remaining <= 0) return Model.formatDuration(0)
    return "expires in " + Model.formatDuration(remaining)
  }

  function heroMetaText() {
    if (onedrive.lastError !== "") return onedrive.lastError
    if (onedrive.isDavfsBackend) {
      if (!onedrive.serviceExists) return "Create " + onedrive.daemonServiceUnit + " to manage the daemon"
      if (!onedrive.authenticated) return "Sign in to OneDrive"
      if (onedrive.active && !onedrive.mounted) return "Daemon active, waiting for mount"
      if (onedrive.active && !onedrive.daemonReachable) return "Daemon active, not responding"
      if (onedrive.active) return Model.statusSummary(onedrive.statusText, onedrive.pendingCount, onedrive.lastSyncTs)
      return "Daemon paused"
    }
    if (!onedrive.installed) return "Install rclone to enable OneDrive control"
    if (!onedrive.serviceExists) return "Create " + onedrive.serviceUnit + " to manage the mount"
    if (!onedrive.authenticated) return "Authorize remote " + onedrive.remoteName
    if (onedrive.active && onedrive.pendingCount > 0) return heroPhraseText
    if (onedrive.active && !onedrive.mounted) return "Service active, waiting for mount"
    if (onedrive.active) return Model.statusSummary(onedrive.statusText, onedrive.pendingCount, onedrive.lastSyncTs)
    return "Sync paused"
  }

  function stateText(flag, yesText, noText) {
    return flag ? yesText : noText
  }

  readonly property var treeRows: Model.flattenTree(onedrive.treeByPath, onedrive.treeExpanded, "/")
  readonly property int minActionIndex: 0
  readonly property int maxActionIndex: 1
  readonly property bool indexingActive: onedrive.isDavfsBackend && onedrive.indexEnabled && !onedrive.crawlComplete

  function indexProgressText() {
    var dirs = Number(onedrive.totalDirs || 0)
    var files = Number(onedrive.totalFiles || 0)
    var total = dirs + files
    if (!onedrive.indexEnabled) return "Off"
    if (total <= 0) return onedrive.crawlComplete ? "Empty" : "Crawling…"
    var label = total + " items · " + dirs + " folders"
    return onedrive.crawlComplete ? label : ("Crawling · " + label)
  }

  function tickMetaText() {
    if (Number(onedrive.lastTickAt || 0) <= 0) return "Waiting for first tick"
    var parts = []
    parts.push(Model.relativeTime(onedrive.lastTickAt))
    if (Number(onedrive.lastTickApplied || 0) > 0)
      parts.push(onedrive.lastTickApplied + " items · " + Math.round(onedrive.lastTickDurationMs) + " ms")
    parts.push(Model.formatRate(onedrive.itemsPerSec))
    return parts.join(" · ")
  }

  function ensureCursor() {
    if (!onedrive.authenticated) {
      focusSection = "login"
      return
    }
    if (focusSection !== "header" && focusSection !== "actions" && focusSection !== "files") focusSection = "header"
    if (fileIndex >= onedrive.pendingFiles.length) fileIndex = Math.max(0, onedrive.pendingFiles.length - 1)
    if (fileIndex < 0) fileIndex = 0
    if (treeIndex >= treeRows.length) treeIndex = Math.max(0, treeRows.length - 1)
    if (treeIndex < 0) treeIndex = 0
    if (actionIndex < minActionIndex) actionIndex = minActionIndex
    if (actionIndex > maxActionIndex) actionIndex = maxActionIndex
    if (focusSection === "files" && onedrive.pendingFiles.length === 0) {
      focusSection = "actions"
    }
  }

  function moveCursor(dx, dy) {
    cursorActive = true
    ensureCursor()
    if (focusSection === "login") return
    if (focusSection === "header") {
      if (dy > 0) focusSection = "actions"
      return
    }
    if (focusSection === "actions") {
      if (dy < 0) {
        focusSection = "header"
        return
      }
      if (dy > 0 && onedrive.pendingFiles.length > 0) {
        focusSection = "files"
        fileIndex = 0
        scrollCursorIntoView()
        return
      }
      if (dx < 0) actionIndex = Math.max(minActionIndex, actionIndex - 1)
      if (dx > 0) actionIndex = Math.min(maxActionIndex, actionIndex + 1)
      return
    }
    if (focusSection === "files") {
      if (dy < 0 && fileIndex === 0) {
        focusSection = "actions"
        return
      }
      if (dy !== 0) {
        fileIndex = Math.max(0, Math.min(onedrive.pendingFiles.length - 1, fileIndex + dy))
        scrollCursorIntoView()
      }
    }
  }

  function activateCursor() {
    ensureCursor()
    if (focusSection === "login") onedrive.reconnect()
    else if (focusSection === "header") onedrive.toggleRunning()
    else if (focusSection === "actions") triggerAction(actionIndex)
    else if (focusSection === "files") onedrive.openFile(selectedFile())
  }

  function openTreePanel() {
    treePanelOpen = true
    onedrive.ensureTreeRoot()
    treeIndex = 0
    searchIndex = 0
    browserActionIndex = 0
    browserFocus = "root"
    var row = selectedTreeRow()
    if (row) onedrive.selectedTreePath = row.path
  }

  function closeTreePanel() {
    treePanelOpen = false
    if (onedrive.searchQuery !== "") onedrive.updateSearchQuery("")
  }

  function browserRows() {
    return onedrive.searchQuery.length >= 2 ? onedrive.searchResults : treeRows
  }

  function selectedBrowserEntry() {
    if (browserFocus === "root") return { path: "/", name: "OneDrive", isDir: true, root: true }
    var rows = browserRows()
    if (rows.length === 0) return null
    var index = onedrive.searchQuery.length >= 2 ? searchIndex : treeIndex
    return rows[Math.max(0, Math.min(rows.length - 1, index))]
  }

  function browserActionCount(entry) {
    return entry && entry.isDir ? 4 : 3
  }

  function moveBrowserCursor(dx, dy) {
    var rows = browserRows()
    if (dy > 0 && browserFocus === "root" && rows.length > 0) {
      browserFocus = "rows"
      browserActionIndex = -1
    } else if (dy < 0 && browserFocus === "rows") {
      var current = onedrive.searchQuery.length >= 2 ? searchIndex : treeIndex
      if (current === 0) {
        browserFocus = "root"
        browserActionIndex = 0
      } else if (onedrive.searchQuery.length >= 2) {
        searchIndex = current - 1
      } else {
        treeIndex = current - 1
      }
    } else if (dy > 0 && browserFocus === "rows" && rows.length > 0) {
      if (onedrive.searchQuery.length >= 2)
        searchIndex = Math.min(rows.length - 1, searchIndex + 1)
      else
        treeIndex = Math.min(rows.length - 1, treeIndex + 1)
    }

    var entry = selectedBrowserEntry()
    if (dx > 0 && entry)
      browserActionIndex = Math.min(browserActionCount(entry) - 1, browserActionIndex + 1)
    else if (dx < 0)
      browserActionIndex = Math.max(browserFocus === "root" ? 0 : -1, browserActionIndex - 1)

    if (browserFocus === "rows") {
      if (onedrive.searchQuery.length >= 2) scrollSearchCursorIntoView()
      else {
        var row = selectedTreeRow()
        if (row) onedrive.selectedTreePath = row.path
        scrollTreeCursorIntoView()
      }
    }
  }

  function selectedTreeRow() {
    if (treeRows.length === 0) return null
    return treeRows[Math.max(0, Math.min(treeIndex, treeRows.length - 1))]
  }

  function treeParentPath(path) {
    var p = String(path || "/")
    var i = p.lastIndexOf("/")
    if (i <= 0) return "/"
    return p.substring(0, i)
  }

  function activateTreeRow(row) {
    if (!row) return
    onedrive.selectedTreePath = row.path
    if (row.isDir) onedrive.toggleTreeExpand(row.path)
    else onedrive.openTerminalAt(treeParentPath(row.path))
  }

  function triggerBrowserAction(entry, index) {
    if (!entry) return
    var path = String(entry.path || "/")
    var isDir = entry.isDir === true
    if (isDir) {
      if (index === 0) onedrive.openTerminalAt(path)
      else if (index === 1) onedrive.openFolderAt(path)
      else if (index === 2) onedrive.copyEntry(path, true, entry.name || "OneDrive")
      else if (index === 3) onedrive.copyEntry(path, true, entry.name || "OneDrive", true)
    } else {
      if (index === 0) onedrive.openEntry(path)
      else if (index === 1) onedrive.copyEntry(path, false, entry.name || "")
      else if (index === 2) onedrive.mailEntry(path)
    }
  }

  function activateBrowserCursor() {
    var entry = selectedBrowserEntry()
    if (!entry) return
    if (browserFocus === "rows" && browserActionIndex < 0) {
      if (onedrive.searchQuery.length >= 2) {
        if (entry.isDir) onedrive.openFolderAt(entry.path)
        else onedrive.openEntry(entry.path)
      }
      else activateTreeRow(entry)
      return
    }
    triggerBrowserAction(entry, browserActionIndex)
  }

  function triggerBrowserShortcut(key) {
    var entry = selectedBrowserEntry()
    if (!entry) return
    var value = String(key || "").toLowerCase()
    if (value === "t" && entry.isDir) onedrive.openTerminalAt(entry.path)
    else if (value === "f") {
      if (entry.isDir) onedrive.openFolderAt(entry.path)
      else onedrive.openEntry(entry.path)
    } else if (value === "c") onedrive.copyEntry(entry.path, entry.isDir, entry.name || "")
    else if (value === "x" && entry.isDir) onedrive.copyEntry(entry.path, true, entry.name || "OneDrive", true)
    else if (value === "m" && !entry.isDir) onedrive.mailEntry(entry.path)
  }

  function openTreeTerminal(row) {
    if (!row) {
      onedrive.openTerminalAt(onedrive.selectedTreePath || "/")
      return
    }
    onedrive.selectedTreePath = row.path
    onedrive.openTerminalAt(row.isDir ? row.path : treeParentPath(row.path))
  }

  function setTreeCursor(index) {
    browserFocus = "rows"
    browserActionIndex = -1
    treeIndex = index
    var row = selectedTreeRow()
    if (row) onedrive.selectedTreePath = row.path
  }

  function triggerAction(index) {
    if (index === 0 && onedrive.isDavfsBackend) root.openTreePanel()
    else if (index === 0) onedrive.syncNow()
    else if (index === 1) onedrive.openFolder()
  }

  function selectedFile() {
    if (onedrive.pendingFiles.length === 0) return null
    return onedrive.pendingFiles[Math.max(0, Math.min(fileIndex, onedrive.pendingFiles.length - 1))]
  }

  function setHeaderCursor() {
    cursorActive = true
    focusSection = "header"
    if (panelFlick) panelFlick.contentY = 0
  }

  function setActionCursor(index) {
    cursorActive = true
    focusSection = "actions"
    actionIndex = index
  }

  function setFileCursor(index) {
    cursorActive = true
    focusSection = "files"
    fileIndex = index
    scrollCursorIntoView()
  }

  function scrollItemIntoView(item) {
    if (!panelFlick || !item) return
    Qt.callLater(function() {
      if (!item) return
      var margin = Style.space(6)
      var point = item.mapToItem(panelFlick.contentItem, 0, 0)
      var top = point.y
      var bottom = top + item.height
      var viewTop = panelFlick.contentY
      var viewBottom = viewTop + panelFlick.height
      var maxY = Math.max(0, panelFlick.contentHeight - panelFlick.height)
      if (top < viewTop + margin) panelFlick.contentY = Math.max(0, top - margin)
      else if (bottom > viewBottom - margin) panelFlick.contentY = Math.min(maxY, bottom + margin - panelFlick.height)
    })
  }

  function scrollCursorIntoView() {
    if (focusSection === "files" && fileColumn && fileIndex >= 0 && fileIndex < fileColumn.children.length)
      scrollItemIntoView(fileColumn.children[fileIndex])
  }

  function scrollTreeCursorIntoView() {
    if (!treeColumn || treeIndex < 0 || treeIndex >= treeColumn.children.length) return
    var item = treeColumn.children[treeIndex]
    if (!treeOverlayFlick || !item) return
    Qt.callLater(function() {
      if (!item) return
      var margin = Style.space(6)
      var point = item.mapToItem(treeOverlayFlick.contentItem, 0, 0)
      var top = point.y
      var bottom = top + item.height
      var viewTop = treeOverlayFlick.contentY
      var viewBottom = viewTop + treeOverlayFlick.height
      var maxY = Math.max(0, treeOverlayFlick.contentHeight - treeOverlayFlick.height)
      if (top < viewTop + margin) treeOverlayFlick.contentY = Math.max(0, top - margin)
      else if (bottom > viewBottom - margin) treeOverlayFlick.contentY = Math.min(maxY, bottom + margin - treeOverlayFlick.height)
    })
  }

  function scrollSearchCursorIntoView() {
    if (!searchResultsColumn || searchIndex < 0 || searchIndex >= searchResultsColumn.children.length) return
    var item = searchResultsColumn.children[searchIndex]
    if (!searchResultsFlick || !item) return
    Qt.callLater(function() {
      var margin = Style.space(6)
      var point = item.mapToItem(searchResultsFlick.contentItem, 0, 0)
      var top = point.y
      var bottom = top + item.height
      var viewTop = searchResultsFlick.contentY
      var viewBottom = viewTop + searchResultsFlick.height
      var maxY = Math.max(0, searchResultsFlick.contentHeight - searchResultsFlick.height)
      if (top < viewTop + margin) searchResultsFlick.contentY = Math.max(0, top - margin)
      else if (bottom > viewBottom - margin) searchResultsFlick.contentY = Math.min(maxY, bottom + margin - searchResultsFlick.height)
    })
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) {
    cursorActive = false
    if (panelFlick) panelFlick.contentY = 0
    onedrive.refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  } else {
    closeTreePanel()
  }
  onFileIndexChanged: scrollCursorIntoView()

  Service {
    id: onedrive
    settings: root.settings
  }

  Connections {
    target: onedrive
    function onAuthenticatedChanged() { root.ensureCursor() }
    function onPendingFilesChanged() { root.ensureCursor() }
    function onSearchResultsChanged() {
      root.searchIndex = Math.max(0, Math.min(root.searchIndex, onedrive.searchResults.length - 1))
    }
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { onedrive.refresh(); return "ok" }
    function reconnect(): string { onedrive.reconnect(); return "ok" }
    function status(): string { return onedrive.statusText }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Item {
        OneDriveIcon {
          anchors.centerIn: parent
          iconSize: Style.space(12)
          color: root.barIconColor
          active: onedrive.active
          syncing: onedrive.pendingCount > 0
          indexing: root.indexingActive
          error: onedrive.lastError !== ""
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) onedrive.refresh()
      else if (buttonCode === Qt.MiddleButton) onedrive.reconnect()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(580))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: searchField.activeFocus
      onMoveRequested: function(dx, dy) {
        if (root.treePanelOpen) { root.moveBrowserCursor(dx, dy); return }
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: {
        if (root.treePanelOpen) { root.activateBrowserCursor(); return }
        if (root.cursorActive) root.activateCursor()
      }
      onCloseRequested: {
        if (root.treePanelOpen) { root.closeTreePanel(); return }
        root.close()
      }
      onDeleteRequested: {
        if (root.treePanelOpen) root.triggerBrowserShortcut("x")
      }
      onTabRequested: function(direction) { if (!root.treePanelOpen) root.switchPanel(direction) }
      onTextKey: function(t) {
        if (root.treePanelOpen) {
          if (t === "t" || t === "T" || t === "f" || t === "F"
              || t === "c" || t === "C" || t === "x" || t === "X"
              || t === "m" || t === "M") root.triggerBrowserShortcut(t)
          else if (t === "/") Qt.callLater(function() { searchField.forceActiveFocus() })
          return
        }
        if (t === "r" || t === "R") onedrive.refresh()
        else if (t === "o" || t === "O") onedrive.openFolder()
        else if (t === "p" || t === "P") onedrive.toggleRunning()
        else if (t === "c" || t === "C") onedrive.reconnect()
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          Item {
            id: header
            visible: root.showHero
            width: parent.width
            implicitHeight: hero.implicitHeight
            readonly property bool ringVisible: root.headerHasCursor
            function focusHero() { root.setHeaderCursor() }

            PanelHero {
              id: hero
              width: parent.width
              title: onedrive.authenticated ? "OneDrive" : "OneDrive setup"
              meta: root.heroMeta
              foreground: root.foreground
              fontFamily: root.fontFamily
              iconOpacity: onedrive.active ? 1.0 : 0.55
              iconComponent: Component {
                OneDriveIcon {
                  iconSize: Style.font.display
                  color: root.iconColor
                  active: onedrive.active
                  syncing: onedrive.pendingCount > 0
                  indexing: root.indexingActive
                  error: onedrive.lastError !== ""
                }
              }
              trailingControl: Component {
                RowLayout {
                  spacing: Style.space(6)

                  PanelActionButton {
                    iconText: "󰑐"
                    tooltipText: "Refresh OneDrive view"
                    visible: onedrive.authenticated
                    enabled: !onedrive.refreshing
                    foreground: hero.foreground
                    fontFamily: hero.fontFamily
                    Layout.alignment: Qt.AlignVCenter
                    onClicked: onedrive.refreshView()
                  }

                  PanelActionButton {
                    iconText: "󰌋"
                    tooltipText: "Reconnect OneDrive"
                    visible: onedrive.authenticated
                    enabled: onedrive.canReconnect
                    foreground: hero.foreground
                    fontFamily: hero.fontFamily
                    Layout.alignment: Qt.AlignVCenter
                    onClicked: onedrive.reconnect()
                  }

                  ToggleSwitch {
                    id: powerSwitch
                    visible: onedrive.serviceExists
                    checked: onedrive.active
                    busy: onedrive.busy
                    hasCursor: header.ringVisible
                    foreground: hero.foreground
                    onHovered: function(on) { if (on) header.focusHero() }
                    onToggled: onedrive.toggleRunning()

                    PanelToolTip {
                      visible: powerSwitch.containsMouse
                      text: root.toggleHint
                      fontFamily: hero.fontFamily
                    }
                  }
                }
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            visible: onedrive.actionStatus !== "" || onedrive.lastError !== ""
            width: parent.width
            text: onedrive.actionStatus !== "" ? onedrive.actionStatus : onedrive.lastError
            color: onedrive.lastError !== "" && onedrive.actionStatus === "" ? root.urgent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          LoginButton {
            visible: !onedrive.authenticated
            width: parent.width
          }

          Column {
            visible: onedrive.authenticated || root.showHero
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader {
              text: onedrive.authenticated ? "ACTIONS" : "NEXT STEPS"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Column {
              width: parent.width
              spacing: Style.space(6)

              ActionRow {
                width: parent.width
                rowIndex: 0
                iconText: onedrive.isDavfsBackend ? "󰉋" : "󰑐"
                title: onedrive.isDavfsBackend ? "Browse folders" : "Sync now"
                subtitle: onedrive.isDavfsBackend
                  ? (onedrive.indexEnabled ? indexProgressText() : "Metadata index disabled")
                  : (!onedrive.installed
                    ? "Install rclone first"
                    : (!onedrive.running
                      ? "Start " + onedrive.serviceUnit + " first"
                      : (onedrive.rcAvailable
                        ? "Request a VFS refresh through rclone RC"
                        : "Enable --rc on the rclone service")))
                enabled: onedrive.isDavfsBackend ? onedrive.authenticated : onedrive.canSyncNow
              }

              ActionRow {
                width: parent.width
                rowIndex: 1
                iconText: "󰉋"
                title: "Open folder"
                subtitle: onedrive.mounted ? "Open the active OneDrive mount in Files" : "Open the configured mount folder"
                enabled: onedrive.canOpenFolder
              }

            }
          }

          PanelSeparator {
            visible: onedrive.authenticated && !onedrive.isDavfsBackend
            foreground: root.foreground
          }

          Column {
            visible: onedrive.authenticated && !onedrive.isDavfsBackend
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader {
              text: "PENDING"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              visible: onedrive.pendingFiles.length === 0
              width: parent.width
              text: "No pending items reported by rclone."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
            }

            Column {
              id: fileColumn
              visible: onedrive.pendingFiles.length > 0
              width: parent.width
              spacing: Style.space(6)

              Repeater {
                model: onedrive.pendingFiles
                FileRow {
                  required property var modelData
                  required property int index
                  width: fileColumn.width
                  file: modelData
                  rowIndex: index
                }
              }
            }

          }

          PanelSeparator {
            visible: onedrive.authenticated || root.showHero
            foreground: root.foreground
          }

          Column {
            visible: onedrive.authenticated || root.showHero
            width: parent.width
            spacing: Style.space(8)

            Item {
              width: parent.width
              implicitHeight: statisticsHeader.implicitHeight + Style.spacing.rowPaddingX

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.statisticsExpanded = !root.statisticsExpanded
              }

              RowLayout {
                id: statisticsHeader
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(6)
                anchors.rightMargin: Style.space(6)
                spacing: Style.space(8)

                Text {
                  textFormat: Text.PlainText
                  text: root.statisticsExpanded ? "▾" : "▸"
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                PanelSectionHeader {
                  Layout.fillWidth: true
                  text: "STATISTICS"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                }

                Text {
                  textFormat: Text.PlainText
                  text: onedrive.isDavfsBackend ? indexProgressText() : onedrive.statusText
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                  Layout.maximumWidth: Style.space(190)
                }
              }
            }

            Column {
              visible: root.statisticsExpanded
              width: parent.width
              spacing: Style.spacing.labelGap

              InfoPair { label: "Status"; value: onedrive.statusText }
              InfoPair { label: "Backend"; value: onedrive.isDavfsBackend ? "WebDAV (davfs2)" : "rclone mount" }
              InfoPair { label: "Remote"; value: onedrive.remoteName; visible: !onedrive.isDavfsBackend }
              InfoPair { label: "Unit"; value: onedrive.isDavfsBackend ? onedrive.daemonServiceUnit : onedrive.serviceUnit }
              InfoPair { label: "Service"; value: root.stateText(onedrive.running, "Running", (onedrive.serviceExists ? "Stopped" : "Missing")) }
              InfoPair { label: "Mounted"; value: root.stateText(onedrive.mounted, "Yes", "No") }
              InfoPair { label: "Auth"; value: root.stateText(onedrive.authenticated, "Ready", "Required") }
              InfoPair { label: "RC"; value: root.stateText(onedrive.rcAvailable, "Reachable", "Unavailable"); visible: !onedrive.isDavfsBackend }
              InfoPair { label: "Daemon"; value: root.stateText(onedrive.daemonReachable, "Reachable", "Unavailable"); visible: onedrive.isDavfsBackend }
              InfoPair { label: "Token"; value: onedrive.authenticated ? tokenExpiryText() : "missing"; visible: onedrive.isDavfsBackend }
              InfoPair { label: "Index"; value: indexProgressText(); visible: onedrive.isDavfsBackend }
              InfoPair { label: "Tick"; value: tickMetaText(); visible: onedrive.isDavfsBackend }
              InfoPair { label: "Mount"; value: onedrive.mountPointExpanded }
              InfoPair { label: "Last sync"; value: Model.relativeTime(onedrive.lastSyncTs); visible: !onedrive.isDavfsBackend }
              InfoPair { label: "Pending"; value: String(onedrive.pendingCount); visible: !onedrive.isDavfsBackend }
              InfoPair { label: "Queued"; value: Model.formatBytes(onedrive.bytesQueued); visible: !onedrive.isDavfsBackend }
              InfoPair { label: "Transferred"; value: Model.formatBytes(onedrive.transferredBytes); visible: !onedrive.isDavfsBackend }
            }
          }

          Text {
            visible: onedrive.authenticated || root.showHero
            width: parent.width
            textFormat: Text.PlainText
            text: "R refresh · P mount · O folder · C reconnect"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }

          Item {
            visible: onedrive.authenticated || root.showHero
            width: parent.width
            height: Style.space(4)
          }
        }
      }

      Rectangle {
        id: treeOverlay
        anchors.fill: parent
        visible: opacity > 0
        opacity: root.treePanelOpen ? 1 : 0
        scale: root.treePanelOpen ? 1.0 : 0.97
        color: Color.popups.background
        border.color: Color.popups.border
        border.width: 1
        radius: Style.space(4)

        Behavior on opacity { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }
        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
        }

        ColumnLayout {
          anchors.fill: parent
          anchors.margins: Style.space(10)
          spacing: Style.space(8)

          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(8)

            Text {
              textFormat: Text.PlainText
              text: "󰉋"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.icon
            }

            Text {
              textFormat: Text.PlainText
              Layout.fillWidth: true
              text: "Folders"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              elide: Text.ElideRight
            }

            PanelActionButton {
              iconText: "󰅖"
              tooltipText: "Close"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.closeTreePanel()
            }
          }

          PanelSeparator {
            Layout.fillWidth: true
            foreground: root.foreground
          }

          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(6)

            Text {
              textFormat: Text.PlainText
              Layout.fillWidth: true
              text: "OneDrive root"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            PanelActionButton {
              iconText: "󰆍"
              tooltipText: "Open root in terminal"
              hasCursor: root.browserFocus === "root" && root.browserActionIndex === 0
              foreground: root.foreground
              fontFamily: root.fontFamily
              onHovered: function(on) { if (on) { root.browserFocus = "root"; root.browserActionIndex = 0 } }
              onClicked: onedrive.openTerminalAt("/")
            }

            PanelActionButton {
              iconText: "󰉋"
              tooltipText: "Open root in Files"
              hasCursor: root.browserFocus === "root" && root.browserActionIndex === 1
              foreground: root.foreground
              fontFamily: root.fontFamily
              onHovered: function(on) { if (on) { root.browserFocus = "root"; root.browserActionIndex = 1 } }
              onClicked: onedrive.openFolderAt("/")
            }

            PanelActionButton {
              iconText: "󰆏"
              tooltipText: "Copy OneDrive folder to…"
              hasCursor: root.browserFocus === "root" && root.browserActionIndex === 2
              foreground: root.foreground
              fontFamily: root.fontFamily
              onHovered: function(on) { if (on) { root.browserFocus = "root"; root.browserActionIndex = 2 } }
              onClicked: onedrive.copyEntry("/", true, "OneDrive")
            }

            PanelActionButton {
              iconText: "󰉍"
              tooltipText: "Copy root contents to…"
              hasCursor: root.browserFocus === "root" && root.browserActionIndex === 3
              foreground: root.foreground
              fontFamily: root.fontFamily
              onHovered: function(on) { if (on) { root.browserFocus = "root"; root.browserActionIndex = 3 } }
              onClicked: onedrive.copyEntry("/", true, "OneDrive", true)
            }
          }

          TextField {
            id: searchField
            Layout.fillWidth: true
            placeholderText: "Browse folders"
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            foreground: root.foreground
            text: onedrive.searchQuery
            onTextChanged: if (text !== onedrive.searchQuery) onedrive.updateSearchQuery(text)
            Keys.onEscapePressed: {
              if (text !== "") {
                text = ""
              } else {
                root.closeTreePanel()
                keyCatcher.forceActiveFocus()
              }
            }
            Keys.onDownPressed: {
              root.browserFocus = onedrive.searchResults.length > 0 ? "rows" : "root"
              root.searchIndex = 0
              root.browserActionIndex = root.browserFocus === "rows" ? -1 : 0
              keyCatcher.forceActiveFocus()
            }
            Keys.onUpPressed: {
              root.browserFocus = "root"
              root.browserActionIndex = 0
              keyCatcher.forceActiveFocus()
            }
          }

          Text {
            visible: onedrive.searchQuery.length >= 2 && onedrive.searchError !== ""
            Layout.fillWidth: true
            text: onedrive.searchError
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Text {
            visible: onedrive.searchQuery.length >= 2 && onedrive.searchError === "" && !onedrive.searchReady
            Layout.fillWidth: true
            text: "Index not ready yet"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
          }

          Text {
            visible: onedrive.searchQuery.length >= 2 && onedrive.searchError === "" && onedrive.searchReady
              && !onedrive.searchLoading && onedrive.searchResults.length === 0
            Layout.fillWidth: true
            text: "No matches"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
          }

          Text {
            visible: onedrive.searchQuery.length >= 2 && onedrive.searchTruncated
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: "Showing first " + onedrive.searchResults.length + " matches — refine your search for more"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }

          Text {
            visible: onedrive.searchQuery.length < 2
            Layout.fillWidth: true
            text: onedrive.treeError
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Text {
            visible: onedrive.searchQuery.length < 2 && treeRows.length === 0 && onedrive.treeError === ""
            Layout.fillWidth: true
            text: onedrive.treeLoading ? "Loading folder list…" : "No folders in the index yet."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
          }

          Flickable {
            id: treeOverlayFlick
            visible: onedrive.searchQuery.length < 2
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: treeColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            interactive: contentHeight > height
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Column {
              id: treeColumn
              visible: treeRows.length > 0
              width: treeOverlayFlick.width
              spacing: Style.space(2)

              Repeater {
                model: treeRows
                TreeRow {
                  required property var modelData
                  required property int index
                  width: treeColumn.width
                  row: modelData
                  rowIndex: index
                }
              }
            }
          }

          Flickable {
            id: searchResultsFlick
            visible: onedrive.searchQuery.length >= 2
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: searchResultsColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            interactive: contentHeight > height
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Column {
              id: searchResultsColumn
              width: searchResultsFlick.width
              spacing: Style.space(2)

              Repeater {
                model: onedrive.searchResults
                SearchResultRow {
                  required property var modelData
                  required property int index
                  width: searchResultsColumn.width
                  entry: modelData
                  rowIndex: index
                }
              }
            }
          }

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: onedrive.searchQuery.length >= 2
              ? "↑↓ rows · ←→ actions · Enter run · F open · C copy · X contents · M mail"
              : "↑↓ rows · ←→ actions · Enter run/expand · T terminal · F files · C copy · X contents"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }

  Timer {
    id: phraseTimer
    interval: 2800
    running: root.opened && onedrive.authenticated && onedrive.active && onedrive.pendingCount > 0
    repeat: true
    onTriggered: phraseSwap.restart()
  }

  SequentialAnimation {
    id: phraseSwap
    PropertyAnimation {
      target: hero; property: "metaOpacity"
      to: 0.0; duration: 180; easing.type: Easing.OutQuad
    }
    ScriptAction {
      script: root.phraseIndex = (root.phraseIndex + 1) % root.activePhrases.length
    }
    PropertyAnimation {
      target: hero; property: "metaOpacity"
      to: 1.0; duration: 260; easing.type: Easing.InQuad
    }
  }

  component LoginButton: CursorSurface {
    id: loginButton
    hasCursor: root.cursorActive && root.focusSection === "login"
    foreground: root.foreground
    implicitHeight: loginRow.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: onedrive.installed && !onedrive.busy ? Qt.PointingHandCursor : Qt.ArrowCursor
      enabled: onedrive.installed && !onedrive.busy
      onEntered: {
        root.cursorActive = true
        root.focusSection = "login"
      }
      onClicked: onedrive.reconnect()
    }

    RowLayout {
      id: loginRow
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: "󰌊"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.heading
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: root.loginTitle
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: root.loginSubtitle
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      PanelActionButton {
        iconText: "󰌋"
        foreground: root.foreground
        fontFamily: root.fontFamily
        enabled: onedrive.installed && !onedrive.busy
        Layout.alignment: Qt.AlignVCenter
        onClicked: onedrive.reconnect()
      }
    }
  }

  component ActionRow: CursorSurface {
    id: actionRow
    property int rowIndex: 0
    property string iconText: ""
    property string title: ""
    property string subtitle: ""
    property bool enabled: true

    hasCursor: root.cursorActive && root.focusSection === "actions" && root.actionIndex === rowIndex
    foreground: enabled ? root.foreground : root.dim
    implicitHeight: actionContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      enabled: actionRow.enabled
      cursorShape: actionRow.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onEntered: root.setActionCursor(actionRow.rowIndex)
      onClicked: root.triggerAction(actionRow.rowIndex)
    }

    RowLayout {
      id: actionContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: actionRow.iconText
        color: actionRow.enabled ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: actionRow.title
          color: actionRow.enabled ? root.foreground : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: actionRow.subtitle
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }

  component FileRow: CursorSurface {
    id: fileRow
    property var file: null
    property int rowIndex: 0

    hasCursor: root.cursorActive && root.focusSection === "files" && root.fileIndex === rowIndex
    foreground: root.foreground
    implicitHeight: fileContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setFileCursor(fileRow.rowIndex)
      onClicked: onedrive.openFile(fileRow.file)
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: Model.pendingGlyph(fileRow.file)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        id: fileContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: Model.pendingTitle(fileRow.file)
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: Model.pendingMeta(fileRow.file)
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }

  component TreeRow: CursorSurface {
    id: treeRow
    property var row: null
    property int rowIndex: 0

    hasCursor: root.treePanelOpen && root.browserFocus === "rows"
      && onedrive.searchQuery.length < 2 && root.treeIndex === rowIndex
    foreground: root.foreground
    implicitHeight: treeContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setTreeCursor(treeRow.rowIndex)
      onClicked: root.activateTreeRow(treeRow.row)
    }

    RowLayout {
      id: treeContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10) + (treeRow.row && treeRow.row.depth ? treeRow.row.depth : 0) * Style.space(12)
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(6)

      Text {
        textFormat: Text.PlainText
        text: treeRow.row && treeRow.row.expanded ? "▾" : "▸"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        Layout.preferredWidth: Style.space(10)
      }

      Text {
        textFormat: Text.PlainText
        text: "󰉋"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: treeRow.row ? String(treeRow.row.name || "") : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }
      }

      PanelActionButton {
        iconText: "󰆍"
        tooltipText: "Open terminal here"
        hasCursor: treeRow.hasCursor && root.browserActionIndex === 0
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onHovered: function(on) {
          if (on) {
            root.setTreeCursor(treeRow.rowIndex)
            root.browserActionIndex = 0
          }
        }
        onClicked: root.openTreeTerminal(treeRow.row)
      }

      PanelActionButton {
        iconText: "󰉋"
        tooltipText: "Open in Files"
        hasCursor: treeRow.hasCursor && root.browserActionIndex === 1
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onHovered: function(on) {
          if (on) {
            root.setTreeCursor(treeRow.rowIndex)
            root.browserActionIndex = 1
          }
        }
        onClicked: onedrive.openFolderAt(treeRow.row.path)
      }

      PanelActionButton {
        iconText: "󰆏"
        tooltipText: "Copy folder to…"
        hasCursor: treeRow.hasCursor && root.browserActionIndex === 2
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onHovered: function(on) {
          if (on) {
            root.setTreeCursor(treeRow.rowIndex)
            root.browserActionIndex = 2
          }
        }
        onClicked: onedrive.copyEntry(treeRow.row.path, true, treeRow.row.name)
      }

      PanelActionButton {
        iconText: "󰉍"
        tooltipText: "Copy folder contents to…"
        hasCursor: treeRow.hasCursor && root.browserActionIndex === 3
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onHovered: function(on) {
          if (on) {
            root.setTreeCursor(treeRow.rowIndex)
            root.browserActionIndex = 3
          }
        }
        onClicked: onedrive.copyEntry(treeRow.row.path, true, treeRow.row.name, true)
      }
    }
  }

  component SearchResultRow: CursorSurface {
    id: resultRow
    property var entry: null
    property int rowIndex: 0
    readonly property bool isDir: !!(entry && entry.isDir)

    hasCursor: root.treePanelOpen && root.browserFocus === "rows"
      && onedrive.searchQuery.length >= 2 && root.searchIndex === rowIndex
    foreground: root.foreground
    implicitHeight: resultContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: {
        root.browserFocus = "rows"
        root.searchIndex = resultRow.rowIndex
        root.browserActionIndex = -1
      }
      onClicked: {
        if (resultRow.isDir) onedrive.openFolderAt(resultRow.entry.path)
        else onedrive.openEntry(resultRow.entry.path)
      }
    }

    RowLayout {
      id: resultContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(6)

      Text {
        textFormat: Text.PlainText
        text: resultRow.isDir ? "󰉋" : "󰈔"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: resultRow.entry ? String(resultRow.entry.name || "") : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: resultRow.entry ? String(resultRow.entry.path || "") : ""
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideMiddle
        }
      }

      PanelActionButton {
        visible: resultRow.isDir
        iconText: "󰆍"
        tooltipText: "Open terminal here"
        hasCursor: resultRow.hasCursor && root.browserActionIndex === 0
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: onedrive.openTerminalAt(resultRow.entry.path)
      }

      PanelActionButton {
        visible: resultRow.isDir
        iconText: "󰉋"
        tooltipText: "Open in Files"
        hasCursor: resultRow.hasCursor && root.browserActionIndex === 1
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: onedrive.openFolderAt(resultRow.entry.path)
      }

      PanelActionButton {
        visible: !resultRow.isDir
        iconText: "󰏋"
        tooltipText: "Open"
        hasCursor: resultRow.hasCursor && root.browserActionIndex === 0
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: onedrive.openEntry(resultRow.entry.path)
      }

      PanelActionButton {
        iconText: "󰆏"
        tooltipText: resultRow.isDir ? "Copy folder to…" : "Copy to…"
        hasCursor: resultRow.hasCursor && root.browserActionIndex === (resultRow.isDir ? 2 : 1)
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: onedrive.copyEntry(resultRow.entry.path, resultRow.isDir, resultRow.entry.name)
      }

      PanelActionButton {
        iconText: "󰉍"
        tooltipText: "Copy folder contents to…"
        visible: resultRow.isDir
        hasCursor: resultRow.hasCursor && root.browserActionIndex === 3
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: onedrive.copyEntry(resultRow.entry.path, true, resultRow.entry.name, true)
      }

      PanelActionButton {
        iconText: "󰇮"
        tooltipText: "Mail"
        visible: !resultRow.isDir
        hasCursor: resultRow.hasCursor && root.browserActionIndex === 2
        foreground: root.foreground
        fontFamily: root.fontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: onedrive.mailEntry(resultRow.entry.path)
      }
    }
  }

  component InfoPair: Row {
    property string label: ""
    property string value: ""

    width: parent.width
    spacing: Style.space(8)

    InfoLabel { text: label }
    Item { width: Math.max(0, parent.width - parent.children[0].implicitWidth - parent.children[2].implicitWidth - parent.spacing * 2); height: 1 }
    InfoValue { text: value }
  }

  component InfoLabel: Text {
    textFormat: Text.PlainText
    color: root.foreground
    opacity: 0.6
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  component InfoValue: Text {
    textFormat: Text.PlainText
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    elide: Text.ElideRight
  }
}
