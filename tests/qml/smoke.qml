import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Plugin.BarWidget { id: widget }
    function check(condition, message) {
        if (!condition) { console.error("ASSERT FAILED: " + message); Qt.quit() }
    }
    property int stage: 0
    Timer {
        interval: 50; running: true; repeat: true
        onTriggered: {
            if (stage === 0) {
                if (!widget.dataValid) return
                check(widget.mode === "auto" && !widget.manualMode, "positive targets do not infer manual mode")
                check(widget.maxTemp === 0 && widget.powerWatts === 0 && widget.sensors.battery === null, "zero and missing values")
                check(widget.fans[0].label.indexOf("<img") === 0, "markup is plain text")
                widget.setFan(1, 4000)
                widget.setFan(2, 3000)
                widget.setFan(1, 4500)
                widget.setSpeed("auto")
                widget.setFan(2, 5000)
                stage = 1
            } else if (stage === 1) {
                if (widget.writeBusy || widget.pendingRequests.length) return
                check(widget.savedMode === "auto", "queued Auto wins and cancels all pending fan changes")
                widget.setFan(1, 4000)
                widget.setFan(2, 3000)
                widget.setFan(1, 4500)
                widget.setFan(2, 3500)
                widget.setFan(64, 4000)
                stage = 2
            } else if (stage === 2) {
                if (widget.writeBusy || widget.pendingRequests.length) return
                check(widget.persistentControl && widget.savedMode === "manual" && widget.savedControlMode === "individual", "per-fan preference acknowledgment")
                check(widget.fanSelected(widget.fans[0]) === 4500 && widget.fanSelected(widget.fans[1]) === 3500, "queue preserves distinct channels and coalesces latest per fan")
                var data = {is_apple_silicon:true, has_fan:true, fan_min:1200, fan_max:6241,
                    fans:[{index:1,min:1200,max:5779,rpm:2300},{index:2,min:1200,max:6241,rpm:2500}], mode:"auto", control_available:true,
                    fan_control_enabled:true, persistent:true, per_fan_control:true, saved_mode:"manual", saved_rpm:null,
                    saved_control_mode:"individual",saved_fans:[{index:1,rpm:4500},{index:2,rpm:3500}], paused_reason:"fixture safety pause"}
                widget.applyData(JSON.stringify(data))
                check(widget.desiredManual && !widget.manualMode && widget.savedFans.length === 2, "saved independent intent remains distinct from firmware mode")
                check(widget.pausedReason === "fixture safety pause" && widget.preferenceConfirmed, "valid paused saved preference remains visible")
                data.saved_fans[1].rpm = 2502
                widget.applyData(JSON.stringify(data))
                check(widget.fanSelected(widget.fans[1]) === 2502, "saved raw firmware target is displayed without quantization")
                data.saved_fans[1].rpm = 3500
                data.saved_fans[0].rpm = 4500.5
                widget.applyData(JSON.stringify(data))
                check(!widget.fanControlEnabled && !widget.preferenceConfirmed, "fractional saved map fails closed")
                data.saved_fans[0].rpm = 4500
                data.fans = [data.fans[0]]
                widget.applyData(JSON.stringify(data))
                check(!widget.fanControlEnabled && !widget.preferenceConfirmed, "missing physical fan cannot silently remap saved targets")
                data.fans.push({index:2,min:1200,max:6241,rpm:2500})
                data.per_fan_control = false
                widget.applyData(JSON.stringify(data))
                check(!widget.fanControlEnabled, "legacy service cannot accept per-fan writes")
                data.per_fan_control = true
                data.mode = "manual"
                widget.applyData(JSON.stringify(data))
                widget.setFan(1, 5050)
                stage = 3
            } else if (stage === 3) {
                if (widget.writeBusy || widget.pendingRequests.length) return
                check(widget.controlError.indexOf("fixture command failure") >= 0, "command failure surfaced")
                widget.setFan(1, 5100)
                stage = 4
            } else if (stage === 4) {
                if (widget.writeBusy || widget.pendingRequests.length) return
                check(widget.controlError !== "" && widget.fanSelected(widget.fans[0]) === 4500, "wrong canonical ack cannot claim a requested RPM was saved")
                widget.applyData('{"is_apple_silicon":true,"error":"macsmc_hwmon_missing","control_available":true}')
                check(!widget.dataValid && widget.maxTemp === null && widget.fanRpm === null && widget.fans.length === 0, "stale readings cleared")
                check(!widget.preferenceConfirmed, "stale data cannot show confirmed Saved badge")
                check(widget.controlAvailable && !widget.fanControlEnabled, "Auto recovery remains available")
                widget.applyData('not JSON')
                check(!widget.dataValid, "invalid JSON rejected")
                console.log("WIDGET TEST PASSED")
                stage = 5
                Qt.quit()
            }
        }
    }
    Timer { interval: 10000; running: true; onTriggered: { console.error("ASSERT FAILED: command sequence timed out at stage " + stage); Qt.quit() } }
}
