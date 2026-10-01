import QtQuick
import qs.Commons
import qs.Ui as Ui

Column {
  id: root
  spacing: Style.space(10)
  property var snapshot
  property int cursor: 0
  readonly property int keyboardCount: 4
  signal command(string action, var value)
  signal cursorRequested(int index)
  signal backRequested()

  function activate(index) {
    if (index === 0) command("fade", snapshot.theme_fade === "gentle" ? "quick" : snapshot.theme_fade === "quick" ? "off" : "gentle")
    else if (index === 1) command("lock-off", snapshot.off_when_locked ? "off" : "on")
    else if (index === 2) command("shutdown-off", snapshot.off_on_shutdown ? "off" : "on")
    else if (index === 3) backRequested()
  }
  function cursorItem(index) { return [fadeButton, lockButton, shutdownButton, backButton][index] }

  Text {
    text: "Light preferences"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
  }
  Ui.Button {
    id: fadeButton
    width: parent.width
    text: "Theme fade · " + (snapshot.theme_fade === "off" ? "Off" : snapshot.theme_fade === "quick" ? "Quick" : "Gentle")
    tooltipText: "Gentle: 1 second. Quick: 0.42 seconds. Off: immediate. Colour previews are always immediate."
    bordered: true
    hasCursor: root.cursor === 0
    onClicked: root.activate(0)
    onHovered: function(hot) { if (hot) root.cursorRequested(0) }
  }
  Text {
    width: parent.width
    text: "Theme fade happens once when you switch themes. Cycle repeats through the palette."
    color: Color.foreground
    opacity: 0.8
    wrapMode: Text.Wrap
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
  Ui.Button {
    id: lockButton
    width: parent.width
    text: "Off when locked · " + (snapshot.off_when_locked ? "On" : "Off")
    tooltipText: "Restore on unlock only if locking turned the light off. Manual Off stays off."
    selected: snapshot.off_when_locked
    bordered: true
    hasCursor: root.cursor === 1
    onClicked: root.activate(1)
    onHovered: function(hot) { if (hot) root.cursorRequested(1) }
  }
  Ui.Button {
    id: shutdownButton
    width: parent.width
    text: "Off on shutdown · " + (snapshot.off_on_shutdown ? "On" : "Off")
    tooltipText: "Send Off before a normal shutdown or restart. Requires a reachable light; sudden power loss cannot send a command."
    selected: snapshot.off_on_shutdown
    bordered: true
    hasCursor: root.cursor === 2
    onClicked: root.activate(2)
    onHovered: function(hot) { if (hot) root.cursorRequested(2) }
  }
  Text {
    width: parent.width
    visible: text !== ""
    text: snapshot.off_when_locked && snapshot.lock_monitor === "unavailable" ? "Lock notifications are unavailable in this session." :
      snapshot.off_on_shutdown && snapshot.shutdown_monitor === "unavailable" ? "Shutdown notifications are unavailable in this session." : ""
    color: Color.urgent
    wrapMode: Text.Wrap
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
  Ui.Button {
    id: backButton
    width: parent.width
    text: "Back"
    hasCursor: root.cursor === 3
    onClicked: root.backRequested()
    onHovered: function(hot) { if (hot) root.cursorRequested(3) }
  }
}
