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
                widget.setSpeed(3000)
                stage = 30
            } else if (stage === 30) {
                check(widget.savedLinkedRpm === 3000, "Linked has its own explicit saved speed")
                widget.chooseControlMode("individual")
                stage = 2
            } else if (stage === 2) {
                check(widget.savedControlMode === "individual" && widget.separateControls, "Separate is explicit and durable")
                check(widget.fanSelected(widget.fans[0]) === 3000 && widget.fanSelected(widget.fans[1]) === 3000, "first Separate seeds current exact Linked targets")
                widget.setFan(1, 2300)
                widget.setFan(2, 2502, true)
                stage = 3
            } else if (stage === 3) {
                check(widget.fanSelected(widget.fans[0]) === 2300 && widget.fanSelected(widget.fans[1]) === 2502, "unequal individual targets saved")
                widget.chooseControlMode("shared")
                stage = 4
            } else if (stage === 4) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 3000 && widget.savedLinkedRpm === 3000 && !widget.separateControls, "Linked restores its own saved target rather than using Separate maximum")
                widget.setSpeed(4000)
                stage = 40
            } else if (stage === 40) {
                check(widget.savedRpm === 4000 && widget.savedSeparateFans[0].rpm === 2300 && widget.savedSeparateFans[1].rpm === 2502, "changing Linked does not overwrite remembered Separate speeds")
                recreate()
                stage = 5
            } else if (stage === 5) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 4000 && !widget.separateControls, "Linked survives recreation without a new write")
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
                check(widget.savedControlMode === "individual" && widget.fanSelected(widget.fans[0]) === 2300 && widget.fanSelected(widget.fans[1]) === 2502, "Separate restores both remembered unequal exact targets")
                recreate()
                stage = 7
            } else if (stage === 7) {
                check(widget.separateControls && widget.savedControlMode === "individual", "Separate survives recreation without a new write")
                widget.setFan(1, 1600)
                widget.setFan(2, 5000)
                stage = 8
            } else if (stage === 8) {
                widget.chooseControlMode("shared")
                stage = 9
            } else if (stage === 9) {
                check(widget.savedRpm === 4000 && widget.savedLinkedRpm === 4000 && widget.savedSeparateFans[0].rpm === 1600 && widget.savedSeparateFans[1].rpm === 5000, "Linked restores its lower bank without changing higher Separate speeds")
                widget.setSpeed(3000)
                stage = 10
            } else if (stage === 10) {
                var linkedSlider = find(find(widget, "linked-fan-controls", []), "linked-target-slider", [])
                linkedSlider.dragging = true
                linkedSlider.liveValue = 4321
                widget.chooseControlMode("individual")
                check(widget.fanSelected(widget.fans[1]) === 5000, "active Separate previews remembered targets before acknowledgment")
                check(!linkedSlider.dragging && linkedSlider.liveValue === linkedSlider.value, "hiding Linked resets its stale gesture")
                linkedSlider.released(5500)
                widget.setFan(2, 3500) // This pending edit will be canceled by Linked.
                widget.chooseControlMode("shared")
                stage = 11
            } else if (stage === 11) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 3000 && widget.savedLinkedRpm === 3000 && !widget.separateControls, "explicit Linked restores its lower bank after active Separate and cancels fan edits")
                widget.setSpeed(4000) // Keep a Shared command active while both edits queue.
                widget.chooseControlMode("individual")
                check(widget.fanSelected(widget.fans[0]) === 1600 && widget.fanSelected(widget.fans[1]) === 5000, "pending Separate previews the complete remembered profile")
                widget.setFan(2, 3500)
                check(widget.pendingRequests.some(function(request) { return request.kind === "separate" }) && widget.pendingRequests.some(function(request) { return request.kind === "fan" }), "fan edit keeps the earlier queued restore")
                stage = 42
            } else if (stage === 42) {
                check(widget.savedControlMode === "individual" && widget.fanSelected(widget.fans[0]) === 1600 && widget.fanSelected(widget.fans[1]) === 3500, "fan edits after Separate remain ordered and update memory")
                check(widget.savedLinkedRpm === 4000, "Separate fan edit cannot overwrite Linked bank")
                widget.setSpeed(4400) // In-flight scalar update commits before restore.
                widget.chooseControlMode("individual")
                widget.chooseControlMode("shared") // Cancel unsent Separate, queue Linked.
                check(widget.linkedSelectedRpm === 4400, "pending Linked predicts the newer in-flight scalar bank")
                widget.setSpeed(4200) // Slider edit stays after queued Linked.
                check(widget.pendingRequests.some(function(request) { return request.kind === "linked" }) && widget.pendingRequests.some(function(request) { return request.kind === "shared" }), "linked slider edit preserves prior queued restore")
                stage = 43
            } else if (stage === 43) {
                check(widget.savedRpm === 4200 && widget.savedLinkedRpm === 4200 && widget.savedSeparateFans[0].rpm === 1600 && widget.savedSeparateFans[1].rpm === 3500, "queued Linked then slider settles on the later scalar without changing Separate bank")
                widget.setSpeed("auto")
                widget.chooseControlMode("individual")
                stage = 12
            } else if (stage === 12) {
                check(widget.savedMode === "auto" && !widget.separateControls, "Auto keeps precedence over layout changes")
                widget.enableManual()
                stage = 13
            } else if (stage === 13) {
                check(widget.savedControlMode === "shared" && widget.savedRpm === 4200 && !widget.separateControls, "Manual after Auto restores remembered Linked speed")
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
    Timer { interval: 11000; running: true; onTriggered: { console.error("ASSERT FAILED: layout mode sequence timed out at stage " + stage); Qt.quit() } }
}
