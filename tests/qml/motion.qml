import QtQuick
import Quickshell
import qs.Commons
import "Plugin" as Plugin

FloatingWindow {
    id: window
    visible: true
    implicitWidth: 80; implicitHeight: 40
    property int rpm: 2300
    property bool enabledSpin: true
    property bool varyRpm: true
    property real beforePoll: 0
    property real pausedPhase: 0
    property real resumedAt: 0
    property real previousPhase: 0
    property real previousTime: 0
    property int samples: 0
    property int failures: 0
    Plugin.FanIcon {
        id: icon
        anchors.centerIn: parent
        fan: true
        spinning: window.enabledSpin && window.rpm > 0
        text: "󰈐"
    }
    function check(condition, message) {
        if (!condition) { failures++; console.error("ASSERT FAILED: " + message) }
    }
    Timer {
        interval: 35; running: true; repeat: true
        onTriggered: {
            var now = Date.now()
            if (previousTime && window.enabledSpin && window.rpm > 0 && !Style.reduceMotion) {
                var delta = (icon.phase - previousPhase + 360) % 360
                var expected = (now - previousTime) * 360 / icon.periodMs
                // One frame of scheduling jitter is expected; a restart or stalled
                // phase at the frequent RPM changes is not.
                check(Math.abs(delta - expected) < 15, "uneven phase across RPM updates")
                samples++
            }
            previousPhase = icon.phase
            previousTime = now
            if (varyRpm) window.rpm = window.rpm === 2300 ? 6000 : 2300
        }
    }
    Timer {
        interval: 1300; running: true
        onTriggered: {
            check(samples > 20, "insufficient rendered motion samples")
            check(icon.width === 16 && icon.height === 16, "icon changed bar slot dimensions")
            var glyph = icon.children[0]
            check(glyph.transform[0].xScale === 1.04, "fan glyph is not four percent larger")
            window.enabledSpin = false
            varyRpm = false
            pausedPhase = icon.phase
            previousTime = 0
        }
    }
    Timer {
        interval: 1500; running: true
        onTriggered: {
            check(icon.phase === pausedPhase, "disabled spin advanced phase")
            icon.fan = false
            var glyph = icon.children[0]
            check(glyph.transform[1].angle === 0, "warning glyph is tilted")
            check(glyph.transform[0].xScale === 1, "warning glyph unexpectedly enlarged")
            icon.fan = true
            window.rpm = 0
            window.enabledSpin = true
        }
    }
    Timer {
        interval: 1700; running: true
        onTriggered: {
            check(icon.phase === pausedPhase, "stopped fan continues spinning")
            previousTime = 0
            window.rpm = 2300
            resumedAt = Date.now()
        }
    }
    Timer {
        interval: 2050; running: true
        onTriggered: {
            check(Math.abs((icon.phase - pausedPhase + 360) % 360 - (Date.now() - resumedAt) * 360 / icon.periodMs) < 15, "resume jumped by paused time")
            Style.reduceMotion = true
            pausedPhase = icon.phase
        }
    }
    Timer {
        interval: 2250; running: true
        onTriggered: {
            check(icon.phase === pausedPhase, "reduce motion did not stop animation")
            Style.reduceMotion = false
            resumedAt = Date.now()
            previousTime = 0
        }
    }
    Timer {
        interval: 2450; running: true
        onTriggered: {
            check(Math.abs((icon.phase - pausedPhase + 360) % 360 - (Date.now() - resumedAt) * 360 / icon.periodMs) < 15, "reduce-motion resume jumped by paused time")
            if (!failures) console.log("MOTION TEST PASSED")
            Qt.quit()
        }
    }
}
