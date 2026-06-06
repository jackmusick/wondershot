"""Native screen recorder with microphone audio.

Flow: xdg-desktop-portal ScreenCast (CreateSession → SelectSources →
Start → OpenPipeWireRemote) hands us a PipeWire fd + node; a
`gst-launch-1.0 -e` subprocess encodes it (x264 + AAC → mp4), mixing in
the microphone via pulsesrc. SIGINT triggers EOS so the mp4 finalizes
cleanly. A portal restore token is persisted, so the screen-share picker
only appears the first time.

The portal D-Bus traffic uses Gio/GLib (PyGObject): the portal insists on
uint32-typed options, which PySide6's QtDBus cannot produce. Qt's Linux
event dispatcher is GLib-based, so Gio signal callbacks fire inside the
Qt event loop with no extra plumbing.
"""

from __future__ import annotations

import os
import random
import shutil
import signal
import subprocess

from PySide6.QtCore import QObject, QTimer, Signal

try:
    import gi
    from gi.repository import Gio, GLib
    _HAVE_GIO = True
except ImportError:
    _HAVE_GIO = False

_element_cache: dict[str, bool] = {}


def _have_gst_element(name: str) -> bool:
    if name not in _element_cache:
        _element_cache[name] = subprocess.run(
            ["gst-inspect-1.0", name], capture_output=True).returncode == 0
    return _element_cache[name]


