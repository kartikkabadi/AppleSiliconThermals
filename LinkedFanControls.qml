import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BorderSurface {
    id: control
    property QtObject bar: null
    property int minimum: 1200
    property int maximum: 7200
    property var targetRpm: null
    property bool controlsEnabled: false
    property string title: "All fans · target speed"
    property string note: ""
    property string minLabel: "Min"
    property string maxLabel: "Max"
    property var presetLabels: ["Quiet", "Balanced", "Max"]
    property var formatValue: function(value) { return value === null ? "—" : String(Math.round(value)) }
    signal targetRequested(int rpm)
    function resetGesture() {
        if (!slider) return
        slider.dragging = false
        slider.liveValue = slider.value
    }
    onVisibleChanged: if (!visible) resetGesture()
    onControlsEnabledChanged: if (!controlsEnabled) resetGesture()
    function snap(value) {
        var clamped = Math.max(minimum, Math.min(maximum, Number(value) || minimum))
        return Math.max(minimum, Math.min(maximum, minimum + Math.round((clamped - minimum) / 50) * 50))
    }
    color: Style.normalFillFor(Commons.Color.foreground, Commons.Color.accent)
    borderSpec: Border.flat(Util.alpha(Commons.Color.foreground, 0.10), 1)
    radius: Style.cornerRadius
    implicitHeight: content.implicitHeight + Style.space(24)
    Column {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: Style.space(12)
        spacing: Style.space(10)
        ThermalText { width: parent.width; text: control.title; color: Commons.Color.muted }
        Row {
            spacing: Style.space(5)
            ThermalText { text: control.targetRpm === null ? "—" : control.formatValue(slider.dragging ? control.snap(slider.liveValue) : control.targetRpm); color: Commons.Color.accent; font.pixelSize: Math.max(Style.font.title, Style.space(28)); font.bold: true }
            ThermalText { text: "RPM"; color: Commons.Color.muted; anchors.bottom: parent.bottom; anchors.bottomMargin: Style.space(3) }
        }
        PanelSlider {
            id: slider
            objectName: "linked-target-slider"
            width: parent.width
            bar: control.bar
            minimum: control.minimum; maximum: control.maximum; step: 50; integer: true
            value: control.targetRpm !== null ? control.targetRpm : control.minimum
            enabled: control.controlsEnabled
            activeFocusOnTab: true
            Accessible.name: control.title
            onReleased: function(value) { if (control.visible && control.controlsEnabled) control.targetRequested(control.snap(value)) }
            Keys.onPressed: function(event) {
                if (!control.visible || !control.controlsEnabled) return
                var key = Util.readingKey(event)
                var value = key === Qt.Key_Left ? liveValue - step : key === Qt.Key_Right ? liveValue + step : key === Qt.Key_Home ? minimum : key === Qt.Key_End ? maximum : null
                if (value !== null) { liveValue = control.snap(value); control.targetRequested(liveValue); event.accepted = true }
            }
        }
        Item {
            width: parent.width; height: minText.implicitHeight
            ThermalText { id: minText; anchors.left: parent.left; text: control.minLabel + " " + control.formatValue(control.minimum); color: Commons.Color.muted }
            ThermalText { anchors.right: parent.right; text: control.maxLabel + " " + control.formatValue(control.maximum); color: Commons.Color.muted }
        }
        Row {
            width: parent.width
            spacing: Style.space(8)
            Repeater {
                model: [control.snap(control.maximum * 0.25), control.snap(control.maximum * 0.5), control.maximum]
                SpeedPreset {
                    required property int index
                    required property int modelData
                    width: (parent.width - parent.spacing * 2) / 3
                    title: control.presetLabels[index]
                    detail: control.formatValue(modelData) + " RPM"
                    glyph: ["󰒲", "󰈐", "󰓅"][index]
                    enabled: control.controlsEnabled
                    selected: control.targetRpm !== null && Math.abs(control.targetRpm - modelData) < 25
                    onClicked: if (control.visible && control.controlsEnabled) control.targetRequested(modelData)
                }
            }
        }
        ThermalText { width: parent.width; visible: control.note !== ""; text: control.note; color: Commons.Color.muted }
    }
}
