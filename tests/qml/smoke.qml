import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Plugin.BarWidget { id: widget }
    function check(condition, message) {
        if (!condition) { console.error("ASSERT FAILED: " + message); Qt.quit() }
    }
    Timer {
        interval: 350; running: true
        onTriggered: {
            check(widget.dataValid, "fixture loaded")
            check(widget.mode === "auto" && !widget.manualMode, "positive targets do not infer manual mode")
            check(widget.maxTemp === 0 && widget.powerWatts === 0 && widget.sensors.battery === null, "zero and missing values")
            check(widget.fans[0].label.indexOf("<img") === 0, "markup is plain text")
            widget.setSpeed("4000")
            widget.setSpeed("4500")
            widget.setSpeed("auto")
            widget.setSpeed("5000") // Must not override the pending Auto.
        }
    }
    Timer {
        interval: 1050; running: true
        onTriggered: {
            check(widget.savedMode === "auto" && widget.mode === "auto", "queued Auto wins")
            widget.setSpeed("4000")
        }
    }
    Timer {
        interval: 1600; running: true
        onTriggered: {
            check(widget.persistentControl && widget.savedMode === "manual" && widget.savedRpm === 4000, "manual preference acknowledgment")
            var data = {is_apple_silicon:true, has_fan:true, fan_min:1200, fan_max:6241,
                fans:[{index:1,min:1200,max:5779,rpm:2300}], mode:"auto", control_available:true,
                fan_control_enabled:true, persistent:true, saved_mode:"manual", saved_rpm:4000,
                paused_reason:"fixture safety pause"}
            widget.applyData(JSON.stringify(data))
            check(widget.desiredManual && !widget.manualMode && widget.savedRpm === 4000, "saved intent remains distinct from actual firmware mode")
            check(widget.pausedReason === "fixture safety pause", "pause reason retained")
            check(widget.preferenceConfirmed, "valid saved preference can show Saved badge")
            data.persistent = false
            widget.applyData(JSON.stringify(data))
            check(!widget.fanControlEnabled, "legacy numeric controls fail closed")
            data.persistent = true
            data.mode = "manual"
            widget.applyData(JSON.stringify(data))
            widget.setSpeed("4999")
        }
    }
    Timer {
        interval: 2200; running: true
        onTriggered: {
            check(widget.controlError.indexOf("fixture command failure") >= 0, "command failure surfaced")
            widget.applyData('{"is_apple_silicon":true,"error":"macsmc_hwmon_missing","control_available":true}')
            check(!widget.dataValid && widget.maxTemp === null && widget.fanRpm === null && widget.fans.length === 0, "stale readings cleared")
            check(!widget.preferenceConfirmed, "stale data cannot show a confirmed Saved badge")
            check(widget.controlAvailable && !widget.fanControlEnabled, "Auto recovery remains available")
            widget.applyData('not JSON')
            check(!widget.dataValid, "invalid JSON rejected")
            console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
}
