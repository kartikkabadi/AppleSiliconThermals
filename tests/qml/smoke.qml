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
            check(!widget.leaseArmed && widget.mode === "auto", "queued Auto wins")
            widget.setSpeed("4000")
        }
    }
    Timer {
        interval: 1600; running: true
        onTriggered: {
            check(widget.leaseArmed && widget.leaseGeneration === "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "own lease acknowledgment")
            var data = {is_apple_silicon:true, has_fan:true, fan_min:1200, fan_max:6241,
                fans:[{index:1,min:1200,max:5779,rpm:2300}], mode:"unknown", control_available:false,
                fan_control_enabled:false, lease_owned:true, lease_recovering:true,
                broker_generation:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
            widget.applyData(JSON.stringify(data))
            check(widget.leaseArmed && widget.leaseRecovering && !widget.fanControlEnabled, "own pending repair preserves renewal with numeric controls disabled")
            data.broker_generation = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            widget.applyData(JSON.stringify(data))
            check(!widget.leaseArmed, "replacement generation stops renewal")
            widget.leaseArmed = true
            data.broker_generation = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            data.lease_owned = false
            widget.applyData(JSON.stringify(data))
            check(!widget.leaseArmed, "other owner's pending repair cannot preserve renewal")
            widget.leaseArmed = true
            data.lease_owned = true
            data.lease_recovering = false
            widget.applyData(JSON.stringify(data))
            check(!widget.leaseArmed, "ordinary unknown state disarms renewal")
            widget.leaseArmed = true
            data.lease_recovering = true
            widget.applyData(JSON.stringify(data))
            widget.invalidate("fixture stale")
            check(!widget.leaseArmed && !widget.leaseRecovering, "stale data disarms pending repair")
            data.lease_recovering = false
            data.mode = "manual"
            data.control_available = true
            data.fan_control_enabled = true
            widget.applyData(JSON.stringify(data))
            check(!widget.leaseArmed, "fresh data does not rearm abandoned generation")
            widget.setSpeed("4999")
        }
    }
    Timer {
        interval: 2200; running: true
        onTriggered: {
            check(!widget.leaseArmed && widget.controlError.indexOf("fixture command failure") >= 0, "command failure surfaced")
            widget.applyData('{"is_apple_silicon":true,"error":"macsmc_hwmon_missing","control_available":true}')
            check(!widget.dataValid && widget.maxTemp === null && widget.fanRpm === null && widget.fans.length === 0, "stale readings cleared")
            check(widget.controlAvailable && !widget.fanControlEnabled, "Auto recovery remains available")
            widget.applyData('not JSON')
            check(!widget.dataValid, "invalid JSON rejected")
            console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
}
