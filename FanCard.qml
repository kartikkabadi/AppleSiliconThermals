import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BorderSurface {
    id: card
    property string nameText: ""
    property string speedText: "—"
    property string percentText: "—"
    property string targetText: ""
    property string rangeText: ""
    property real fraction: 0
    property QtObject bar: null
    property bool manual: false
    property bool controlsEnabled: false
    property var targetRpm: null
    property int minimum: 1200
    property int maximum: 7200
    property string targetLabel: "Target"
    property string minimumLabel: "Min"
    property string maximumLabel: "Max"
    property var presetLabels: ["Quiet", "Balanced", "Max"]
    property var formatValue: function(value) { return value === null ? "—" : String(Math.round(value)) }
    signal targetRequested(int rpm)
    function resetGesture() {
        if (!slider) return
        slider.dragging = false
        slider.liveValue = slider.value
    }
    onManualChanged: if (!manual) resetGesture()
    onVisibleChanged: if (!visible) resetGesture()
    onControlsEnabledChanged: if (!controlsEnabled) resetGesture()
    property color accent: Commons.Color.accent
    function snap(value) {
        var clamped = Math.max(minimum, Math.min(maximum, Number(value) || minimum))
        return Math.max(minimum, Math.min(maximum, minimum + Math.round((clamped - minimum) / 50) * 50))
    }
    color: Style.normalFillFor(Commons.Color.foreground, accent)
    borderSpec: Border.flat(Util.alpha(Commons.Color.foreground, 0.1), 1)
    radius: Style.cornerRadius
    implicitHeight: content.implicitHeight + Style.space(24)
    Column {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: Style.space(12)
        spacing: Style.space(7)
        Item {
            width: parent.width; height: fanName.implicitHeight
            ThermalText { id: fanName; anchors.left: parent.left; width: parent.width - percentage.implicitWidth - Style.space(8); text: card.nameText; elide: Text.ElideRight; maximumLineCount: 1; font.bold: true }
            ThermalText { id: percentage; anchors.right: parent.right; text: card.percentText; color: Commons.Color.muted }
        }
        Row {
            spacing: Style.space(5)
            ThermalText { text: card.speedText; font.pixelSize: Math.max(Style.font.title, Style.space(22)); font.bold: true }
            ThermalText { text: "RPM"; color: Commons.Color.muted; anchors.bottom: parent.bottom; anchors.bottomMargin: Style.space(3) }
        }
        Rectangle {
            width: parent.width; height: Style.space(5); radius: height / 2
            color: Util.alpha(Commons.Color.foreground, 0.10)
            Rectangle { width: parent.width * Math.max(0, Math.min(1, card.fraction)); height: parent.height; radius: parent.radius; color: card.accent }
        }
        ThermalText { width: parent.width; visible: !card.manual; text: card.targetText; color: Commons.Color.muted }
        ThermalText { width: parent.width; visible: !card.manual; text: card.rangeText; color: Commons.Color.muted }
        Column {
            width: parent.width
            visible: card.manual
            spacing: Style.space(7)
            PanelSeparator { width: parent.width }
            Item {
                width: parent.width; height: targetNumber.implicitHeight
                ThermalText { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: card.targetLabel; color: Commons.Color.muted }
                ThermalText { id: targetNumber; anchors.right: parent.right; text: card.targetRpm === null ? "—" : card.formatValue(slider.dragging ? card.snap(slider.liveValue) : card.targetRpm) + " RPM"; color: card.accent; font.bold: true; font.pixelSize: Math.max(Style.font.body, Style.space(14)) }
            }
            PanelSlider {
                id: slider
                objectName: "fan-target-slider"
                width: parent.width
                bar: card.bar
                minimum: card.minimum; maximum: card.maximum; integer: true; step: 50
                value: card.targetRpm !== null ? card.targetRpm : card.minimum
                enabled: card.controlsEnabled
                activeFocusOnTab: true
                Accessible.name: card.nameText + " " + card.targetLabel
                onReleased: function(value) { if (card.visible && card.manual && card.controlsEnabled) card.targetRequested(card.snap(value)) }
                Keys.onPressed: function(event) {
                    if (!card.visible || !card.manual || !card.controlsEnabled) return
                    var key = Util.readingKey(event)
                    var value = key === Qt.Key_Left ? liveValue - step : key === Qt.Key_Right ? liveValue + step : key === Qt.Key_Home ? minimum : key === Qt.Key_End ? maximum : null
                    if (value !== null) { liveValue = card.snap(value); card.targetRequested(liveValue); event.accepted = true }
                }
            }
            Item {
                width: parent.width; height: minText.implicitHeight
                ThermalText { id: minText; anchors.left: parent.left; text: card.minimumLabel + " " + card.formatValue(card.minimum); color: Commons.Color.muted }
                ThermalText { anchors.right: parent.right; text: card.maximumLabel + " " + card.formatValue(card.maximum); color: Commons.Color.muted }
            }
            Row {
                width: parent.width
                spacing: Style.space(3)
                Repeater {
                    model: [card.snap(card.maximum * 0.25), card.snap(card.maximum * 0.5), card.maximum]
                    Button {
                        required property int index
                        required property int modelData
                        width: (parent.width - parent.spacing * 2) / 3
                        horizontalPadding: Style.space(4)
                        fontSize: Style.font.caption
                        text: card.presetLabels[index]
                        tooltipText: text + " · " + card.formatValue(modelData) + " RPM"
                        focusable: true
                        selected: card.targetRpm !== null && Math.abs(card.targetRpm - modelData) < 25
                        enabled: card.controlsEnabled
                        onClicked: if (card.visible && card.manual && card.controlsEnabled) card.targetRequested(modelData)
                    }
                }
            }
        }
    }
}
