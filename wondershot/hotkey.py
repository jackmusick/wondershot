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

On Windows: WinHotkeyBackend — RegisterHotKey, default Ctrl+Shift+PrintScreen.
"""

from __future__ import annotations

import ctypes
import sys
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

COMPONENT = "grabbit"
ACTION = "capture-region"
SERVICE = "org.kde.kglobalaccel"


class HotkeyBackend(QObject):
    """Platform seam for global capture hotkeys.

    Plain QObject base (abc.ABCMeta conflicts with Shiboken's metaclass);
    subclasses implement register().
    """

    pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False

    def register(self) -> bool:
        raise NotImplementedError


class NullHotkeyBackend(HotkeyBackend):
    """No global-hotkey integration on this platform yet (WS-E adds real
    Windows/macOS backends later)."""

    def register(self) -> bool:
        return False


class KGlobalAccelBackend(HotkeyBackend):
    def register(self) -> bool:
        """Listen for KGlobalAccel presses of a 'grabbit' component.

        Never makes method calls into the shortcut daemon (see module
        docstring); adding a signal match rule is harmless on any desktop.
        """
        from PySide6.QtCore import SLOT
        from PySide6.QtDBus import QDBusConnection

        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
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
    def _on_pressed(self, component: str, action: str,
                    _timestamp: int) -> None:
        if component == COMPONENT and action == ACTION:
            self.pressed.emit()


# -- Windows: RegisterHotKey message loop (WS-E) ------------------------------
#
# Default binding: Ctrl+Shift+PrintScreen. RegisterHotKey is bound to the
# registering thread, which must pump a message loop — so a dedicated
# QThread does both. Nothing here touches ctypes.windll at import or
# construction time; the Linux suite constructs these classes.

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_SNAPSHOT = 0x2C   # PrintScreen
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1


class _MSG(ctypes.Structure):
    # Portable field types (no ctypes.wintypes) so the class definition
    # is importable everywhere.
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


class _WinHotkeyThread(QThread):
    hotkey = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = threading.Event()
        self._ok = False
        self._native_tid = 0

    def wait_registered(self, timeout_ms: int) -> bool:
        self._registered.wait(timeout_ms / 1000)
        return self._ok

    def request_quit(self) -> None:
        if self._native_tid:
            ctypes.windll.user32.PostThreadMessageW(
                self._native_tid, WM_QUIT, 0, 0)

    def run(self) -> None:  # pragma: no cover — Windows only
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._native_tid = kernel32.GetCurrentThreadId()
        self._ok = bool(user32.RegisterHotKey(
            None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
            VK_SNAPSHOT))
        self._registered.set()
        if not self._ok:
            return  # e.g. another app owns the chord; backend stays inactive
        msg = _MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.hotkey.emit()
        user32.UnregisterHotKey(None, HOTKEY_ID)


class WinHotkeyBackend(HotkeyBackend):
    """Global Ctrl+Shift+PrintScreen via user32.RegisterHotKey."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None

    def register(self) -> bool:
        if self._thread is not None:
            return self.active
        self._thread = _WinHotkeyThread(self)
        self._thread.hotkey.connect(self.pressed)
        self._thread.start()
        self.active = self._thread.wait_registered(2000)
        return self.active

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.request_quit()
            self._thread.wait(2000)
            self._thread = None
            self.active = False


def create_hotkey_backend(parent=None) -> HotkeyBackend:
    if sys.platform.startswith("linux"):
        return KGlobalAccelBackend(parent)
    if sys.platform == "win32":
        return WinHotkeyBackend(parent)
    return NullHotkeyBackend(parent)
