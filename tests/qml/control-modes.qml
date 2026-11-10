import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Component { id: widgetComponent; Plugin.BarWidget {} }
    Loader { id: loader; sourceComponent: widgetComponent }
    property int stage: 0
    property bool failed: false
    function check(condition, message) {
        if (!condition) { failed = true; console.error("ASSERT FAILED: " + message); Qt.quit() }
    }
    function recreate() { loader.active = false; Qt.callLater(function() { loader.active = true }) }
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
        interval: 50; running: true; repeat: true
        onTriggered: {
            var widget = loader.item
            if (failed || !widget || !widget.dataValid || widget.writeBusy || widget.pendingRequests.length) return
            if (stage === 0) {
                check(!widget.separateControls && widget.savedMode === "auto", "fresh Auto defaults to Linked without writing")
                widget.enableManual()
                stage = 1
            } else if (stage === 1) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 2500 && !widget.separateControls, "Manual starts one linked target")
                widget.chooseControlMode("individual")
                stage = 2
            } else if (stage === 2) {
                check(widget.savedControlMode === "individual" && widget.separateControls, "Separate is explicit and durable")
                check(widget.fanSelected(widget.fans[0]) === 2500 && widget.fanSelected(widget.fans[1]) === 2500, "Shared to Separate preserves both targets")
                widget.setFan(1, 2300)
                widget.setFan(2, 2502, true)
                stage = 3
            } else if (stage === 3) {
                check(widget.fanSelected(widget.fans[0]) === 2300 && widget.fanSelected(widget.fans[1]) === 2502, "unequal individual targets saved")
                widget.chooseControlMode("shared")
                stage = 4
            } else if (stage === 4) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 2502 && !widget.separateControls, "Linked synchronizes to exact highest target without lowering")
                recreate()
                stage = 5
            } else if (stage === 5) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 2502 && !widget.separateControls, "Linked survives recreation without a new write")
                var linked = find(widget, "linked-fan-controls", [])
                var separate = find(widget, "fan-control-1", [])
                check(linked && separate && linked.snap(linked.maximum * 0.25) === 1550 && separate.snap(separate.maximum * 0.25) === 1450, "Linked and Separate use their correct distinct preset ranges")
                var linkedSlider = find(linked, "linked-target-slider", [])
                linkedSlider.dragging = true
                linkedSlider.liveValue = 4321
                widget.chooseControlMode("individual")
                check(!linkedSlider.dragging && linkedSlider.liveValue === linkedSlider.value, "hiding Linked cancels its drag state")
                linkedSlider.released(5500)
                check(!widget.pendingRequests.some(function(request) { return request.kind === "shared" }), "hidden Linked release cannot undo Separate")
                stage = 6
            } else if (stage === 6) {
                check(widget.savedControlMode === "individual" && widget.fanSelected(widget.fans[0]) === 2502 && widget.fanSelected(widget.fans[1]) === 2502, "Separate preserves an exact non-step shared target")
                recreate()
                stage = 7
            } else if (stage === 7) {
                check(widget.separateControls && widget.savedControlMode === "individual", "Separate survives recreation without a new write")
                widget.setSpeed(4000)
                stage = 8
            } else if (stage === 8) {
                widget.setFan(1, 1600) // In flight; queued Shared is then canceled.
                widget.chooseControlMode("shared")
                widget.chooseControlMode("individual")
                stage = 9
            } else if (stage === 9) {
                check(widget.savedControlMode === "individual" && widget.fanSelected(widget.fans[0]) === 1600 && widget.fanSelected(widget.fans[1]) === 4000, "canceled Linked target cannot leak into Separate")
                widget.setFan(2, 5000)
                stage = 10
            } else if (stage === 10) {
                var separateSlider = find(find(widget, "fan-control-1", []), "fan-target-slider", [])
                separateSlider.dragging = true
                separateSlider.liveValue = 4321
                widget.setFan(1, 1200)
                widget.setFan(2, 1200) // Pending lower preview must not hide saved 5000.
                widget.chooseControlMode("shared")
                check(!separateSlider.dragging && separateSlider.liveValue === separateSlider.value, "hiding Separate cancels its drag state")
                separateSlider.released(2300)
                check(!widget.pendingRequests.some(function(request) { return request.kind === "fan" }), "hidden Separate release cannot undo Linked")
                stage = 11
            } else if (stage === 11) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 5000 && !widget.separateControls, "Linked protects observed/saved highest target when pending edits are lower")
                widget.setSpeed("auto")
                widget.chooseControlMode("individual")
                stage = 12
            } else if (stage === 12) {
                check(widget.savedMode === "auto" && !widget.separateControls, "Auto keeps precedence over layout changes")
                widget.enableManual()
                stage = 13
            } else if (stage === 13) {
                check(widget.savedControlMode === "shared" && !widget.separateControls, "re-entering Manual after Auto defaults to Linked")
                widget.setFan(1, 2000)
                widget.chooseControlMode("shared")
                widget.invalidate("fixture sensor failure while changing layouts")
                stage = 14
            } else if (stage === 14) {
                check(widget.manualControlChoice === "" && widget.savedControlMode === "individual" && widget.separateControls, "aborted queued layout cannot leave a stale local override after fresh status")
                console.log("WIDGET TEST PASSED")
                stage = 15
                Qt.quit()
            }
        }
    }
    Timer { interval: 10000; running: true; onTriggered: { console.error("ASSERT FAILED: layout mode sequence timed out at stage " + stage); Qt.quit() } }
}
