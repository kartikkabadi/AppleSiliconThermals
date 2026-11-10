import QtQuick
import QtQuick.Window
import QtTest
import Quickshell
import "Plugin" as Plugin

Scope {
    id: test
    property int clicks: 0
    property int stage: 0
    property bool failed: false
    Plugin.BarWidget { id: widget }
    Window {
        id: keyboardWindow
        visible: true
        width: 240; height: 120
        Plugin.AccessibleButton {
            id: probe
            anchors.centerIn: parent
            text: "Manual"
            checkable: true
            selected: true
            focusable: true
            onClicked: test.clicks++
        }
        TestEvent { id: keyboard }
    }
    function check(condition, message) {
        if (!condition) { failed = true; console.error("ASSERT FAILED: " + message); Qt.quit() }
    }
    function find(object, name, seen) {
        if (!object || seen.indexOf(object) >= 0) return null
        seen.push(object)
        if (object.objectName === name) return object
        var groups = [object.children, object.resources, object.contentItem]
        for (var i = 0; i < groups.length; i++) {
            var group = groups[i]
            if (!group) continue
            if (group.length === undefined) group = [group]
            for (var j = 0; j < group.length; j++) { var result = find(group[j], name, seen); if (result) return result }
        }
        return null
    }
    Timer {
        interval: 100; running: true; repeat: true
        onTriggered: {
            if (failed || !widget.dataValid || widget.writeBusy || widget.pendingRequests.length) return
            if (stage === 0) {
                check(probe.Accessible.role === Accessible.Button && probe.Accessible.name === "Manual", "accessible role and name")
                check(probe.Accessible.checkable && probe.Accessible.checked, "selected state exposed")
                probe.Accessible.pressAction()
                check(clicks === 1, "assistive press invokes the actual click handler")
                probe.enabled = false
                probe.Accessible.pressAction()
                check(clicks === 1, "disabled assistive activation is blocked")
                probe.enabled = true; probe.visible = false
                probe.Accessible.pressAction()
                check(clicks === 1, "hidden assistive activation is blocked")
                probe.visible = true
                keyboardWindow.requestActivate()
                probe.forceActiveFocus()
                stage = 1
            } else if (stage === 1) {
                check(probe.activeFocus && keyboard.keyClick(Qt.Key_Return, Qt.NoModifier, 0), "real Return key event targets the focused button")
                check(clicks === 2, "Return activates the actual click handler")
                check(keyboard.keyClick(Qt.Key_Space, Qt.NoModifier, 0) && clicks === 3, "Space activates the actual click handler")
                var manual = find(widget, "mode-manual", [])
                var auto = find(widget, "mode-auto", [])
                var details = find(widget, "sensor-details", [])
                var barButton = find(widget, "thermals-bar-button", [])
                check(manual.Accessible.role === Accessible.Button && manual.Accessible.checkable && !manual.Accessible.checked, "mode selector semantics reflect actual state")
                check(auto.Accessible.checked && barButton.Accessible.name !== "", "Auto state and bar label exposed")
                details.Accessible.pressAction()
                check(widget.detailsOpen && details.Accessible.checked, "accessible details action toggles actual product state")
                manual.Accessible.pressAction()
                stage = 2
            } else if (stage === 2) {
                var manual = find(widget, "mode-manual", [])
                check(widget.desiredManual && manual.Accessible.checked, "assistive Manual action persisted actual control selection")
                find(widget, "layout-separate", []).Accessible.pressAction()
                stage = 3
            } else if (stage === 3) {
                check(widget.separateControls && find(widget, "layout-separate", []).Accessible.checked, "assistive layout action updates actual separate mode")
                console.log("WIDGET TEST PASSED")
                stage = 4
                Qt.quit()
            }
        }
    }
    Timer { interval: 6000; running: true; onTriggered: { console.error("ASSERT FAILED: accessibility sequence timed out at stage " + stage); Qt.quit() } }
}
