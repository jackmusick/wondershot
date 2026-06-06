"""Native screen recorder with microphone audio.

Flow: xdg-desktop-portal ScreenCast (CreateSession → SelectSources →
Start → OpenPipeWireRemote) hands us a PipeWire fd + node; a
`gst-launch-1.0 -e` subprocess encodes it (x264 + AAC → mp4), mixing in
the microphone via pulsesrc. SIGINT triggers EOS so the mp4 finalizes
cleanly. A portal restore token is persisted, so the screen-share picker
only appears the first time.
"""

from __future__ import annotations

import os
import random
import shutil
import signal
import subprocess

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtDBus import (
    QDBusConnection,
    QDBusMessage,
    QDBusObjectPath,
)

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"


def mic_pulse_device(preferred_description: str = "") -> str:
    """Resolve a settings description to a pulse/pipewire source name."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:
        return ""
    devices = QMediaDevices.audioInputs()
    if not devices:
        return ""
    chosen = None
    if preferred_description:
        for d in devices:
            if d.description() == preferred_description:
                chosen = d
                break
    if chosen is None:
        chosen = QMediaDevices.defaultAudioInput() or devices[0]
    return bytes(chosen.id().data()).decode(errors="replace")


class ScreenRecorder(QObject):
    """Portal + PipeWire + GStreamer screen recorder."""

    started = Signal()
    finished = Signal(str)  # final file path
    failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.bus = QDBusConnection.sessionBus()
        self.recording = False
        self._proc: subprocess.Popen | None = None
        self._session: str | None = None
        self._step = None
        self._tmp = self._out = None
        self._fd = -1

    # -- public ------------------------------------------------------------

    def available(self) -> bool:
        return (shutil.which("gst-launch-1.0") is not None
                and self.bus.isConnected())

    def start(self) -> None:
        if self.recording or self._step is not None:
            return
        if not self.available():
            self.failed.emit("recording needs gstreamer (gst-launch-1.0)")
            return
        self._step = "create_session"
        token = self._request_token()
        self._listen(token)
        msg = self._method("CreateSession")
        msg.setArguments([{
            "handle_token": token,
            "session_handle_token": f"grabbit{random.randint(0, 2**31)}",
        }])
        self.bus.asyncCall(msg)

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            # -e turns SIGINT into EOS: the mp4 finalizes, then exits.
            self._proc.send_signal(signal.SIGINT)
            self._poll_exit(timeout_ms=15000)

    # -- portal dance ---------------------------------------------------------

    def _method(self, name: str) -> QDBusMessage:
        return QDBusMessage.createMethodCall(
            PORTAL_SERVICE, PORTAL_PATH, SCREENCAST_IFACE, name)

    def _request_token(self) -> str:
        return f"grabbit{random.randint(0, 2**31)}"

    def _listen(self, token: str) -> None:
        sender = self.bus.baseService()[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        from PySide6.QtCore import SLOT
        ok = self.bus.connect(PORTAL_SERVICE, path,
                              "org.freedesktop.portal.Request", "Response",
                              self, SLOT("_response(uint,QVariantMap)"))
        if not ok:
            self._step = None
            self.failed.emit("could not subscribe to portal response")

    @Slot("uint", "QVariantMap")
    def _response(self, code: int, results: dict) -> None:
        if code != 0:
            self._step = None
            if code == 1:
                self.failed.emit("screen share cancelled")
            else:
                self.failed.emit(f"portal error (code {code})")
            return
        step = self._step
        if step == "create_session":
            self._session = str(results.get("session_handle", ""))
            self._step = "select_sources"
            token = self._request_token()
            self._listen(token)
            options = {
                "handle_token": token,
                "types": 3,        # monitor | window
                "multiple": False,
                "cursor_mode": 2,  # embedded
                "persist_mode": 2,  # remember across restarts
            }
            restore = self.settings.screencast_token
            if restore:
                options["restore_token"] = restore
            msg = self._method("SelectSources")
            msg.setArguments([QDBusObjectPath(self._session), options])
            self.bus.asyncCall(msg)
        elif step == "select_sources":
            self._step = "start"
            token = self._request_token()
            self._listen(token)
            msg = self._method("Start")
            msg.setArguments([QDBusObjectPath(self._session), "",
                              {"handle_token": token}])
            self.bus.asyncCall(msg)
        elif step == "start":
            self._step = None
            restore = results.get("restore_token")
            if restore:
                self.settings.screencast_token = str(restore)
            streams = results.get("streams")
            node = self._first_node(streams)
            if node is None:
                self.failed.emit("portal returned no stream")
                return
            self._open_pipewire(node)

    @staticmethod
    def _first_node(streams) -> int | None:
        # streams arrives as [(node_id, {props}), ...] in QtDBus' demarshaling
        try:
            from PySide6.QtDBus import QDBusArgument  # noqa: F401
            if streams is None:
                return None
            for entry in streams:
                # entry may be a QDBusArgument-wrapped struct or a sequence
                if isinstance(entry, (list, tuple)) and entry:
                    return int(entry[0])
                value = getattr(entry, "variant", None)
                if callable(value):
                    inner = entry.variant()
                    if isinstance(inner, (list, tuple)) and inner:
                        return int(inner[0])
        except (TypeError, ValueError):
            pass
        return None

    def _open_pipewire(self, node: int) -> None:
        msg = self._method("OpenPipeWireRemote")
        msg.setArguments([QDBusObjectPath(self._session), {}])
        reply = self.bus.call(msg)  # blocking; returns the fd
        if reply.type() == QDBusMessage.ErrorMessage or not reply.arguments():
            self.failed.emit(f"OpenPipeWireRemote failed: {reply.errorMessage()}")
            return
        fd_wrapper = reply.arguments()[0]
        fd = fd_wrapper.fileDescriptor() if hasattr(
            fd_wrapper, "fileDescriptor") else int(fd_wrapper)
        self._fd = os.dup(fd)
        self._launch_gst(self._fd, node)

    # -- gstreamer ---------------------------------------------------------------

    def _launch_gst(self, fd: int, node: int) -> None:
        from .capture import timestamp_name, unique_path
        out = unique_path(self.settings.library_dir,
                          timestamp_name("Recording").replace(".png", ".mp4"))
        tmp_dir = os.path.join(self.settings.library_dir, ".rendering")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp = os.path.join(tmp_dir, os.path.basename(out))
        self._tmp, self._out = tmp, out

        args = [
            "gst-launch-1.0", "-e",
            "pipewiresrc", f"fd={fd}", f"path={node}", "do-timestamp=true",
            "!", "queue", "!", "videoconvert",
            "!", "video/x-raw,format=I420",
            "!", "x264enc", "speed-preset=veryfast", "tune=zerolatency",
            "bitrate=8000", "key-int-max=120",
            "!", "h264parse", "!", "queue", "!", "mux.",
        ]
        if self.settings.mic_enabled:
            device = mic_pulse_device(self.settings.mic_device)
            dev_arg = [f"device={device}"] if device else []
            args += [
                "pulsesrc", *dev_arg, "do-timestamp=true",
                "!", "queue", "!", "audioconvert", "!", "audioresample",
                "!", "avenc_aac", "bitrate=160000",
                "!", "aacparse", "!", "queue", "!", "mux.",
            ]
        args += ["mp4mux", "name=mux", "!", "filesink", f"location={tmp}"]

        os.set_inheritable(fd, True)
        try:
            self._proc = subprocess.Popen(
                args, pass_fds=[fd],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except OSError as e:
            self.failed.emit(f"could not start gstreamer: {e}")
            return
        # If the pipeline dies immediately (bad caps etc.), report it.
        QTimer.singleShot(1200, self._check_alive)
        self.recording = True
        self.started.emit()

    def _check_alive(self) -> None:
        if self._proc is not None and self._proc.poll() is not None:
            err = (self._proc.stderr.read().decode(errors="replace")
                   if self._proc.stderr else "")
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self.recording = False
            self._cleanup()
            self.failed.emit(f"recorder died: {tail[:160]}")

    def _poll_exit(self, timeout_ms: int) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            if timeout_ms <= 0:
                self._proc.kill()
            QTimer.singleShot(
                200, lambda: self._poll_exit(timeout_ms - 200))
            return
        self.recording = False
        ok = (self._proc.returncode == 0 and self._tmp
              and os.path.exists(self._tmp)
              and os.path.getsize(self._tmp) > 0)
        tmp, out = self._tmp, self._out
        self._cleanup()
        if ok:
            shutil.move(tmp, out)
            self.finished.emit(out)
        else:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
            self.failed.emit("recording did not finalize")

    def _cleanup(self) -> None:
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
        self._proc = None
        self._tmp = self._out = None
        if self._session:
            # closing the session releases the portal/PipeWire stream
            msg = QDBusMessage.createMethodCall(
                PORTAL_SERVICE, self._session,
                "org.freedesktop.portal.Session", "Close")
            self.bus.asyncCall(msg)
            self._session = None
