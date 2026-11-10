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
    property color accent: Commons.Color.accent
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
        ThermalText { width: parent.width; text: card.targetText; color: Commons.Color.muted }
        ThermalText { width: parent.width; text: card.rangeText; color: Commons.Color.muted }
    }
}
