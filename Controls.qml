import QtQuick
import qs.Commons
import qs.Ui as Ui

Column {
  id: root
  spacing: Style.space(10)
  property var snapshot
  property int cursor: 0
  property string message: ""
  readonly property int keyboardCount: snapshot.mode === "cycle" ? 11 : 10
  signal command(string action, var value)
  signal setupRequested()
  signal preferencesRequested()
  signal cursorRequested(int index)

  function activate(index) {
    if (index < 3) {
      var role = snapshot.roles[index]
      if (role) command("preview", role.id)
    } else if (index === 4) command("on")
    else if (index === 5) command("off")
    else if (index === 6) command("follow", snapshot.follow ? "off" : "on")
    else if (index === 7) command("mode", snapshot.mode === "cycle" ? "steady" : "cycle")
    else if (index === 8 && snapshot.mode === "cycle")
      command("speed", snapshot.speed === "slow" ? "medium" : snapshot.speed === "medium" ? "fast" : "slow")
    else if (index === keyboardCount - 2) preferencesRequested()
    else if (index === keyboardCount - 1) setupRequested()
  }
  function cursorItem(index) {
    if (index < 3) return roleChoices.itemAt(index) || roleRow
    if (index === keyboardCount - 1) return setupButton
    if (index === keyboardCount - 2) return preferencesButton
    return [slider, onButton, offButton, followButton, cycleButton, speedButton][index - 3]
  }

  Text {
    text: "NEEWER RGB1"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
  }
  Text {
    width: parent.width
    text: !snapshot.follow && snapshot.connection_state === "offline" ? "Theme following off" :
      snapshot.connection_state === "connecting" ? "Connecting to your light…" :
      snapshot.connection_state === "offline" ? "Light offline · choices will sync when it reconnects" :
      snapshot.connection_state === "ready" ? "Light ready" : "Set up your light"
    color: snapshot.connection_state === "offline" && snapshot.follow ? Color.urgent : Color.foreground
    opacity: 0.8
    wrapMode: Text.Wrap
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
  Text {
    text: "Theme colours" + (snapshot.theme ? " · " + snapshot.theme : "")
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }
  Row {
    id: roleRow
    width: parent.width
    spacing: Style.space(6)
    Repeater {
      id: roleChoices
      model: snapshot.roles || []
      delegate: Item {
        required property var modelData
        required property int index
        width: (root.width - Style.space(12)) / 3
        height: roleButton.implicitHeight + Style.space(6)
        Rectangle {
          width: parent.width
          height: Style.space(4)
          radius: height / 2
          color: modelData.hex || Color.accent
        }
        Ui.Button {
          id: roleButton
          y: Style.space(6)
          width: parent.width
          text: modelData.label
          tooltipText: "Preview " + modelData.label + " now"
          bordered: true
          selected: snapshot.role === modelData.id
          hasCursor: root.cursor === index
          onClicked: root.command("preview", modelData.id)
          onHovered: function(hot) { if (hot) root.cursorRequested(index) }
        }
      }
    }
  }
  Text {
    text: "Brightness · " + Math.round(slider.liveValue) + "%"
    color: root.cursor === 3 ? Color.accent : Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }
  Ui.PanelSlider {
    id: slider
    width: parent.width
    minimum: 0
    maximum: 100
    step: 5
    integer: true
    value: snapshot.brightness || 0
    onReleased: function(value) { root.command("brightness", Math.round(value)) }
  }
  Row {
    width: parent.width
    spacing: Style.space(8)
    Ui.Button {
      id: onButton
      width: (parent.width - parent.spacing) / 2
      text: "On"
      bordered: true
      hasCursor: root.cursor === 4
      onClicked: root.command("on")
      onHovered: function(hot) { if (hot) root.cursorRequested(4) }
    }
    Ui.Button {
      id: offButton
      width: (parent.width - parent.spacing) / 2
      text: "Off"
      bordered: true
      hasCursor: root.cursor === 5
      onClicked: root.command("off")
      onHovered: function(hot) { if (hot) root.cursorRequested(5) }
    }
  }
  Ui.Button {
    id: followButton
    width: parent.width
    text: "Follow theme · " + (snapshot.follow ? "On" : "Off")
    tooltipText: "Keep the Bluetooth link ready and track theme changes. Off stays off until On or a colour preview."
    selected: snapshot.follow
    hasCursor: root.cursor === 6
    onClicked: root.command("follow", snapshot.follow ? "off" : "on")
    onHovered: function(hot) { if (hot) root.cursorRequested(6) }
  }
  Ui.Button {
    id: cycleButton
    width: parent.width
    text: "Cycle theme colours · " + (snapshot.mode === "cycle" ? "On" : "Off")
    tooltipText: "Gently fade between Main, Complement and Alternate. Turning it off holds the current colour."
    bordered: true
    selected: snapshot.mode === "cycle"
    hasCursor: root.cursor === 7
    onClicked: root.command("mode", snapshot.mode === "cycle" ? "steady" : "cycle")
    onHovered: function(hot) { if (hot) root.cursorRequested(7) }
  }
  Ui.Button {
    id: speedButton
    width: parent.width
    visible: snapshot.mode === "cycle"
    text: "Speed · " + (snapshot.speed === "fast" ? "Fast" : snapshot.speed === "medium" ? "Medium" : "Slow")
    tooltipText: "Fade to the next theme colour over 12, 6 or 3 seconds"
    hasCursor: root.cursor === 8
    onClicked: root.command("speed", snapshot.speed === "slow" ? "medium" : snapshot.speed === "medium" ? "fast" : "slow")
    onHovered: function(hot) { if (hot) root.cursorRequested(8) }
  }
  Text {
    width: parent.width
    text: root.message
    visible: text !== ""
    color: snapshot.ok === false ? Color.urgent : Color.foreground
    wrapMode: Text.Wrap
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
  Ui.Button {
    id: preferencesButton
    width: parent.width
    text: "Preferences"
    leftAlign: true
    hasCursor: root.cursor === root.keyboardCount - 2
    onClicked: root.preferencesRequested()
    onHovered: function(hot) { if (hot) root.cursorRequested(root.keyboardCount - 2) }
  }
  Ui.Button {
    id: setupButton
    width: parent.width
    text: "Light setup"
    leftAlign: true
    hasCursor: root.cursor === root.keyboardCount - 1
    onClicked: root.setupRequested()
    onHovered: function(hot) { if (hot) root.cursorRequested(root.keyboardCount - 1) }
  }
}