PORTAL_BUS = "org.freedesktop.portal.Desktop"
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
        self.recording = False
        self._busy = False
        self._proc: subprocess.Popen | None = None
        self._session: str | None = None
        self._tmp = self._out = None
        self._fd = -1
        self._conn = None
        self._subs: list[int] = []
        self._stopping = False

    # -- public ------------------------------------------------------------

    def available(self) -> bool:
        return _HAVE_GIO and shutil.which("gst-launch-1.0") is not None

    def start(self) -> None:
        if self.recording or self._busy:
            return
        if not self.available():
            self.failed.emit(
                "recording needs python3-gobject and gst-launch-1.0")
            return
        self._busy = True
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            token = self._token()
            session_token = self._token()
            self._on_request(token, self._created)
            self._call("CreateSession", GLib.Variant("(a{sv})", ({
                "handle_token": GLib.Variant("s", token),
                "session_handle_token": GLib.Variant("s", session_token),
            },)))
        except GLib.Error as e:
            self._fail(f"portal unavailable: {e.message}")

    def stop(self) -> None:
        if self._stopping:
            return  # double-stop (tray + toolbar) must not double-finalize
        if self._proc is not None and self._proc.poll() is None:
            self._stopping = True
            # -e turns SIGINT into EOS: the mp4 finalizes, then exits.
            self._proc.send_signal(signal.SIGINT)
            self._poll_exit(timeout_ms=15000)

    # -- portal plumbing -------------------------------------------------------

    @staticmethod
    def _token() -> str:
        return f"grabbit{random.randint(0, 2**31)}"

    def _sender_path(self, token: str) -> str:
        sender = self._conn.get_unique_name()[1:].replace(".", "_")
        return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    def _on_request(self, token: str, callback) -> None:
        """Subscribe for the Response of the request named by token."""
        def wrapper(_c, _s, _p, _i, _m, params, sub=[None]):
            code, results = params.unpack()
            self._unsubscribe()
            if code != 0:
                self._fail("screen share cancelled" if code == 1
                           else f"portal error (code {code})")
                return
            try:
                callback(results)
            except GLib.Error as e:
                self._fail(f"portal call failed: {e.message}")
        sub_id = self._conn.signal_subscribe(
            PORTAL_BUS, "org.freedesktop.portal.Request", "Response",
            self._sender_path(token), None,
            Gio.DBusSignalFlags.NONE, wrapper)
        self._subs.append(sub_id)

    def _unsubscribe(self) -> None:
        for sub in self._subs:
            self._conn.signal_unsubscribe(sub)
        self._subs = []

    def _call(self, method: str, args: GLib.Variant):
        return self._conn.call_sync(
            PORTAL_BUS, PORTAL_PATH, SCREENCAST_IFACE, method, args,
            None, Gio.DBusCallFlags.NONE, 3000, None)

    # -- the dance ---------------------------------------------------------------

    def _created(self, results: dict) -> None:
        self._session = results.get("session_handle", "")
        if not self._session:
            self._fail("portal returned no session")
            return
        token = self._token()
        options = {
            "handle_token": GLib.Variant("s", token),
            "types": GLib.Variant("u", 3),        # monitor | window
            "multiple": GLib.Variant("b", False),
            "cursor_mode": GLib.Variant("u", 2),  # embedded
            "persist_mode": GLib.Variant("u", 2),  # remember permanently
        }
        restore = self.settings.screencast_token
        if restore:
            options["restore_token"] = GLib.Variant("s", restore)
        self._on_request(token, self._sources_selected)
        self._call("SelectSources",
                   GLib.Variant("(oa{sv})", (self._session, options)))

    def _sources_selected(self, _results: dict) -> None:
        token = self._token()
        self._on_request(token, self._started_cb)
        self._call("Start", GLib.Variant("(osa{sv})", (
            self._session, "",
            {"handle_token": GLib.Variant("s", token)})))

    def _started_cb(self, results: dict) -> None:
        restore = results.get("restore_token")
        if restore:
            self.settings.screencast_token = str(restore)
        streams = results.get("streams") or []
        if not streams:
            self._fail("portal returned no stream")
            return
        node = int(streams[0][0])
        try:
            reply, fd_list = self._conn.call_with_unix_fd_list_sync(
                PORTAL_BUS, PORTAL_PATH, SCREENCAST_IFACE,
                "OpenPipeWireRemote",
                GLib.Variant("(oa{sv})", (self._session, {})),
                None, Gio.DBusCallFlags.NONE, 3000, None, None)
            fd_index = reply.unpack()[0]
            self._fd = fd_list.get(fd_index)
        except GLib.Error as e:
            self._fail(f"OpenPipeWireRemote failed: {e.message}")
            return
        self._launch_gst(self._fd, node)

    def _fail(self, message: str) -> None:
        self._busy = False
        self._close_session()
        self.failed.emit(message)

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
            # webrtcdsp: noise suppression + auto gain + high-pass — raw
            # pulsesrc picks up every fan and echo in the room.
            dsp = []
            if (self.settings.noise_suppression
                    and _have_gst_element("webrtcdsp")):
                dsp = ["!", "audio/x-raw,rate=48000,channels=1",
                       "!", "webrtcdsp", "echo-cancel=false",
                       "noise-suppression=true", "gain-control=true",
                       "high-pass-filter=true"]
            args += [
                "pulsesrc", *dev_arg, "do-timestamp=true",
                "!", "queue", "!", "audioconvert", "!", "audioresample",
                *dsp,
                "!", "audioconvert",
                "!", "avenc_aac", "bitrate=160000",
                "!", "aacparse", "!", "queue", "!", "mux.",
            ]
        args += ["mp4mux", "name=mux", "!", "filesink", f"location={tmp}"]

        os.set_inheritable(fd, True)
        log_dir = os.path.join(
            os.environ.get("XDG_CACHE_HOME",
                           os.path.expanduser("~/.cache")), "grabbit")
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "recorder.log")
        try:
            log = open(self.log_path, "wb")
            log.write((" ".join(args) + "\n\n").encode())
            log.flush()
            self._proc = subprocess.Popen(
                args, pass_fds=[fd], stdout=log, stderr=log)
        except OSError as e:
            self._fail(f"could not start gstreamer: {e}")
            return
        # If the pipeline dies immediately (bad caps etc.), report it.
        QTimer.singleShot(1200, self._check_alive)
        self._busy = False
        self.recording = True
        self.started.emit()

    def _log_tail(self) -> str:
        try:
            with open(self.log_path, errors="replace") as f:
                lines = [ln for ln in f.read().strip().splitlines()
                         if "ERROR" in ln or "WARN" in ln] or ["unknown"]
            return lines[-1]
        except OSError:
            return "unknown"

    def _check_alive(self) -> None:
        if self._proc is not None and self._proc.poll() is not None:
            self.recording = False
            self._cleanup()
            self.failed.emit(
                f"recorder died: {self._log_tail()[:160]} "
                f"(full log: {self.log_path})")

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
            self.failed.emit(f"recording did not finalize "
                             f"(log: {getattr(self, 'log_path', '?')})")

    def _close_session(self) -> None:
        if self._session and self._conn is not None:
            try:
                self._conn.call_sync(
                    PORTAL_BUS, self._session,
                    "org.freedesktop.portal.Session", "Close",
                    None, None, Gio.DBusCallFlags.NONE, 1000, None)
            except GLib.Error:
                pass
            self._session = None

    def _cleanup(self) -> None:
        self._stopping = False
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
        self._proc = None
        self._tmp = self._out = None
        self._close_session()
