"""KWin scripting D-Bus: KDE probe + active-window frame geometry.

DANGER ZONE — KWin hosts the Wayland compositor. A malformed D-Bus call
into it has aborted KWin before (KGlobalAccel, kwin 6.6.5 — see
ROADMAP.md "Platform landmines" and hotkey.py's module docstring).
Rules in this module:

- only the documented org.kde.kwin.Scripting methods are called
  (loadScript / unloadScript, Script.run / Script.stop), with plain
  string/int arguments — never dicts, never variants;
- the geometry answer travels KWin→us as a single comma-joined STRING
  via callDBus from the injected script, so we never depend on KWin's
  number marshalling and our receiving slot is a simple @Slot(str);
- every call has a hard timeout; any failure is reported via failed()
  and the feature simply doesn't exist — no retries, no dialogs.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QObject, QRect, QTimer, Signal, Slot

SERVICE = "org.kde.KWin"
SCRIPTING_PATH = "/Scripting"
SCRIPTING_IFACE = "org.kde.kwin.Scripting"
SCRIPT_IFACE = "org.kde.kwin.Script"
PLUGIN_NAME = "wondershot-active-window"
CALLBACK_PATH = "/wondershot/kwin"
CALLBACK_IFACE = "com.wondershot.kwin"
CALLBACK_METHOD = "geometry"


# -- feature probe -----------------------------------------------------------

def is_kde(env=None) -> bool:
    env = os.environ if env is None else env
    return "kde" in env.get("XDG_CURRENT_DESKTOP", "").lower()


def kwin_available() -> bool:
    """Cheap startup probe: KDE session + the KWin service on the bus.

    Never calls INTO KWin — just asks the bus daemon who's registered.
    """
    if not is_kde():
        return False
    try:
        from PySide6.QtDBus import QDBusConnection
        bus = QDBusConnection.sessionBus()
        return (bus.isConnected()
                and bool(bus.interface().isServiceRegistered(SERVICE)))
    except Exception:  # noqa: BLE001 — probe must never raise
        return False


# -- script text -----------------------------------------------------------

def build_geometry_script(service: str, path: str, iface: str,
                          method: str) -> str:
    """JS for KWin: report the active window's frame geometry back to us.

    activeWindow is KWin 6; activeClient the KWin 5 name — try both.
    The reply is one string ("x,y,w,h"), empty when there is no active
    window, so the D-Bus signature is always a lone 's'.
    """
    return (
        "var w = workspace.activeWindow || workspace.activeClient;\n"
        "if (w && w.frameGeometry) {\n"
        "    var g = w.frameGeometry;\n"
        f'    callDBus("{service}", "{path}", "{iface}", "{method}",\n'
        '             "" + g.x + "," + g.y + "," + g.width + "," + g.height);\n'
        "} else {\n"
        f'    callDBus("{service}", "{path}", "{iface}", "{method}", "");\n'
        "}\n"
    )


def parse_geometry_reply(text: str):
    """'x,y,w,h' -> (x, y, w, h) ints, or None for anything unusable."""
    parts = text.split(",")
    if len(parts) != 4:
        return None
    try:
        x, y, w, h = (int(float(p)) for p in parts)
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


# -- D-Bus call builders (pure; args are str/int ONLY — see module doc) -----

def build_load_call(script_path: str, plugin: str):
    return (SERVICE, SCRIPTING_PATH, SCRIPTING_IFACE, "loadScript",
            [script_path, plugin])


def build_run_call(script_id: int):
    return (SERVICE, f"/Scripting/Script{script_id}", SCRIPT_IFACE, "run", [])


def build_stop_call(script_id: int):
    return (SERVICE, f"/Scripting/Script{script_id}", SCRIPT_IFACE, "stop", [])


def build_unload_call(plugin: str):
    return (SERVICE, SCRIPTING_PATH, SCRIPTING_IFACE, "unloadScript",
            [plugin])


# -- crop math ----------------------------------------------------------------

def map_global_rect(rect: QRect, virtual: QRect, img_w: int,
                    img_h: int) -> QRect:
    """Map a global (logical) rect into a fullscreen image's pixel space.

    The fullscreen capture covers the virtual-desktop union of all
    screens; under HiDPI its pixel size exceeds the logical union, so
    scale by image/virtual per axis, translate off the union origin
    (which can be negative — left monitors), and clamp to the image.
    """
    if (virtual.width() <= 0 or virtual.height() <= 0
            or img_w <= 0 or img_h <= 0):
        return QRect()
    sx = img_w / virtual.width()
    sy = img_h / virtual.height()
    mapped = QRect(round((rect.x() - virtual.x()) * sx),
                   round((rect.y() - virtual.y()) * sy),
                   round(rect.width() * sx),
                   round(rect.height() * sy))
    return mapped.intersected(QRect(0, 0, img_w, img_h))


def crop_file_to_global_rect(path: str, rect: QRect, virtual: QRect) -> bool:
    """Crop the image at `path` in place to the global rect. False = no-op."""
    from PySide6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        return False
    target = map_global_rect(rect, virtual, img.width(), img.height())
    if target.isEmpty():
        return False
    return img.copy(target).save(path)
