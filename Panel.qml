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
  property bool cursorActive: false
  property int phraseIndex: 0

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
  readonly property string loginTitle: !onedrive.installed
    ? "rclone is not installed"
    : (onedrive.authenticated ? "Reconnect OneDrive" : "Authorize OneDrive")
  readonly property string loginSubtitle: !onedrive.installed
    ? "Install rclone and configure a OneDrive remote first"
    : (!onedrive.serviceExists
      ? "Create " + onedrive.serviceUnit + " after authorizing the remote"
      : "Open rclone's OAuth flow in the browser")

  function heroMetaText() {
    if (onedrive.lastError !== "") return onedrive.lastError
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

  function ensureCursor() {
    if (!onedrive.authenticated) {
      focusSection = "login"
      return
    }
    if (focusSection !== "header" && focusSection !== "actions" && focusSection !== "files") focusSection = "header"
    if (fileIndex >= onedrive.pendingFiles.length) fileIndex = Math.max(0, onedrive.pendingFiles.length - 1)
    if (fileIndex < 0) fileIndex = 0
    if (actionIndex < 0) actionIndex = 0
    if (actionIndex > 2) actionIndex = 2
    if (focusSection === "files" && onedrive.pendingFiles.length === 0) focusSection = "actions"
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
      if (dx < 0) actionIndex = Math.max(0, actionIndex - 1)
      if (dx > 0) actionIndex = Math.min(2, actionIndex + 1)
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

  function triggerAction(index) {
    if (index === 0) onedrive.syncNow()
    else if (index === 1) onedrive.openFolder()
    else if (index === 2) onedrive.reconnect()
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

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) {
    cursorActive = false
    if (panelFlick) panelFlick.contentY = 0
    onedrive.refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
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
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
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
                  error: onedrive.lastError !== ""
                }
              }
              trailingControl: Component {
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
            spacing: Style.spacing.labelGap

            InfoPair { label: "Status"; value: onedrive.statusText }
            InfoPair { label: "Remote"; value: onedrive.remoteName }
            InfoPair { label: "Unit"; value: onedrive.serviceUnit }
            InfoPair { label: "Service"; value: root.stateText(onedrive.running, "Running", (onedrive.serviceExists ? "Stopped" : "Missing")) }
            InfoPair { label: "Mounted"; value: root.stateText(onedrive.mounted, "Yes", "No") }
            InfoPair { label: "Auth"; value: root.stateText(onedrive.authenticated, "Ready", "Required") }
            InfoPair { label: "RC"; value: root.stateText(onedrive.rcAvailable, "Reachable", "Unavailable") }
            InfoPair { label: "Mount"; value: onedrive.mountPointExpanded }
            InfoPair { label: "Last sync"; value: Model.relativeTime(onedrive.lastSyncTs) }
            InfoPair { label: "Pending"; value: String(onedrive.pendingCount) }
            InfoPair { label: "Queued"; value: Model.formatBytes(onedrive.bytesQueued) }
            InfoPair { label: "Transferred"; value: Model.formatBytes(onedrive.transferredBytes) }
          }

          PanelSeparator {
            visible: onedrive.authenticated || root.showHero
            foreground: root.foreground
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
                iconText: "󰑐"
                title: "Sync now"
                subtitle: !onedrive.installed
                  ? "Install rclone first"
                  : (!onedrive.running
                    ? "Start " + onedrive.serviceUnit + " first"
                    : (onedrive.rcAvailable
                      ? "Request a VFS refresh through rclone RC"
                      : "Enable --rc on the rclone service"))
                enabled: onedrive.canSyncNow
              }

              ActionRow {
                width: parent.width
                rowIndex: 1
                iconText: "󰉋"
                title: "Open folder"
                subtitle: onedrive.mounted ? "Open the active OneDrive mount in Files" : "Open the configured mount folder"
                enabled: onedrive.canOpenFolder
              }

              ActionRow {
                width: parent.width
                rowIndex: 2
                iconText: "󰌋"
                title: onedrive.authenticated ? "Reconnect" : "Authorize"
                subtitle: onedrive.authenticated
                  ? "Start rclone's OAuth re-authorization flow"
                  : "Finish remote authorization without exposing tokens to QML"
                enabled: onedrive.canReconnect
              }
            }
          }

          PanelSeparator {
            visible: onedrive.authenticated
            foreground: root.foreground
          }

          Column {
            visible: onedrive.authenticated
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

            Text {
              visible: onedrive.authenticated || root.showHero
              width: parent.width
              textFormat: Text.PlainText
              text: "Shortcuts: R refresh · P pause/resume · O open folder · C authorize"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }
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
