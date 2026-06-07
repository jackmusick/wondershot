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
import sys
import signal
import subprocess
import time

from PySide6.QtCore import QObject, QTimer, Signal

try:
    import gi
    from gi.repository import Gio, GLib
    _HAVE_GIO = True
except ImportError:
    _HAVE_GIO = False


def log_dir() -> str:
    """Per-platform cache dir for recorder logs (honors XDG on Linux)."""
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(
        QStandardPaths.GenericCacheLocation)
    return os.path.join(base, "wondershot")


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


def sweep_stale_tmp(tmp_dir: str, max_age_s: int = 3600) -> None:
    """Remove finalize leftovers from crashed/quit-while-recording runs.

    2026-06-06 forensics: four orphaned mp4s in <library>/.rendering.
    A live recording's tmp has a fresh mtime (filesink writes
    continuously), so anything older than max_age_s is dead.
    """
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        return
    now = time.time()
    for name in names:
        path = os.path.join(tmp_dir, name)
        try:
            if now - os.path.getmtime(path) > max_age_s:
                os.unlink(path)
        except OSError:
            pass


class ScreenRecorder(QObject):
    """Portal + PipeWire + GStreamer screen recorder."""

    started = Signal()
    stopping = Signal()  # a stop transition began (whichever control asked)
    finished = Signal(str)  # final file path
    failed = Signal(str)
    tick = Signal(str)  # elapsed time ("1:05"), once a second while recording

    # Finalize escalation ladder. gst-launch -e can wedge in "Waiting for
    # EOS" indefinitely (observed 2026-06-06: pipeline still draining-
    # failing 3+ min after SIGINT — journal pipewire-pulse overruns,
    # orphaned .rendering tmp). A SECOND SIGINT makes gst-launch abort
    # the EOS wait and exit; SIGKILL is the last resort.
    GRACE_MS = 5000
    KILL_MS = 10000

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
        self._watchdog: QTimer | None = None
        self._started_at: float | None = None
        self.log_path = ""

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
        if self._proc is None:
            return
        self._stopping = True
        self.stopping.emit()
        if self._proc.poll() is None:
            # -e turns SIGINT into EOS: the mp4 finalizes, then exits.
            self._proc.send_signal(signal.SIGINT)
        # Even if the pipeline already died (mux error etc.), finalize so
        # finished/failed always fires — the UI must never stay "Stopping".
        self._poll_exit(elapsed_ms=0)

    # -- portal plumbing -------------------------------------------------------

    @staticmethod
    def _token() -> str:
        return f"grabbit{random.randint(0, 2**31)}"

    # Restore-token policy hooks. The recorder reuses its persisted
    # ScreenCast grant so the share picker shows only once; subclasses
    # that need a fresh pick per session (scroll capture) override BOTH:
    # returning "" forces the picker, and a no-op save keeps the scroll
    # grant from clobbering the recorder's stored token.
    def _restore_token(self) -> str:
        return self.settings.screencast_token

    def _save_restore_token(self, token: str) -> None:
        self.settings.screencast_token = token

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
        restore = self._restore_token()
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
            self._save_restore_token(str(restore))
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

    def _gst_args(self, fd: int, node: int, tmp: str) -> list[str]:
        args = [
            "gst-launch-1.0", "-e",
            "pipewiresrc", f"fd={fd}", f"path={node}", "do-timestamp=true",
            "!", "queue", "!", "videoconvert",
            # pipewiresrc intermittently emits buffers with no PTS (fatal
            # to mp4mux: "Buffer has no PTS"); videorate drops them and
            # turns the damage-driven stream into clean CFR.
            "!", "videorate",
            "!", "video/x-raw,format=I420,framerate=30/1",
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
                # measured on this hardware: NS very-high without AGC has a
                # 22dB lower ambient floor than raw, 8dB lower than NS+AGC
                # (AGC re-amplifies room noise between words)
                dsp = ["!", "audio/x-raw,rate=48000,channels=1",
                       "!", "webrtcdsp", "echo-cancel=false",
                       "noise-suppression=true",
                       "noise-suppression-level=very-high",
                       "gain-control=false",
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
        return args

    def _launch_gst(self, fd: int, node: int) -> None:
        from .capture import timestamp_name, unique_path
        out = unique_path(self.settings.library_dir,
                          timestamp_name("Recording").replace(".png", ".mp4"))
        tmp_dir = os.path.join(self.settings.library_dir, ".rendering")
        os.makedirs(tmp_dir, exist_ok=True)
        sweep_stale_tmp(tmp_dir)
        tmp = os.path.join(tmp_dir, os.path.basename(out))
        self._tmp, self._out = tmp, out
        args = self._gst_args(fd, node, tmp)

        os.set_inheritable(fd, True)
        logs = log_dir()
        os.makedirs(logs, exist_ok=True)
        self.log_path = os.path.join(logs, "recorder.log")
        try:
            log = open(self.log_path, "wb")
            log.write((" ".join(args) + "\n\n").encode())
            log.flush()
            self._proc = subprocess.Popen(
                args, pass_fds=[fd], stdout=log, stderr=log)
        except OSError as e:
            self._fail(f"could not start gstreamer: {e}")
            return
        # Watch for pipeline death for the whole recording (mux errors
        # can kill it minutes in), not just at startup.
        self._start_watchdog()
        self._busy = False
        self.recording = True
        self._started_at = time.monotonic()
        self.started.emit()

    def _log_tail(self) -> str:
        try:
            with open(self.log_path, errors="replace") as f:
                lines = [ln for ln in f.read().strip().splitlines()
                         if "ERROR" in ln or "WARN" in ln] or ["unknown"]
            return lines[-1]
        except OSError:
            return "unknown"

    def _start_watchdog(self) -> None:
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._check_alive)
        self._watchdog.start()

    def elapsed_str(self) -> str:
        if not self.recording or self._started_at is None:
            return ""
        s = int(time.monotonic() - self._started_at)
        return f"{s // 60}:{s % 60:02d}"

    def _check_alive(self) -> None:
        if self._stopping:
            return  # _poll_exit owns the exit path now
        if self._proc is not None and self._proc.poll() is not None:
            self.recording = False
            tmp, out = self._tmp, self._out
            self._cleanup()
            partial = self._salvage_partial(tmp, out)
            self.failed.emit(
                f"recorder died: {self._log_tail()[:160]} "
                f"(full log: {self.log_path}){partial}")
            return
        self.tick.emit(self.elapsed_str())

    @staticmethod
    def _salvage_partial(tmp, out) -> str:
        """KEEP whatever was written — a dead or SIGKILLed pipeline can
        leave minutes of salvageable footage; deleting it was part of
        the "Stop did nothing / recording vanished" bug."""
        if not tmp or not os.path.exists(tmp):
            return ""
        if out and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            return f"; partial recording kept: {os.path.basename(out)}"
        os.unlink(tmp)  # zero bytes: nothing to salvage
        return ""

    def _poll_exit(self, elapsed_ms: int = 0, nudged: bool = False) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            if elapsed_ms >= self.KILL_MS:
                self._proc.kill()
            elif elapsed_ms >= self.GRACE_MS and not nudged:
                # second interrupt: gst-launch gives up waiting for EOS
                self._proc.send_signal(signal.SIGINT)
                nudged = True
            QTimer.singleShot(
                200, lambda: self._poll_exit(elapsed_ms + 200, nudged))
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
            return
        partial = self._salvage_partial(tmp, out)
        self.failed.emit(
            f"recording did not finalize: {self._log_tail()[:160]} "
            f"(log: {getattr(self, 'log_path', '?')}){partial}")

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
        if getattr(self, "_watchdog", None) is not None:
            self._watchdog.stop()
            self._watchdog = None
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
        self._proc = None
        self._tmp = self._out = None
        self._close_session()


# -- platform factory (WS-E seam) ---------------------------------------------

def create_screen_recorder(settings, parent=None):
    """sys.platform factory mirroring create_capture_manager.

    Linux behavior is byte-identical: same class, same constructor.
    """
    if sys.platform == "win32":
        from .winrecord import WinScreenRecorder
        return WinScreenRecorder(settings, parent)
    return ScreenRecorder(settings, parent)
