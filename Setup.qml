import QtQuick
import qs.Commons
import qs.Ui as Ui

Column {
  id: root
  spacing: Style.space(10)
  property var snapshot
  property bool canReturn: false
  property bool installing: false
  property bool installFailed: false
  property int cursor: 0
  property string message: ""
  readonly property bool backendReady: snapshot.backend_ready === true
  readonly property bool controlsEnabled: backendReady && !installing
  readonly property int keyboardCount: backendReady ? 1 + (snapshot.devices || []).length +
    (snapshot.configured ? 1 : 0) + (snapshot.test_success && !snapshot.setup_complete ? 1 : 0) +
    (canReturn ? 1 : 0) : 1
  signal command(string action, var value)
  signal backRequested()
  signal cursorRequested(int index)
  onCursorChanged: {
    if (cursor > 0 && cursor <= (snapshot.devices || []).length)
      deviceList.positionViewAtIndex(cursor - 1, ListView.Contain)
  }

  function activate(index) {
    if (!backendReady) {
      if (!installing) command("install")
      return
    }
    if (installing) return
    if (index === 0) { if (!snapshot.scanning) command("scan"); return }
    var devices = snapshot.devices || []
    if (index <= devices.length) { command("select", devices[index - 1].address); return }
    index -= devices.length + 1
    if (snapshot.configured) {
      if (index === 0) { command("test"); return }
      index--
    }
    if (snapshot.test_success && !snapshot.setup_complete) {
      if (index === 0) { command("confirm"); return }
      index--
    }
    if (canReturn && index === 0) backRequested()
  }
  function cursorItem(index) {
    if (!backendReady) return enableButton
    if (index === 0) return findButton
    var count = (snapshot.devices || []).length
    if (index <= count) return deviceList
    index -= count + 1
    if (snapshot.configured) { if (index === 0) return testButton; index-- }
    if (snapshot.test_success && !snapshot.setup_complete) {
      if (index === 0) return confirmButton
      index--
    }
    return canReturn && index === 0 ? backButton : null
  }

  Text {
    text: !backendReady ? "Enable light controls" :
      snapshot.configured ? "Light setup" : "Set up your RGB1"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
  }
  Text {
    width: parent.width
    text: !backendReady ? "One-time setup needs internet access. It installs local Bluetooth controls that run at login. No account or administrator password is needed." :
      snapshot.configured ? "Your RGB1 is saved. Test the connection or choose another light." :
      "1. Switch your RGB1 on and turn on computer Bluetooth.\n2. Disconnect the phone app. System Bluetooth pairing is not needed.\n3. Find your light, select it, test a colour, then confirm it looks right."
    color: Color.foreground
    wrapMode: Text.Wrap
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }
  Text {
    width: parent.width
    visible: backendReady && (!snapshot.configured || snapshot.connection_state !== "ready")
    text: "If it is not found, hold the button marked 2.4G for about 1.5 seconds until Bluetooth flashes, then try again. If the phone still holds the link, turn Bluetooth off in the phone's Settings."
    color: Color.foreground
    opacity: 0.75
    wrapMode: Text.Wrap
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
  Ui.Button {
    id: enableButton
    width: parent.width
    visible: !backendReady
    text: installing ? "Enabling light controls…" :
      installFailed ? "Try setup again" : "Enable light controls"
    bordered: true
    enabled: !installing
    hasCursor: root.cursor === 0
    onClicked: root.command("install")
    onHovered: function(hot) { if (hot) root.cursorRequested(0) }
  }
  Ui.Button {
    id: findButton
    width: parent.width
    visible: backendReady
    text: snapshot.scanning ? "Finding light…" : "Find light"
    bordered: true
    enabled: controlsEnabled && !snapshot.scanning
    hasCursor: root.cursor === 0
    onClicked: root.command("scan")
    onHovered: function(hot) { if (hot) root.cursorRequested(0) }
  }
  ListView {
    id: deviceList
    width: parent.width
    height: Math.max(0, Math.min(contentHeight, Style.space(160)))
    clip: true
    interactive: contentHeight > height
    spacing: Style.space(4)
    visible: backendReady
    model: snapshot.devices || []
    delegate: Ui.Button {
      required property var modelData
      required property int index
      width: deviceList.width
      text: modelData.label || "RGB1 light"
      leftAlign: true
      bordered: true
      enabled: root.controlsEnabled
      hasCursor: root.cursor === index + 1
      onClicked: root.command("select", modelData.address)
      onHovered: function(hot) { if (hot) root.cursorRequested(index + 1) }
    }
  }
  Text {
    width: parent.width
    visible: backendReady && snapshot.scanning && (!snapshot.devices || snapshot.devices.length === 0)
    text: "Looking for nearby RGB1 lights…"
    color: Color.foreground
    opacity: 0.75
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
  Text {
    width: parent.width
    visible: backendReady && snapshot.configured
    text: snapshot.connection_state === "connecting" ? "Connecting to your saved light…" :
      snapshot.connection_state === "ready" ? "Saved light connected" : "Saved light · currently offline"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
  Ui.Button {
    id: testButton
    width: parent.width
    visible: backendReady && snapshot.configured
    text: "Test colour"
    bordered: true
    enabled: controlsEnabled
    hasCursor: root.cursor === 1 + (snapshot.devices || []).length
    onClicked: root.command("test")
    onHovered: function(hot) { if (hot) root.cursorRequested(1 + (snapshot.devices || []).length) }
  }
  Row {
    width: parent.width
    visible: backendReady && snapshot.test_success && !snapshot.setup_complete
    spacing: Style.space(8)
    Rectangle {
      width: Style.space(18)
      height: width
      radius: width / 2
      color: snapshot.last_colour || snapshot.hex
    }
    Text {
      text: (snapshot.last_theme || snapshot.theme) + " · " +
        (snapshot.last_role === "complementary" ? "Complement" :
         snapshot.last_role === "alternate" ? "Alternate" : "Main")
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }
  Text {
    width: parent.width
    visible: backendReady && snapshot.test_success && !snapshot.setup_complete
    text: "Did your light change to this colour?"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }
  Ui.Button {
    id: confirmButton
    width: parent.width
    visible: backendReady && snapshot.test_success && !snapshot.setup_complete
    text: "Looks right"
    bordered: true
    enabled: controlsEnabled
    hasCursor: root.cursor === 1 + (snapshot.devices || []).length + (snapshot.configured ? 1 : 0)
    onClicked: root.command("confirm")
    onHovered: function(hot) { if (hot) root.cursorRequested(1 + (snapshot.devices || []).length + (snapshot.configured ? 1 : 0)) }
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
    id: backButton
    width: parent.width
    visible: backendReady && root.canReturn
    text: "Back to controls"
    hasCursor: root.cursor === root.keyboardCount - 1
    onClicked: root.backRequested()
    onHovered: function(hot) { if (hot) root.cursorRequested(root.keyboardCount - 1) }
  }
}
