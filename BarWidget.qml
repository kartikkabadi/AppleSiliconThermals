import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Telemetry.js" as Telemetry

BarWidget {
    id: root
    moduleName: "io.github.lukasmoriarty.applesiliconthermals"
    property bool popupOpen: false
    property bool dataValid: false
    property bool isAppleSilicon: true
    property bool hasFan: false
    property int fanCount: 0
    property var fanRpm: null
    property var fanTarget: null
    property int fanMin: 1200
    property int fanMax: 7200
    property bool fanControlEnabled: false
    property bool controlAvailable: false
    property string mode: "unknown"
    readonly property bool manualMode: mode === "manual"
    property var maxTemp: null
    property var powerWatts: null
    property string deviceModel: ""
    property var fans: []
    property var sensors: ({})
    property string readError: ""
    property string controlError: ""
    property string controlStatusError: ""
    property string warningText: ""
    property bool writeBusy: false
    property bool readBusy: false
    property string pendingTarget: ""
    property bool leaseArmed: false
    property string leaseGeneration: ""
    property bool leaseRecovering: false
    readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("helper.sh").toString().replace(/^file:\/\//, ""))
    readonly property bool spinIcon: setting("spinIcon", true) === true
    readonly property int quietRpm: snapSpeed(fanMax * 0.25)
    readonly property int regularRpm: snapSpeed(fanMax * 0.5)
    readonly property int maxRpm: fanMax
    readonly property string modeText: strings.t(leaseRecovering ? "recovering" : mode === "manual" ? "manual" : mode === "auto" ? "auto" : "unknown")
    readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground

    Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }
    function formatNumber(value, decimals) {
        return value === null || value === undefined || !isFinite(value) ? "—" : Commons.I18n.formatNumber(value, decimals || 0)
    }
    function formatRpm(value) { return formatNumber(value, 0) }
    function snapSpeed(value) {
        var clamped = Math.max(fanMin, Math.min(fanMax, Number(value) || fanMin))
        return Math.max(fanMin, Math.min(fanMax, fanMin + Math.round((clamped - fanMin) / 50) * 50))
    }
    function invalidate(message) {
        dataValid = false
        fanControlEnabled = false
        mode = "unknown"
        hasFan = false
        fanCount = 0
        fanRpm = null
        fanTarget = null
        maxTemp = null
        powerWatts = null
        fans = []
        sensors = ({})
        leaseArmed = false
        leaseRecovering = false
        readError = message
        warningText = ""
    }
    function applyData(raw) {
        try {
            var data = Telemetry.parse(raw)
            isAppleSilicon = data.isAppleSilicon
            deviceModel = data.deviceModel
            controlAvailable = data.controlAvailable
            controlStatusError = data.controlError
            if (data.error) {
                invalidate(data.error === "unsupported_hardware" ? strings.t("unsupported") : data.error === "macsmc_hwmon_missing" ? strings.t("driverMissing") : (data.errorMessage || strings.t("readFailed")))
                return
            }
            fanRpm = data.fanRpm
            fanTarget = data.fanTarget
            fanMin = data.fanMin === null ? 1200 : data.fanMin
            fanMax = data.fanMax === null ? 7200 : data.fanMax
            fanCount = data.fanCount
            fans = data.fans
            hasFan = data.hasFan && fanCount > 0
            mode = data.mode
            leaseRecovering = data.leaseRecovering
            fanControlEnabled = data.controlEnabled
            sensors = data.sensors
            maxTemp = data.maxTemp
            powerWatts = data.powerWatts
            dataValid = true
            readError = ""
            warningText = data.warnings.join("\n")
            freshness.restart()
            var sameLease = data.leaseOwned && leaseGeneration !== "" && data.generation === leaseGeneration
            // A journaled, bounded repair temporarily reports unknown mode. Keep
            // renewing only our already-armed generation while its broker owns
            // that repair; all other unknown/unavailable states fail closed.
            if (!sameLease || !((mode === "manual" && fanControlEnabled) || data.leaseRecovering)) leaseArmed = false
        } catch (error) {
            invalidate(strings.t("readFailed"))
        }
    }
    function refresh() {
        if (readBusy || writeBusy) return
        readBusy = true
        readProc.buffer = ""
        readProc.failed = false
        readProc.cancelled = false
        readProc.running = true
        readDeadline.restart()
    }
    function togglePopup() { popupOpen = !popupOpen; if (popupOpen) refresh() }
    function close() { popupOpen = false }
    function setSpeed(target) {
        var value = String(target)
        if (!/^(auto|[1-7][0-9]{3})$/.test(value)) return
        if (value === "auto") {
            leaseArmed = false
            if (!controlAvailable) return
        } else if (!fanControlEnabled || !dataValid || pendingTarget === "auto" || (writeBusy && writeProc.targetSpeed === "auto")) return
        pendingTarget = value
        startPending()
    }
    function startPending() {
        if (writeBusy || pendingTarget === "") return
        writeBusy = true
        if (readProc.running) { readProc.cancelled = true; readProc.running = false }
        writeProc.targetSpeed = pendingTarget
        pendingTarget = ""
        writeProc.buffer = ""
        writeProc.output = ""
        writeProc.timedOut = false
        controlError = ""
        writeProc.running = true
        writeDeadline.restart()
    }
    Component.onCompleted: refresh()

    Timer { interval: root.popupOpen ? 1500 : 3000; running: true; repeat: true; onTriggered: root.refresh() }
    Timer { id: freshness; interval: 10000; onTriggered: root.invalidate(strings.t("stale")) }
    Timer {
        id: readDeadline
        interval: 5000
        onTriggered: {
            readProc.failed = true
            readProc.running = false
            root.invalidate(strings.t("readTimeout"))
            if (!readProc.running) root.readBusy = false
        }
    }
    Process {
        id: readProc
        property string buffer: ""
        property bool failed: false
        property bool cancelled: false
        command: [root.helperPath, "get"]
        stdout: SplitParser {
            onRead: function(line) {
                if (readProc.buffer.length + line.length > 65536) { readProc.failed = true; return }
                readProc.buffer += line + "\n"
            }
        }
        onExited: function(code) {
            readDeadline.stop()
            Qt.callLater(function() {
                if (readProc.cancelled) { root.readBusy = false; return }
                if (!readProc.failed) {
                    if (code !== 0 && readProc.buffer.trim() === "") root.invalidate(strings.t("readFailed"))
                    else root.applyData(readProc.buffer)
                } else if (root.readError === "") root.invalidate(strings.t("readFailed"))
                root.readBusy = false
            })
        }
    }
    Timer {
        id: writeDeadline
        interval: 5000
        onTriggered: {
            writeProc.timedOut = true
            root.leaseArmed = false
            writeProc.running = false
            root.controlError = strings.t("writeTimeout")
            if (root.pendingTarget !== "auto") root.pendingTarget = ""
            if (!writeProc.running) root.writeBusy = false
        }
    }
    Process {
        id: writeProc
        property string targetSpeed: "auto"
        property string buffer: ""
        property string output: ""
        property bool timedOut: false
        command: [root.helperPath, "set", targetSpeed]
        stdout: SplitParser { onRead: function(line) { if (writeProc.output.length < 16384) writeProc.output += line + "\n" } }
        stderr: SplitParser { onRead: function(line) { if (writeProc.buffer.length < 1024) writeProc.buffer += line.slice(0, 240) + "\n" } }
        onExited: function(code) {
            writeDeadline.stop()
            Qt.callLater(function() {
                if (code !== 0 || writeProc.timedOut) {
                    root.leaseArmed = false
                    if (!writeProc.timedOut) {
                        var detail = writeProc.buffer.trim()
                        try { detail = JSON.parse(writeProc.output).error || detail } catch (error) {}
                        root.controlError = Telemetry.boundedText(detail, 240) || strings.t("writeFailed")
                    }
                    if (root.pendingTarget !== "auto") root.pendingTarget = ""
                } else if (writeProc.targetSpeed !== "auto" && root.pendingTarget !== "auto") {
                    try {
                        var reply = JSON.parse(writeProc.output)
                        if (reply.mode !== "manual" || !/^[0-9a-f]{32}$/.test(reply.generation)) throw new Error("Invalid lease acknowledgment")
                        root.leaseGeneration = reply.generation
                        root.leaseArmed = true
                    } catch (error) {
                        root.leaseArmed = false
                        root.controlError = strings.t("writeFailed")
                    }
                } else root.leaseArmed = false
                root.writeBusy = false
                root.refresh()
                root.startPending()
            })
        }
    }
    Timer {
        interval: 3000
        running: root.leaseArmed && root.dataValid
        repeat: true
        onTriggered: if (!heartbeat.running) { heartbeat.generation = root.leaseGeneration; heartbeat.running = true; heartbeatDeadline.restart() }
    }
    Timer {
        id: heartbeatDeadline
        interval: 3000
        onTriggered: { root.leaseArmed = false; heartbeat.running = false; root.controlError = strings.t("heartbeatFailed") }
    }
    Process {
        id: heartbeat
        property string generation: ""
        command: [root.helperPath, "heartbeat", generation]
        onExited: function(code) {
            heartbeatDeadline.stop()
            if (code !== 0 && root.leaseArmed) { root.leaseArmed = false; root.controlError = strings.t("heartbeatFailed"); root.refresh() }
        }
    }

    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight
    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        slotSize: Style.bar.statusSlot
        foreground: !root.dataValid ? Commons.Color.muted : root.maxTemp !== null && root.maxTemp >= 80 ? Commons.Color.urgent : root.manualMode ? Commons.Color.accent : root.foreground
        tooltipText: Telemetry.escapeMarkup(strings.t("title") + ": " + (!root.dataValid ? (root.readError || strings.t("loading")) : root.hasFan ? strings.t("tooltip").arg(root.formatRpm(root.fanRpm)).arg(root.formatNumber(root.maxTemp, 1)) : strings.t("temperature").arg(root.formatNumber(root.maxTemp, 1))))
        onPressed: function(mouseButton) { if (mouseButton === Qt.LeftButton) root.togglePopup() }
        iconComponent: Component {
            Item {
                width: 16; height: 16
                OpticalGlyph {
                    id: fanGlyph
                    anchors.fill: parent
                    text: !root.dataValid ? "󰌺" : root.hasFan ? "󰈐" : "󰔏"
                    color: button.foreground
                    fontFamily: button.fontFamily
                    fontSize: button.fontSize
                    paintedSize: Style.bar.iconSize
                    transform: Rotation { id: spin; origin.x: fanGlyph.paintedCenterX; origin.y: fanGlyph.paintedCenterY }
                }
                NumberAnimation {
                    target: spin; property: "angle"; from: 0; to: 360
                    duration: Math.max(1, Style.duration(Math.round(Math.max(180, Math.min(1200, 1200000 / Math.max(root.fanRpm || 1, 1))))))
                    loops: Animation.Infinite
                    easing.type: Easing.Linear
                    running: root.spinIcon && !Style.reduceMotion && root.dataValid && root.hasFan && root.fanRpm > 0
                }
            }
        }
    }

    PopupCard {
        id: popup
        anchorItem: button
        bar: root.bar
        owner: root
        open: root.popupOpen
        contentWidth: fittedContentWidth(Style.space(380))
        contentHeight: fittedContentHeight(mainCol.implicitHeight)
        onOpenChanged: if (open) Qt.callLater(function() { focusScope.forceActiveFocus() })
        FocusScope {
            id: focusScope
            anchors.fill: parent
            Keys.onEscapePressed: root.close()
            Flickable {
                id: scroll
                anchors.fill: parent
                clip: true
                contentWidth: width
                contentHeight: mainCol.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: mainCol
                    width: scroll.width
                    spacing: Style.space(10)
                    ThermalText { width: parent.width; text: strings.t("title"); font.pixelSize: Style.font.body; font.bold: true }
                    ThermalText { width: parent.width; text: root.deviceModel; color: Commons.Color.muted; visible: text !== "" }
                    PanelSeparator { width: parent.width }
                    ThermalText { width: parent.width; visible: root.readError !== ""; text: root.readError; color: Commons.Color.urgent }
                    ThermalText { width: parent.width; visible: root.controlError !== ""; text: root.controlError; color: Commons.Color.urgent }
                    ThermalText { width: parent.width; visible: root.controlStatusError !== ""; text: root.controlStatusError; color: Commons.Color.urgent }
                    ThermalText { width: parent.width; visible: root.warningText !== ""; text: root.warningText; color: Commons.Color.muted }
                    ThermalText { width: parent.width; visible: !root.dataValid && root.readError === ""; text: strings.t("loading") }
                    Column {
                        width: parent.width
                        visible: root.dataValid
                        spacing: Style.space(8)
                        ThermalText { width: parent.width; text: root.hasFan ? root.modeText : strings.t("fanless"); color: root.manualMode ? Commons.Color.accent : root.foreground; font.pixelSize: Style.font.body }
                        Repeater {
                            model: root.fans
                            Column {
                                required property var modelData
                                width: mainCol.width
                                spacing: Style.space(2)
                                ThermalText { width: parent.width; text: modelData.label || strings.t("fanFallback").arg(root.formatNumber(modelData.index)); font.bold: true }
                                ThermalText { width: parent.width; text: strings.t("fanSummary").arg(root.formatRpm(modelData.rpm)).arg(root.formatRpm(modelData.target)).arg(root.formatRpm(modelData.min)).arg(root.formatRpm(modelData.max)) }
                            }
                        }
                        ThermalText { width: parent.width; text: strings.t("componentMax").arg(root.formatNumber(root.maxTemp, 1)); font.bold: true }
                        ThermalText { width: parent.width; text: strings.t("systemPower").arg(root.formatNumber(root.powerWatts, 2)) }
                        ThermalText { width: parent.width; text: strings.t("sensorNote"); color: Commons.Color.muted }
                        Repeater {
                            model: ["nand", "battery", "regulator", "wifi"]
                            ThermalText { required property string modelData; width: mainCol.width; text: strings.t(modelData).arg(root.formatNumber(root.sensors[modelData], 1)) }
                        }
                        PanelSeparator { width: parent.width; visible: root.hasFan }
                        ThermalText { width: parent.width; visible: root.hasFan; text: strings.t(root.fanControlEnabled ? "leaseNote" : "setup"); color: Commons.Color.muted }
                        Flow {
                            width: parent.width
                            spacing: Style.space(6)
                            visible: root.hasFan && root.fanControlEnabled
                            Repeater {
                                model: [{key: "quiet", rpm: root.quietRpm}, {key: "regular", rpm: root.regularRpm}, {key: "maximum", rpm: root.maxRpm}]
                                Button {
                                    required property var modelData
                                    text: strings.t(modelData.key)
                                    focusable: true
                                    enabled: !root.writeBusy
                                    selected: root.manualMode && root.fanTarget !== null && Math.abs(root.fanTarget - modelData.rpm) < 25
                                    onClicked: root.setSpeed(modelData.rpm)
                                }
                            }
                        }
                        Column {
                            width: parent.width
                            visible: root.hasFan && root.fanControlEnabled
                            ThermalText { width: parent.width; text: strings.t("target").arg(root.formatRpm(root.snapSpeed(rpmSlider.liveValue))) }
                            PanelSlider {
                                id: rpmSlider
                                width: parent.width
                                bar: root.bar
                                minimum: root.fanMin; maximum: root.fanMax; step: 50; integer: true
                                enabled: !root.writeBusy
                                activeFocusOnTab: true
                                value: root.fanTarget !== null ? root.snapSpeed(root.fanTarget) : root.quietRpm
                                onReleased: function(value) { root.setSpeed(root.snapSpeed(value)) }
                                Keys.onPressed: function(event) {
                                    var key = Util.readingKey(event)
                                    var target = key === Qt.Key_Left ? liveValue - step : key === Qt.Key_Right ? liveValue + step : key === Qt.Key_Home ? minimum : key === Qt.Key_End ? maximum : null
                                    if (target !== null) { liveValue = root.snapSpeed(target); root.setSpeed(liveValue); event.accepted = true }
                                }
                            }
                        }
                    }
                    Flow {
                        width: parent.width
                        spacing: Style.space(8)
                        Button { text: strings.t("autoButton"); focusable: true; visible: root.controlAvailable; selected: root.mode === "auto"; onClicked: root.setSpeed("auto") }
                        Button { text: strings.t("refresh"); focusable: true; onClicked: root.refresh() }
                        Button { text: strings.t("close"); focusable: true; onClicked: root.close() }
                    }
                }
            }
        }
    }
}
