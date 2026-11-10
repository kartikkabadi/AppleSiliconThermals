import QtQuick
import qs.Ui as Ui

// Host styling and keyboard behavior with explicit assistive-technology semantics.
Ui.Button {
    id: control
    property bool checkable: false
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.checkable: checkable
    Accessible.checked: checkable && selected
    Accessible.focusable: focusable
    Accessible.onPressAction: if (enabled && visible) clicked()
}
