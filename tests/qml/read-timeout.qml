import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Plugin.BarWidget { id: widget }
    Timer {
        interval: 7600; running: true
        onTriggered: {
            if (!widget.dataValid || widget.readBusy) console.error("ASSERT FAILED: timed-out reader blocked later fresh telemetry")
            else console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
}
