import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Plugin.BarWidget { id: widget }
    Timer {
        interval: 250; running: true
        onTriggered: {
            widget.controlAvailable = true
            widget.fanControlEnabled = true
            widget.dataValid = true
            widget.setSpeed("4000")
        }
    }
    Timer {
        interval: 7400; running: true
        onTriggered: {
            if (!widget.dataValid || widget.readBusy || widget.writeBusy || widget.leaseArmed) console.error("ASSERT FAILED: startup failure did not recover")
            else console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
}
