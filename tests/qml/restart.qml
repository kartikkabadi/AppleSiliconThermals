import QtQuick
import Quickshell
import "Plugin" as Plugin

Scope {
    Component { id: widgetComponent; Plugin.BarWidget {} }
    Loader { id: loader; sourceComponent: widgetComponent }
    function check(condition, message) {
        if (!condition) { console.error("ASSERT FAILED: " + message); Qt.quit() }
    }
    Timer {
        interval: 350; running: true
        onTriggered: { check(loader.item.dataValid, "first widget loaded"); loader.item.setSpeed("4000") }
    }
    Timer {
        interval: 1000; running: true
        onTriggered: {
            check(loader.item.savedMode === "manual" && loader.item.savedRpm === 4000, "manual preference saved")
            loader.active = false
            Qt.callLater(function() { loader.active = true })
        }
    }
    Timer {
        interval: 1800; running: true
        onTriggered: {
            check(loader.item.dataValid && loader.item.desiredManual && loader.item.manualMode, "recreated widget uses service-owned manual state")
            check(loader.item.savedRpm === 4000 && loader.item.preferenceConfirmed, "saved RPM survives widget destruction")
        }
    }
    Timer {
        interval: 4500; running: true
        onTriggered: {
            check(loader.item.savedMode === "manual" && loader.item.savedRpm === 4000, "selection remains after a legacy heartbeat interval")
            console.log("WIDGET TEST PASSED")
            Qt.quit()
        }
    }
}
