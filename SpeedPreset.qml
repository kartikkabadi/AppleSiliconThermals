import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BorderSurface {
    id: control
    property string title: ""
    property string detail: ""
    property string glyph: ""
    property bool selected: false
    signal clicked()
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: title + ", " + detail
    Accessible.checkable: true
    Accessible.focusable: true
    Accessible.checked: selected
    Accessible.onPressAction: if (enabled && visible) clicked()
    implicitHeight: content.implicitHeight + Style.space(18)
    radius: Style.cornerRadius
    opacity: enabled ? 1 : 0.45
    color: selected ? Style.selectedFillFor(Commons.Color.foreground, Commons.Color.accent) : mouse.containsMouse ? Style.hoverFillFor(Commons.Color.foreground, Commons.Color.accent) : Style.normalFillFor(Commons.Color.foreground, Commons.Color.accent)
    borderSpec: Border.flat(activeFocus || selected ? Commons.Color.accent : Util.alpha(Commons.Color.foreground, 0.12), Math.max(1, Style.space(1)))
    Keys.onReturnPressed: if (enabled) clicked()
    Keys.onEnterPressed: if (enabled) clicked()
    Keys.onSpacePressed: if (enabled) clicked()
    Column {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: Style.space(9)
        spacing: Style.space(4)
        ThermalText { width: parent.width; text: control.glyph + "  " + control.title; font.bold: control.selected; horizontalAlignment: Text.AlignHCenter; maximumLineCount: 1; elide: Text.ElideRight }
        ThermalText { width: parent.width; text: control.detail; color: Commons.Color.muted; horizontalAlignment: Text.AlignHCenter; maximumLineCount: 1; elide: Text.ElideRight }
    }
    MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { control.forceActiveFocus(); control.clicked() } }
}
