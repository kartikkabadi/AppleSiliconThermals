import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BorderSurface {
    id: card
    property string labelText: ""
    property string valueText: "—"
    property string unitText: ""
    property string iconText: ""
    property color valueColor: Commons.Color.foreground
    color: Style.normalFillFor(Commons.Color.foreground, Commons.Color.accent)
    borderSpec: Border.flat(Util.alpha(Commons.Color.foreground, 0.1), 1)
    radius: Style.cornerRadius
    implicitHeight: content.implicitHeight + Style.space(24)
    Column {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: Style.space(12)
        spacing: Style.space(7)
        ThermalText { width: parent.width; text: card.iconText + "  " + card.labelText; color: Commons.Color.muted }
        Row {
            spacing: Style.space(5)
            ThermalText { text: card.valueText; color: card.valueColor; font.pixelSize: Math.max(Style.font.title, Style.space(20)); font.bold: true }
            ThermalText { text: card.unitText; color: Commons.Color.muted; anchors.bottom: parent.bottom; anchors.bottomMargin: Style.space(3) }
        }
    }
}
