"""Global hotkey support.

v1 intentionally does NOT auto-register with KGlobalAccel: on Plasma 6 the
shortcut daemon lives inside KWin, and a mistyped D-Bus call can abort the
compositor (observed on kwin 6.6.5 — `dbus type invalid 0 not a basic type`
→ _dbus_abort). Until that's done properly with typed QtDBus arguments and
tested against a disposable session, the supported path is a DE shortcut
bound to `grabbit --capture`, which talks to the running instance over the
single-instance socket (System Settings → Shortcuts → Custom → Command).

We still listen for a `grabbit` KGlobalAccel component signal so a manually
registered shortcut (or a future safe registration) fires the capture.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtDBus import QDBusConnection

COMPONENT = "grabbit"
ACTION = "capture-region"
SERVICE = "org.kde.kglobalaccel"


class HotkeyManager(QObject):
    pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False

    def register(self) -> bool:
        """Listen for KGlobalAccel presses of a 'grabbit' component.

        Never makes method calls into the shortcut daemon (see module
        docstring); adding a signal match rule is harmless on any desktop.
        """
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
        from PySide6.QtCore import SLOT
        ok = bus.connect(
            SERVICE,
            f"/component/{COMPONENT}",
            "org.kde.kglobalaccel.Component",
            "globalShortcutPressed",
            self,
            SLOT("_on_pressed(QString,QString,qlonglong)"),
        )
        self.active = bool(ok)
        return self.active

    @Slot(str, str, "qlonglong")
    def _on_pressed(self, component: str, action: str, _timestamp: int) -> None:
        if component == COMPONENT and action == ACTION:
            self.pressed.emit()
