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
            console.log("READY_REMOVE_HELPER")
            request.start()
        }
    }
    Timer {
        id: request; interval: 250
        onTriggered: {
            widget.setSpeed("4000")
            widget.setSpeed("auto")
            console.log("RESTORE_HELPER")
            verifyFailedStart.start()
            finish.start()
        }
    }
    Timer {
        id: verifyFailedStart; interval: 1000
        onTriggered: if (!widget.writeBusy || widget.pendingRequests.length !== 1)
            console.error("ASSERT FAILED: missing-executable write/queued Auto path was not exercised")
    }
    Timer {
        id: finish; interval: 7600
        onTriggered: {
            if (widget.writeBusy || widget.pendingRequests.length || widget.mode !== "auto" || widget.savedMode !== "auto") console.error("ASSERT FAILED: queued Auto did not recover after helper restoration")
            else console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
    Timer { interval: 11000; running: true; onTriggered: { console.error("ASSERT FAILED: Auto recovery test timed out"); Qt.quit() } }
}
