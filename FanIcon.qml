import QtQuick
import qs.Commons
import qs.Ui

Item {
    id: icon
    property string text: ""
    property color color: "white"
    property string fontFamily: Style.font.family
    property real fontSize: Style.font.body
    property bool fan: false
    property bool spinning: false
    property real phase: 0
    readonly property real periodMs: Style.duration(1200)
    width: 16
    height: 16

    OpticalGlyph {
        id: glyph
        objectName: "fan-icon-glyph"
        anchors.fill: parent
        text: icon.text
        color: icon.color
        fontFamily: icon.fontFamily
        fontSize: icon.fontSize
        paintedSize: Style.bar.iconSize
        transform: [
            Scale {
                origin.x: glyph.paintedCenterX; origin.y: glyph.paintedCenterY
                xScale: icon.fan ? 1.04 : 1
                yScale: xScale
            },
            Rotation {
                origin.x: glyph.paintedCenterX; origin.y: glyph.paintedCenterY
                angle: icon.fan ? icon.phase : 0
            }
        ]
    }
    // Accumulate frame time without restarting a loop when RPM telemetry changes.
    // Keep the phase while paused; warning and temperature glyphs stay upright.
    FrameAnimation {
        running: icon.spinning && icon.fan && !Style.reduceMotion && icon.periodMs > 0
        onTriggered: icon.phase = (icon.phase + frameTime * 360000 / icon.periodMs) % 360
    }
}
