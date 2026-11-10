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
    property bool detailsOpen: false
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
    property string controlNotice: ""
    property string warningText: ""
    property bool writeBusy: false
    property bool readBusy: false
    property string pendingTarget: ""
    property bool persistentControl: false
    property string savedMode: "unknown"
    property var savedRpm: null
    property string pausedReason: ""
    property string preferenceError: ""
    property bool leaseRecovering: false
    readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("helper.sh").toString().replace(/^file:\/\//, ""))
    readonly property bool spinIcon: setting("spinIcon", true) === true
    readonly property int quietRpm: snapSpeed(fanMax * 0.25)
    readonly property int regularRpm: snapSpeed(fanMax * 0.5)
    readonly property int maxRpm: fanMax
    readonly property bool desiredManual: persistentControl && savedMode === "manual"
    readonly property bool preferenceConfirmed: dataValid && persistentControl && preferenceError === "" && (savedMode === "auto" || (savedMode === "manual" && savedRpm !== null))
    readonly property int selectedRpm: snapSpeed(savedRpm !== null ? savedRpm : fanTarget !== null ? fanTarget : quietRpm)
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
            controlNotice = data.controlNotice
            persistentControl = data.persistent
            savedMode = data.savedMode
            savedRpm = data.savedRpm
            pausedReason = data.pausedReason
            preferenceError = data.preferenceError
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
                    if (!writeProc.timedOut) {
                        var detail = writeProc.buffer.trim()
                        try { detail = JSON.parse(writeProc.output).error || detail } catch (error) {}
                        root.controlError = Telemetry.boundedText(detail, 240) || strings.t("writeFailed")
                    }
                    if (root.pendingTarget !== "auto") root.pendingTarget = ""
                } else {
                    try {
                        var reply = JSON.parse(writeProc.output)
                        if (reply.persistent !== true || ["auto", "manual"].indexOf(reply.saved_mode) < 0) throw new Error("Invalid saved preference acknowledgment")
                        root.persistentControl = true
                        root.savedMode = reply.saved_mode
                        root.savedRpm = Telemetry.integer(reply.saved_rpm, 1000, 7999)
                    } catch (error) {
                        root.controlError = strings.t("writeFailed")
                    }
                }
                root.writeBusy = false
                root.refresh()
                root.startPending()
            })
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
        contentWidth: fittedContentWidth(Style.space(450))
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
                    spacing: Style.space(14)

                    Row {
                        width: parent.width
                        spacing: Style.space(10)
                        BorderSurface {
                            id: headerIcon
                            width: Style.space(36); height: width
                            radius: Style.cornerRadius
                            color: Style.selectedFillFor(root.foreground, Commons.Color.accent)
                            ThermalText { anchors.centerIn: parent; text: "󰈐"; font.pixelSize: Style.font.subtitle; color: Commons.Color.accent }
                        }
                        Column {
                            width: parent.width - headerIcon.width - headerActions.width - parent.spacing * 2
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Style.space(3)
                            ThermalText { width: parent.width; text: strings.t("title"); font.pixelSize: Style.font.body; font.bold: true }
                            ThermalText { width: parent.width; text: root.deviceModel || strings.t("loading"); color: Commons.Color.muted; maximumLineCount: 2; elide: Text.ElideRight }
                        }
                        Row {
                            id: headerActions
                            spacing: Style.space(2)
                            Button { text: "󰑐"; fontSize: Style.font.body; horizontalPadding: Style.space(7); tooltipText: strings.t("refresh"); Accessible.name: strings.t("refresh"); focusable: true; enabled: !root.readBusy; onClicked: root.refresh() }
                            Button { text: "×"; fontSize: Style.font.body; horizontalPadding: Style.space(7); tooltipText: strings.t("close"); Accessible.name: strings.t("close"); focusable: true; onClicked: root.close() }
                        }
                    }

                    BorderSurface {
                        width: parent.width
                        radius: Style.cornerRadius
                        color: Style.normalFillFor(root.foreground, Commons.Color.accent)
                        borderSpec: Border.flat(Util.alpha(root.foreground, 0.10), 1)
                        height: stateRow.implicitHeight + Style.space(16)
                        Row {
                            id: stateRow
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                            anchors.margins: Style.space(8)
                            spacing: Style.space(8)
                            Rectangle { width: Style.space(6); height: width; radius: width / 2; color: !root.dataValid ? Commons.Color.muted : root.manualMode ? Commons.Color.accent : root.desiredManual && root.mode !== "manual" ? Commons.Color.urgent : root.foreground; anchors.verticalCenter: parent.verticalCenter }
                            ThermalText { width: parent.width - stateBadge.implicitWidth - Style.space(22); text: !root.dataValid ? strings.t("unavailable") : root.writeBusy ? strings.t("saving") : root.desiredManual && root.mode !== "manual" && !root.leaseRecovering ? strings.t("paused") : root.modeText; font.bold: true }
                            ThermalText { id: stateBadge; text: root.preferenceConfirmed ? "✓ " + strings.t("saved") : strings.t("live"); color: Commons.Color.muted; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }

                    BorderSurface {
                        width: parent.width
                        visible: root.readError !== "" || root.controlError !== "" || root.controlStatusError !== "" || root.preferenceError !== ""
                        height: errorText.implicitHeight + Style.space(20)
                        radius: Style.cornerRadius
                        color: Util.alpha(Commons.Color.urgent, 0.10)
                        borderSpec: Border.flat(Util.alpha(Commons.Color.urgent, 0.5), 1)
                        ThermalText { id: errorText; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: Style.space(10); text: [root.readError, root.controlError, root.controlStatusError, root.preferenceError].filter(function(value) { return value !== "" }).join("\n"); color: Commons.Color.urgent }
                    }

                    Grid {
                        id: fanGrid
                        width: parent.width
                        visible: root.dataValid && root.hasFan
                        columns: width < Style.space(330) || root.fans.length === 1 ? 1 : 2
                        spacing: Style.space(10)
                        Repeater {
                            model: root.fans
                            FanCard {
                                required property var modelData
                                width: (fanGrid.width - fanGrid.spacing * (fanGrid.columns - 1)) / fanGrid.columns
                                nameText: modelData.label || strings.t("fanFallback").arg(root.formatRpm(modelData.index))
                                speedText: root.formatRpm(modelData.rpm)
                                fraction: modelData.rpm !== null && modelData.max !== null && modelData.max > 0 ? modelData.rpm / modelData.max : 0
                                percentText: modelData.rpm !== null && modelData.max !== null && modelData.max > 0 ? strings.t("percent").arg(root.formatNumber(Math.min(100, Math.round(fraction * 100)))) : "—"
                                targetText: strings.t("fanTarget").arg(root.formatRpm(modelData.target))
                                rangeText: strings.t("fanRange").arg(root.formatRpm(modelData.min)).arg(root.formatRpm(modelData.max))
                            }
                        }
                    }

                    Grid {
                        id: metrics
                        width: parent.width
                        visible: root.dataValid
                        columns: width < Style.space(260) ? 1 : 2
                        spacing: Style.space(10)
                        MetricCard { width: (metrics.width - metrics.spacing * (metrics.columns - 1)) / metrics.columns; labelText: strings.t("componentLabel"); valueText: root.formatNumber(root.maxTemp, 1); unitText: "°C"; iconText: "󰔏"; valueColor: root.maxTemp !== null && root.maxTemp >= 80 ? Commons.Color.urgent : root.foreground }
                        MetricCard { width: (metrics.width - metrics.spacing * (metrics.columns - 1)) / metrics.columns; labelText: strings.t("powerLabel"); valueText: root.formatNumber(root.powerWatts, 1); unitText: "W"; iconText: "󰚥" }
                    }

                    Column {
                        width: parent.width
                        visible: root.hasFan || root.controlAvailable || root.desiredManual
                        spacing: Style.space(10)
                        ThermalText { width: parent.width; text: strings.t("coolingLabel"); font.pixelSize: Style.font.body; font.bold: true }
                        BorderSurface {
                            width: parent.width
                            height: modeButtons.implicitHeight + Style.space(8)
                            radius: Style.cornerRadius
                            color: Style.normalFillFor(root.foreground, Commons.Color.accent)
                            borderSpec: Border.flat(Util.alpha(root.foreground, 0.10), 1)
                            Row {
                                id: modeButtons
                                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                                anchors.margins: Style.space(4)
                                spacing: Style.space(4)
                                Button { width: (parent.width - parent.spacing) / 2; text: strings.t("autoButton"); iconText: "󰒓"; focusable: true; enabled: root.controlAvailable; selected: !root.desiredManual && root.mode === "auto"; onClicked: root.setSpeed("auto") }
                                Button { width: (parent.width - parent.spacing) / 2; text: strings.t("manualButton"); iconText: "󰒺"; focusable: true; enabled: root.fanControlEnabled && !root.writeBusy; selected: root.desiredManual; onClicked: root.setSpeed(root.savedRpm !== null ? root.snapSpeed(root.savedRpm) : root.snapSpeed(root.fanRpm !== null && root.fanRpm >= root.fanMin ? root.fanRpm : root.quietRpm)) }
                            }
                        }

                        Column {
                            width: parent.width
                            visible: root.desiredManual
                            spacing: Style.space(12)
                            Item {
                                width: parent.width
                                height: targetValue.implicitHeight
                                Column {
                                    id: targetValue
                                    spacing: Style.space(3)
                                    ThermalText { text: strings.t(root.fanCount === 2 ? "targetBoth" : root.fanCount > 2 ? "targetAll" : "targetLabel"); color: Commons.Color.muted }
                                    Row {
                                        spacing: Style.space(5)
                                        ThermalText { text: root.formatRpm(root.snapSpeed(rpmSlider.liveValue)); font.pixelSize: Style.font.title; font.bold: true; color: Commons.Color.accent }
                                        ThermalText { text: "RPM"; color: Commons.Color.muted; anchors.bottom: parent.bottom; anchors.bottomMargin: Style.space(3) }
                                    }
                                }
                                ThermalText { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: strings.t("ofMaximum").arg(root.formatNumber(Math.round(root.snapSpeed(rpmSlider.liveValue) / root.fanMax * 100))); color: Commons.Color.muted }
                            }
                            Column {
                                width: parent.width
                                spacing: Style.space(4)
                                PanelSlider {
                                    id: rpmSlider
                                    width: parent.width
                                    bar: root.bar
                                    minimum: root.fanMin; maximum: root.fanMax; step: 50; integer: true
                                    enabled: root.fanControlEnabled && !root.writeBusy
                                    activeFocusOnTab: true
                                    Accessible.name: strings.t("targetLabel")
                                    value: root.selectedRpm
                                    onReleased: function(value) { root.setSpeed(root.snapSpeed(value)) }
                                    Keys.onPressed: function(event) {
                                        var key = Util.readingKey(event)
                                        var target = key === Qt.Key_Left ? liveValue - step : key === Qt.Key_Right ? liveValue + step : key === Qt.Key_Home ? minimum : key === Qt.Key_End ? maximum : null
                                        if (target !== null) { liveValue = root.snapSpeed(target); root.setSpeed(liveValue); event.accepted = true }
                                    }
                                }
                                Item {
                                    width: parent.width; height: minLabel.implicitHeight
                                    ThermalText { id: minLabel; anchors.left: parent.left; text: strings.t("minimumRpm").arg(root.formatRpm(root.fanMin)); color: Commons.Color.muted }
                                    ThermalText { anchors.right: parent.right; text: strings.t("maximumRpm").arg(root.formatRpm(root.fanMax)); color: Commons.Color.muted }
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: Style.space(8)
                                Repeater {
                                    model: [{key:"quiet",rpm:root.quietRpm,glyph:"󰒲"}, {key:"balanced",rpm:root.regularRpm,glyph:"󰈐"}, {key:"maximum",rpm:root.maxRpm,glyph:"󰓅"}]
                                    SpeedPreset {
                                        required property var modelData
                                        width: (mainCol.width - Style.space(16)) / 3
                                        title: strings.t(modelData.key)
                                        detail: strings.t("rpm").arg(root.formatRpm(modelData.rpm))
                                        glyph: modelData.glyph
                                        selected: Math.abs(root.selectedRpm - modelData.rpm) < 25
                                        enabled: root.fanControlEnabled && !root.writeBusy
                                        onClicked: root.setSpeed(modelData.rpm)
                                    }
                                }
                            }
                            ThermalText { width: parent.width; visible: root.preferenceConfirmed; text: "✓ " + strings.t("remembered"); color: Commons.Color.muted }
                        }
                        ThermalText { width: parent.width; visible: !root.desiredManual && root.mode === "auto"; text: strings.t("automaticNote"); color: Commons.Color.muted }
                        ThermalText { width: parent.width; visible: !root.persistentControl || !root.controlAvailable; text: strings.t(root.persistentControl ? "controlUnavailable" : "setup"); color: Commons.Color.muted }
                        ThermalText { width: parent.width; visible: root.pausedReason !== ""; text: root.pausedReason; color: Commons.Color.urgent }
                    }

                    PanelSeparator { width: parent.width }
                    Column {
                        width: parent.width
                        spacing: Style.space(8)
                        Button { width: parent.width; text: strings.t("sensorDetails"); iconText: root.detailsOpen ? "󰅃" : "󰅀"; leftAlign: true; focusable: true; selected: root.detailsOpen; onClicked: root.detailsOpen = !root.detailsOpen }
                        Grid {
                            id: sensorGrid
                            width: parent.width
                            visible: root.detailsOpen && root.dataValid
                            columns: width < Style.space(330) ? 1 : 2
                            spacing: Style.space(8)
                            Repeater {
                                model: ["nand", "battery", "regulator", "wifi"]
                                Column {
                                    required property string modelData
                                    width: (sensorGrid.width - sensorGrid.spacing * (sensorGrid.columns - 1)) / sensorGrid.columns
                                    spacing: Style.space(3)
                                    ThermalText { width: parent.width; text: strings.t(modelData + "Label"); color: Commons.Color.muted }
                                    ThermalText { width: parent.width; text: strings.t("temperature").arg(root.formatNumber(root.sensors[modelData], 1)); font.bold: true }
                                }
                            }
                        }
                        ThermalText { width: parent.width; visible: root.detailsOpen; text: strings.t("sensorNote"); color: Commons.Color.muted }
                        ThermalText { width: parent.width; visible: root.detailsOpen && root.warningText !== ""; text: root.warningText; color: Commons.Color.muted }
                        ThermalText { width: parent.width; visible: root.detailsOpen && root.controlNotice !== ""; text: root.controlNotice; color: Commons.Color.muted }
                    }
                }
            }
        }
    }

}
