import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

Ui.Panel {
  id: root
  moduleName: "io.github.tomdavenport.neewer"
  manageIpc: false
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  property var snapshot: ({ ok: true, configured: false, setup_complete: false,
    test_success: false, connection_state: "unconfigured", scanning: false,
    devices: [], theme: "", role: "accent", roles: [], hex: "#ffffff",
    brightness: 20, follow: true, mode: "steady", speed: "slow", last_sent: "", last_requested_power: "",
    message: "" })
  property bool initialized: false
  property bool hadSavedLight: false
  property bool setupVisible: false
  property bool awaitingConfirm: false
  property bool installing: false
  property bool installFailed: false
  property bool returnToControlsOnReady: false
  property int cursor: 0
  property string localError: ""
  property var pendingActions: []
  property string activeAction: ""
  readonly property string displayMessage: localError ||
    (installing ? "Setting up the local Bluetooth helper and service. This can take about a minute." :
     snapshot.message || "")
  readonly property string controlScript: bundledScriptPath()

  function bundledScriptPath() {
    var url = Qt.resolvedUrl("scripts/control.sh").toString()
    if (url.indexOf("file://") !== 0) return ""
    try {
      var path = decodeURIComponent(url.slice(7))
      return path.indexOf("/") === 0 ? path : ""
    } catch (error) {
      return ""
    }
  }

  function accept(raw) {
    try {
      var next = JSON.parse(String(raw))
      if (next && next.ok === false && !Array.isArray(next.roles)) {
        localError = next.message || "Light controls are unavailable."
        return
      }
      if (!next || typeof next !== "object" || !Array.isArray(next.roles))
        throw new Error("Invalid light state")
      if (JSON.stringify(next.roles) === JSON.stringify(snapshot.roles))
        next.roles = snapshot.roles
      var leavingCycle = snapshot.mode === "cycle" && next.mode !== "cycle"
      snapshot = next
      if (next.backend_ready === true) installFailed = false
      if (next.backend_ready === false) {
        setupVisible = true
        cursor = 0
      }
      if (leavingCycle && !setupVisible && cursor >= 8)
        cursor = cursor === 8 ? 7 : 8
      localError = ""
      if (!initialized) {
        initialized = true
        hadSavedLight = !!next.setup_complete
        setupVisible = !next.setup_complete || next.backend_ready === false
      }
      if (awaitingConfirm && next.setup_complete) {
        awaitingConfirm = false
        hadSavedLight = true
        setupVisible = false
        cursor = 0
      }
      if (returnToControlsOnReady && next.backend_ready === true && next.setup_complete) {
        hadSavedLight = true
        setupVisible = false
        cursor = 0
        returnToControlsOnReady = false
      }
    } catch (error) {
      localError = "Could not read the light state. Open Light setup to try again."
    }
  }

  function issue(action, value) {
    if ((!initialized && action !== "status") || !controlScript ||
        installing) return
    if (action === "install") {
      installing = true
      installFailed = false
      returnToControlsOnReady = true
      localError = ""
    }
    var queue = pendingActions.slice()
    queue.push({ action: action, value: value })
    pendingActions = queue
    startNext()
  }
  function startNext() {
    if (control.running || pendingActions.length === 0) return
    var queue = pendingActions.slice()
    var next = queue.shift()
    pendingActions = queue
    activeAction = next.action
    var args = ["bash", controlScript, next.action]
    if (next.value !== undefined) args.push(String(next.value))
    control.command = args
    control.running = true
  }
  function move(delta) {
    if (!initialized) return
    var count = setupVisible ? setup.keyboardCount : controls.keyboardCount
    if (count > 0) cursor = (cursor + delta + count) % count
  }
  function activate() {
    if (!initialized) return
    if (setupVisible) setup.activate(cursor)
    else controls.activate(cursor)
  }
  function closeOrBack() {
    if (setupVisible && hadSavedLight && snapshot.backend_ready === true) {
      setupVisible = false
      cursor = 0
    } else close()
  }
  function ensureCursorVisible() {
    if (!opened) return
    var target = setupVisible ? setup.cursorItem(cursor) : controls.cursorItem(cursor)
    if (!target || scroll.height <= 0) return
    var top = target.mapToItem(content, 0, 0).y
    var bottom = top + target.height
    if (top < scroll.contentY) scroll.contentY = top
    else if (bottom > scroll.contentY + scroll.height)
      scroll.contentY = bottom - scroll.height
  }
  onCursorChanged: Qt.callLater(root.ensureCursorVisible)
  onSetupVisibleChanged: { scroll.contentY = 0; Qt.callLater(root.ensureCursorVisible) }
  onOpenedChanged: if (opened) { issue("status"); Qt.callLater(root.ensureCursorVisible) }

  FileView {
    path: Quickshell.env("HOME") + "/.local/state/neewer-omarchy/status.json"
    watchChanges: true
    onLoaded: root.accept(text())
    onFileChanged: reload()
  }
  Process {
    id: control
    stdout: StdioCollector { onStreamFinished: root.accept(text) }
    onExited: function(code, status) {
      var finishedAction = root.activeAction
      root.activeAction = ""
      if (finishedAction === "install") {
        root.installing = false
        root.installFailed = code !== 0
      }
      if (code !== 0 && !root.localError && root.snapshot.ok !== false) {
        root.localError = finishedAction === "install" ?
          "Setup could not finish. Check your connection, then try again." :
          "The light did not respond. Try a colour preview or Light setup."
      }
      Qt.callLater(root.startNext)
    }
  }

  Ui.BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰌵"
    active: root.opened
    tooltipText: "NEEWER RGB1 · light controls"
    onPressed: root.toggle()
  }
  Ui.KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keys
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(600))
    Ui.PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.closeOrBack()
      onTabRequested: function(direction) { root.move(direction) }
      onMoveRequested: function(dx, dy) {
        if (dy) root.move(dy)
        else if (!root.setupVisible && root.cursor === 3)
          root.issue("brightness", Math.max(0, Math.min(100, root.snapshot.brightness + dx * 5)))
        else root.move(dx)
      }
      onActivateRequested: root.activate()
      Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column {
          id: content
          width: scroll.width
          spacing: Style.space(12)
          Text {
            width: parent.width
            visible: !root.initialized
            text: "Checking light controls…"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }
          Controls {
            id: controls
            width: parent.width
            visible: root.initialized && !root.setupVisible
            snapshot: root.snapshot
            cursor: root.cursor
            message: root.displayMessage
            onCommand: function(action, value) { root.issue(action, value) }
            onCursorRequested: function(index) { root.cursor = index }
            onSetupRequested: { root.setupVisible = true; root.cursor = 0 }
          }
          Setup {
            id: setup
            width: parent.width
            visible: root.initialized && root.setupVisible
            snapshot: root.snapshot
            canReturn: root.hadSavedLight
            cursor: root.cursor
            message: root.displayMessage
            installing: root.installing
            installFailed: root.installFailed
            onCursorRequested: function(index) { root.cursor = index }
            onCommand: function(action, value) {
              if (action === "confirm") root.awaitingConfirm = true
              root.issue(action, value)
            }
            onBackRequested: { root.setupVisible = false; root.cursor = 0 }
          }
        }
      }
    }
  }
}
