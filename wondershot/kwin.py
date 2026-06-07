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


# -- the query object ---------------------------------------------------------

class _DBusTransport:
    """Real session-bus transport. Thin glue — tests use FakeTransport."""

    def __init__(self):
        from PySide6.QtDBus import QDBusConnection
        self._bus = QDBusConnection.sessionBus()

    def service_name(self) -> str:
        return self._bus.baseService()

    def register(self, path: str, obj) -> bool:
        from PySide6.QtDBus import QDBusConnection
        return self._bus.registerObject(
            path, obj, QDBusConnection.ExportAllSlots)

    def unregister(self, path: str) -> None:
        self._bus.unregisterObject(path)

    def call(self, service, path, iface, method, args):
        """Blocking call with a hard 1 s timeout. None on any error."""
        from PySide6.QtDBus import QDBus, QDBusMessage
        msg = QDBusMessage.createMethodCall(service, path, iface, method)
        msg.setArguments(list(args))
        reply = self._bus.call(msg, QDBus.Block, 1000)
        if reply.type() != QDBusMessage.ReplyMessage:
            return None
        a = reply.arguments()
        return a[0] if a else True


class ActiveWindowQuery(QObject):
    """One-shot: emit finished(x, y, w, h) for the active window, or failed(msg).

    KWin runs our tiny script (build_geometry_script) which calls our
    registered `geometry` slot back with one string. Defensive posture
    throughout — see the module docstring.
    """

    finished = Signal(int, int, int, int)
    failed = Signal(str)

    def __init__(self, parent=None, transport=None, timeout_ms: int = 2000):
        super().__init__(parent)
        self._transport = transport
        self._script_id: int | None = None
        self._tmp: str | None = None
        self._done = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(
            lambda: self._fail("KWin did not answer (timeout)"))

    def _t(self):
        if self._transport is None:
            self._transport = _DBusTransport()
        return self._transport

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        t = self._t()
        if not t.register(CALLBACK_PATH, self):
            self._fail("could not register D-Bus callback object",
                       registered=False)
            return
        script = build_geometry_script(t.service_name(), CALLBACK_PATH,
                                       CALLBACK_IFACE, CALLBACK_METHOD)
        fd, self._tmp = tempfile.mkstemp(suffix=".js",
                                         prefix="wondershot-kwin-")
        with os.fdopen(fd, "w") as f:
            f.write(script)
        # clear any stale copy left by a previous crash, then load
        t.call(*build_unload_call(PLUGIN_NAME))
        reply = t.call(*build_load_call(self._tmp, PLUGIN_NAME))
        if reply is None:
            self._fail("KWin loadScript failed")
            return
        try:
            self._script_id = int(reply)
        except (TypeError, ValueError):
            self._fail("KWin loadScript returned no script id")
            return
        if t.call(*build_run_call(self._script_id)) is None:
            self._fail("KWin script run failed")
            return
        self._timer.start()

    # -- KWin's script calls this back (via D-Bus, ExportAllSlots) ----------

    @Slot(str)
    def geometry(self, text: str) -> None:
        if self._done:
            return  # straggler after failure/timeout
        rect = parse_geometry_reply(text)
        if rect is None:
            self._fail("no active window")
            return
        self._done = True
        self._cleanup()
        self.finished.emit(*rect)

    # -- teardown -------------------------------------------------------------

    def _fail(self, msg: str, registered: bool = True) -> None:
        if self._done:
            return
        self._done = True
        if registered:
            self._cleanup()
        self.failed.emit(msg)

    def _cleanup(self) -> None:
        self._timer.stop()
        t = self._t()
        if self._script_id is not None:
            t.call(*build_stop_call(self._script_id))
        t.call(*build_unload_call(PLUGIN_NAME))
        t.unregister(CALLBACK_PATH)
        if self._tmp:
            try:
                os.unlink(self._tmp)
            except OSError:
                pass
            self._tmp = None
