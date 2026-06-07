"""Screenshot capture backends for Wayland.

Primary backend on KDE: spectacle CLI (instant native region picker, no
permission prompts). Fallback: the xdg-desktop-portal Screenshot API, which
works on any Wayland compositor.
"""

from __future__ import annotations

import os
import random
import shutil
import time

from PySide6.QtCore import QObject, QProcess, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusMessage

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"


def timestamp_name(prefix: str = "Screenshot") -> str:
    return time.strftime(f"{prefix}_%Y%m%d_%H%M%S.png")


def unique_path(directory: str, name: str) -> str:
    path = os.path.join(directory, name)
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        path = f"{base}-{n}{ext}"
        n += 1
    return path


class CaptureManager(QObject):
    """Runs a capture and emits captured(path) or failed(message)."""

    captured = Signal(str)
    failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._proc: QProcess | None = None
        self._portal_pending_path: str | None = None
        self._pending_crop = None   # QRect: crop the next capture to this
        self._crop_virtual = None   # test seam; None = live screen union
        self._geom_query = None     # keep the KWin query alive

    # -- public API ----------------------------------------------------

    def capture_region(self) -> None:
        self._pending_crop = None
        self._capture("region")

    def capture_fullscreen(self) -> None:
        self._pending_crop = None
        self._capture("fullscreen")

    def capture_window(self) -> None:
        self._pending_crop = None
        self._capture("window")

    def capture_active_window(self) -> None:
        """KDE-only: crop a fullscreen shot to the active window's frame.

        Geometry comes from KWin scripting (kwin.py — defensive, timed
        out, feature-probed); then we reuse the normal fullscreen path
        and crop in _finish. No interactive pick."""
        from .kwin import ActiveWindowQuery
        self._pending_crop = None
        q = ActiveWindowQuery(self)
        self._geom_query = q
        q.finished.connect(self._geometry_ready)
        q.failed.connect(
            lambda msg: self.failed.emit(f"window geometry: {msg}"))
        q.start()

    def _geometry_ready(self, x: int, y: int, w: int, h: int) -> None:
        from PySide6.QtCore import QRect
        self._pending_crop = QRect(x, y, w, h)
        self._capture("fullscreen")

    # -- recording (v1: Spectacle's portal/PipeWire engine) --------------

    def record_region(self) -> bool:
        return self._record("region")

    def record_screen(self) -> bool:
        return self._record("screen")

    def _record(self, mode: str) -> bool:
        if not shutil.which("spectacle"):
            self.failed.emit("screen recording currently needs spectacle")
            return False
        out = unique_path(self.settings.library_dir,
                          timestamp_name("Recording").replace(".png", ".webm"))
        # Recording runs long and owns its own stop UI (Spectacle tray
        # button) — fully detach it.
        ok = QProcess.startDetached(
            "spectacle", ["-b", "-n", "-R", mode, "-o", out])
        if not ok:
            self.failed.emit("could not start spectacle recording")
        return ok

    # -- backend dispatch ----------------------------------------------

    def _capture(self, mode: str) -> None:
        backend = self.settings.backend
        if backend == "auto":
            backend = "spectacle" if shutil.which("spectacle") else "portal"
        if backend == "spectacle":
            self._spectacle(mode)
        else:
            # the Screenshot portal has no delay option; wait ourselves
            delay = self.settings.capture_delay * 1000
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                delay, lambda: self._portal(
                    interactive=(mode != "fullscreen")))

    # -- spectacle backend ----------------------------------------------

    def _spectacle(self, mode: str) -> None:
        if self._proc is not None:
            return  # capture already in flight
        out = unique_path(self.settings.library_dir, timestamp_name())
        flag = {"region": "-r", "fullscreen": "-f", "window": "-a"}[mode]
        self._proc = QProcess(self)
        self._proc.finished.connect(lambda code, _st: self._spectacle_done(code, out))
        # -b background, -n no notification popup
        args = ["-b", "-n", flag, "-o", out]
        if self.settings.capture_cursor:
            args.insert(2, "-p")  # include pointer
        if self.settings.capture_delay:
            args += ["-d", str(self.settings.capture_delay * 1000)]
        self._proc.start("spectacle", args)

    def _finish(self, path: str) -> None:
        """Common tail for both backends: apply a pending window crop."""
        crop, self._pending_crop = self._pending_crop, None
        if crop is not None:
            from .kwin import crop_file_to_global_rect
            virtual = self._crop_virtual
            if virtual is None:
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                virtual = screen.virtualGeometry() if screen else None
            if virtual is not None:
                # False = unusable rect; degrade to the full shot
                crop_file_to_global_rect(path, crop, virtual)
        self.captured.emit(path)

    def _spectacle_done(self, code: int, out: str) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.deleteLater()
        if os.path.exists(out) and os.path.getsize(out) > 0:
            self._finish(out)
        elif code != 0:
            self.failed.emit(f"spectacle exited with code {code}")
        # code 0 with no file = user cancelled the picker; stay silent.

    # -- portal backend ---------------------------------------------------

    def _portal(self, interactive: bool = True) -> None:
        bus = QDBusConnection.sessionBus()
        sender = bus.baseService()[1:].replace(".", "_")
        token = f"grabbit{random.randint(0, 2**31)}"
        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        from PySide6.QtCore import SLOT
        ok = bus.connect(
            PORTAL_SERVICE,
            request_path,
            "org.freedesktop.portal.Request",
            "Response",
            self,
            SLOT("_portal_response(uint,QVariantMap)"),
        )
        if not ok:
            self.failed.emit("could not subscribe to portal response")
            return
        msg = QDBusMessage.createMethodCall(
            PORTAL_SERVICE, PORTAL_PATH, "org.freedesktop.portal.Screenshot", "Screenshot"
        )
        msg.setArguments(["", {"handle_token": token, "interactive": interactive}])
        bus.asyncCall(msg)

    @Slot("uint", "QVariantMap")
    def _portal_response(self, code: int, results: dict) -> None:
        if code != 0:
            return  # user cancelled
        uri = str(results.get("uri", ""))
        if not uri.startswith("file://"):
            self.failed.emit(f"portal returned unusable uri: {uri!r}")
            return
        src = uri[len("file://"):]
        dest = unique_path(self.settings.library_dir, timestamp_name())
        try:
            if os.path.dirname(src) == self.settings.library_dir:
                dest = src
            else:
                shutil.move(src, dest)
        except OSError as e:
            self.failed.emit(f"could not move screenshot: {e}")
            return
        self._finish(dest)
