import QtQuick
import qs.Commons

Item {
  id: root

  property real iconSize: Style.font.icon
  property color color: Color.foreground
  property bool active: false
  property bool syncing: false
  property bool error: false

  width: iconSize * 1.15
  height: iconSize
  implicitWidth: width
  implicitHeight: height

  Text {
    id: glyph
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: root.error ? "󰅚" : (root.syncing ? "󰅠" : (root.active ? "󰅟" : "󰅞"))
    color: root.color
    opacity: root.active ? 1.0 : 0.65
    font.family: Style.font.family
    font.pixelSize: root.iconSize
  }

  SequentialAnimation on opacity {
    running: root.syncing && !root.error
    loops: Animation.Infinite
    PropertyAnimation { to: 0.65; duration: 650; easing.type: Easing.InOutQuad }
    PropertyAnimation { to: 1.0; duration: 650; easing.type: Easing.InOutQuad }
  }
}
