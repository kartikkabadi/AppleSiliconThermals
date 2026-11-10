import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Plugin.BarWidget { id: widget }
    property var originalCard: null
    property var originalSlider: null
    property var originalRpm: null
    function find(object, name, seen) {
        if (!object || seen.indexOf(object) >= 0) return null
        seen.push(object)
        if (object.objectName === name) return object
        var groups = [object.children, object.resources, object.contentItem]
        for (var i = 0; i < groups.length; i++) {
            var group = groups[i]
            if (!group) continue
            if (group.length === undefined) group = [group]
            for (var j = 0; j < group.length; j++) {
                var result = find(group[j], name, seen)
                if (result) return result
            }
        }
        return null
    }
    Timer {
        interval: 350; running: true
        onTriggered: {
            originalCard = find(widget, "fan-control-1", [])
            originalSlider = find(originalCard, "fan-target-slider", [])
            originalRpm = widget.fans[0].rpm
            if (!originalSlider) { console.error("ASSERT FAILED: fan slider not found"); Qt.quit(); return }
            originalSlider.dragging = true
            originalSlider.liveValue = 4321
        }
    }
    Timer { interval: 600; running: true; repeat: true; onTriggered: widget.refresh() }
    Timer {
        interval: 2400; running: true
        onTriggered: {
            if (!widget.dataValid || widget.fans.length !== 2) console.error("ASSERT FAILED: repeated telemetry lost fan channels")
            else if (find(widget, "fan-control-1", []) !== originalCard || find(originalCard, "fan-target-slider", []) !== originalSlider) console.error("ASSERT FAILED: telemetry recreated an interactive fan card")
            else if (!originalSlider.dragging || originalSlider.liveValue !== 4321) console.error("ASSERT FAILED: telemetry interrupted the slider gesture")
            else if (widget.fans[0].rpm <= originalRpm) console.error("ASSERT FAILED: test did not receive changed sensor values")
            else console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
}
