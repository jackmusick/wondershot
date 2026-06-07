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
MOD_ALT = 0x0001
MOD_WIN = 0x0008
VK_SNAPSHOT = 0x2C   # PrintScreen
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1

# Qt key name -> virtual-key code, for keys whose VK isn't ord(char).
_VK_NAMED = {
    "PRINT": VK_SNAPSHOT, "SYSREQ": VK_SNAPSHOT,
    "SPACE": 0x20, "TAB": 0x09, "RETURN": 0x0D, "ENTER": 0x0D,
    "ESC": 0x1B, "ESCAPE": 0x1B, "BACKSPACE": 0x08,
    "INS": 0x2D, "INSERT": 0x2D, "DEL": 0x2E, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PGDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "PAUSE": 0x13, "SCROLLLOCK": 0x91,
    **{f"F{i}": 0x6F + i for i in range(1, 25)},  # F1=0x70
}


def qt_to_win(chord: str) -> tuple[int, int] | None:
    """Portable QKeySequence string -> (win32 modifiers, vk), or None.

    Pure (no ctypes calls) so the converter is testable everywhere.
    Only single-chord sequences make sense for RegisterHotKey.
    """
    parts = [p.strip() for p in chord.split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key = None
    for p in parts:
        up = p.upper()
        if up == "CTRL":
            mods |= MOD_CONTROL
        elif up == "SHIFT":
            mods |= MOD_SHIFT
        elif up == "ALT":
            mods |= MOD_ALT
        elif up in ("META", "WIN"):
            mods |= MOD_WIN
        elif key is None:
            key = up
        else:
            return None  # two non-modifier keys: not a hotkey chord
    if key is None:
        return None
    if key in _VK_NAMED:
        return mods, _VK_NAMED[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return mods, ord(key)  # VK for A-Z/0-9 == ASCII uppercase
    return None


class _MSG(ctypes.Structure):
    # Portable field types (no ctypes.wintypes) so the class definition
    # is importable everywhere.
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


class _WinHotkeyThread(QThread):
    hotkey = Signal()

    def __init__(self, parent=None, mods=MOD_CONTROL | MOD_SHIFT,
                 vk=VK_SNAPSHOT):
        super().__init__(parent)
        self._mods = mods
        self._vk = vk
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
            None, HOTKEY_ID, self._mods | MOD_NOREPEAT, self._vk))
        self._registered.set()
        if not self._ok:
            return  # e.g. another app owns the chord; backend stays inactive
        msg = _MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.hotkey.emit()
        user32.UnregisterHotKey(None, HOTKEY_ID)


class WinHotkeyBackend(HotkeyBackend):
    """Settings-driven global hotkey via user32.RegisterHotKey.

    The chord comes from settings.hotkey_capture (QKeySequence string,
    editable in Settings → General); rebind() re-registers live after
    the user changes it. Unparseable/conflicting chords leave the
    backend inactive rather than crashing."""

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.settings = settings
        self._thread = None

    def _chord(self) -> tuple[int, int]:
        chord = getattr(self.settings, "hotkey_capture", "") or ""
        return qt_to_win(chord) or (MOD_CONTROL | MOD_SHIFT, VK_SNAPSHOT)

    def register(self) -> bool:
        if self._thread is not None:
            return self.active
        mods, vk = self._chord()
        self._thread = _WinHotkeyThread(self, mods=mods, vk=vk)
        self._thread.hotkey.connect(self.pressed)
        self._thread.start()
        self.active = self._thread.wait_registered(2000)
        return self.active

    def rebind(self) -> bool:
        """Re-register after settings.hotkey_capture changed."""
        self.stop()
        return self.register()

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.request_quit()
            self._thread.wait(2000)
            self._thread = None
            self.active = False


def create_hotkey_backend(parent=None, settings=None) -> HotkeyBackend:
    if sys.platform.startswith("linux"):
        return KGlobalAccelBackend(parent)
    if sys.platform == "win32":
        return WinHotkeyBackend(parent, settings=settings)
    return NullHotkeyBackend(parent)
