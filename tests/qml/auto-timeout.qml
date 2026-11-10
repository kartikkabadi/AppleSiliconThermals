import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Plugin.BarWidget { id: widget }
    property bool started: false
    Timer {
        interval: 50; running: true; repeat: true
        onTriggered: if (!started && widget.dataValid) {
            started = true
            widget.setSpeed("4300")
            widget.setSpeed("auto")
            finish.start()
        }
    }
    Timer {
        id: finish; interval: 7600
        onTriggered: {
            if (widget.writeBusy || widget.pendingRequests.length || widget.savedMode !== "auto" || widget.controlError !== "") console.error("ASSERT FAILED: killed write child completed or blocked a later Auto request")
            else console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
    Timer { interval: 11000; running: true; onTriggered: { console.error("ASSERT FAILED: child timeout test timed out"); Qt.quit() } }
}
