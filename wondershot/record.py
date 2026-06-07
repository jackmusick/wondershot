"""Native screen recorder with microphone audio.

Flow: xdg-desktop-portal ScreenCast (CreateSession → SelectSources →
Start → OpenPipeWireRemote) hands us a PipeWire fd + node; an in-process
`Gst.parse_launch` pipeline encodes it (x264 + AAC → mp4), mixing in the
microphone via pulsesrc. A bus EOS event triggers the mp4 to finalize
cleanly; bus ERROR is the death signal. A portal restore token is
persisted, so the screen-share picker only appears the first time.

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


def build_pipeline_description(fd, node, tmp, *, mic_enabled, mic_device="",
                               noise_suppression=True, have_webrtcdsp=False,
                               crop=None, halo=False):
    """Build the Gst.parse_launch string. PURE — no Gst, no portal, no I/O.

    crop: dict(left,right,top,bottom) or None. halo: bool (cursor overlay).
    The videorate + fixed-framerate caps are the no-PTS landmine fix — VERBATIM.
    """
    crop_seg = ""
    if crop:
        crop_seg = ("videocrop top={top} left={left} "
                    "right={right} bottom={bottom} ! ").format(**crop)
    # cairooverlay needs an alpha-capable format; wrap it in videoconvert.
    halo_seg = ("videoconvert ! cairooverlay name=halo ! " if halo else "")
    video = (
        f"pipewiresrc fd={fd} path={node} do-timestamp=true ! "
        "queue ! videoconvert ! "
        f"{crop_seg}"
        # pipewiresrc emits PTS-less buffers (mp4mux-fatal); videorate drops
        # them and turns the damage-driven stream into clean CFR. VERBATIM.
        "videorate ! video/x-raw,format=I420,framerate=30/1 ! "
        # 'pause' identity carries the PTS-offset probe (C1) and MUST sit on
        # RAW frames BEFORE x264enc: dropping/retiming encoded H264 NALs would
        # corrupt inter-frame dependencies. Harmless transparent tap until C1
        # wires the probe.
        "identity name=pause ! "
        f"{halo_seg}"
        "x264enc speed-preset=veryfast tune=zerolatency "
        "bitrate=8000 key-int-max=120 ! "
        "h264parse ! queue ! mux. "
    )
    audio = ""
    if mic_enabled:
        device = mic_pulse_device(mic_device)
        dev = f"device={device} " if device else ""
        dsp = ""
        if noise_suppression and have_webrtcdsp:
            dsp = ("audio/x-raw,rate=48000,channels=1 ! webrtcdsp "
                   "echo-cancel=false noise-suppression=true "
                   "noise-suppression-level=very-high gain-control=false "
                   "high-pass-filter=true ! ")
        audio = (
            f"pulsesrc {dev}do-timestamp=true ! "
            "queue ! audioconvert ! audioresample ! "
            f"{dsp}audioconvert ! avenc_aac bitrate=160000 ! "
            "aacparse ! queue ! mux. "
        )
    return f"{video}{audio}mp4mux name=mux ! filesink location={tmp}"


def elapsed_seconds(started_at, now, paused_total=0.0, paused_at=None):
    """Wall seconds recorded, excluding paused spans. PURE."""
    if started_at is None:
        return 0.0
    live = now - started_at - paused_total
    if paused_at is not None:
        live -= (now - paused_at)
    return max(0.0, live)


def format_elapsed(seconds):
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def pts_offset_ns(paused_total_s):
    """Nanoseconds to subtract from buffer PTS/DTS so the resumed segment
    is gap-free for mp4mux. PURE."""
    return int(round(paused_total_s * 1_000_000_000))


def crop_props(rect, stream_w, stream_h):
    """Map a chosen rect (x,y,w,h) in stream pixels to videocrop
    top/left/right/bottom borders, clamped. PURE."""
    x, y, w, h = rect
    left = max(0, x)
    top = max(0, y)
    right = max(0, stream_w - (x + w))
    bottom = max(0, stream_h - (y + h))
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def halo_geometry(cx, cy, frame_w, frame_h, radius=24):
    """Clamp the halo centre into frame; return (cx, cy, radius). PURE."""
    cx = max(0, min(int(cx), frame_w))
    cy = max(0, min(int(cy), frame_h))
    return (cx, cy, radius)


def _gst():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    if not Gst.is_initialized():
        Gst.init(None)
    return Gst


class _GstPipeline:
    """Owns a real Gst pipeline + bus; exposes the fakeable lifecycle
    surface (poll_status/error_text/send_eos/force_stop/pause/resume)."""

    def __init__(self, desc, log_path):
        Gst = _gst()
        self._Gst = Gst
        self._log_path = log_path
        self._error = ""
        self._forced = False        # force_stop() called: poll_status terminal
        self._paused_offset_ns = 0  # accumulated paused duration (C1)
        self._dropping = False
        self._pause_started_ns = 0
        self._p = Gst.parse_launch(desc)          # may raise GLib.Error
        self._bus = self._p.get_bus()
        self._p.set_state(Gst.State.PLAYING)

    def poll_status(self):
        Gst = self._Gst
        flt = Gst.MessageType.ERROR | Gst.MessageType.EOS
        msg = self._bus.pop_filtered(flt)
        while msg is not None:
            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                self._error = err.message
                self._append_log(f"ERROR: {err.message} | {dbg}")
                return "error"
            if msg.type == Gst.MessageType.EOS:
                return "eos"          # EOS on the bus == filesink finalized
            msg = self._bus.pop_filtered(flt)
        # set NULL posts neither EOS nor ERROR to the bus, so a wedged
        # pipeline would otherwise report "running" forever and hang the
        # finalize loop on "Stopping…". force_stop() is the terminal,
        # non-clean give-up — surface it so _poll_exit salvages + exits.
        if self._forced:
            return "error"
        return "running"

    def error_text(self):
        return self._error or "unknown"

    def send_eos(self):
        self._p.send_event(self._Gst.Event.new_eos())

    def force_stop(self):
        self._forced = True
        if not self._error:
            self._error = "force-stopped (EOS wait abandoned)"
        try:
            self._p.set_state(self._Gst.State.NULL)
        except Exception:
            pass

    # -- pause/resume (C1) -------------------------------------------------
    def pause(self):
        """Gate the 'pause' identity: drop buffers and remember when."""
        Gst = self._Gst
        elem = self._p.get_by_name("pause")
        if elem is None:
            return
        if not self._dropping:
            self._pause_started_ns = self._p.get_clock().get_time() \
                if self._p.get_clock() else 0
            self._dropping = True
            if not getattr(self, "_probe_id", None):
                pad = elem.get_static_pad("src")
                self._probe_id = pad.add_probe(
                    Gst.PadProbeType.BUFFER, self._pause_probe)

    def resume(self):
        if self._dropping:
            now = self._p.get_clock().get_time() \
                if self._p.get_clock() else 0
            self._paused_offset_ns += max(0, now - self._pause_started_ns)
            self._dropping = False

    def _pause_probe(self, pad, info):
        Gst = self._Gst
        if self._dropping:
            return Gst.PadProbeReturn.DROP
        buf = info.get_buffer()
        if buf is not None and self._paused_offset_ns:
            buf = buf.make_writable()
            if buf.pts != Gst.CLOCK_TIME_NONE:
                buf.pts = max(0, buf.pts - self._paused_offset_ns)
            if buf.dts != Gst.CLOCK_TIME_NONE:
                buf.dts = max(0, buf.dts - self._paused_offset_ns)
            info.data = buf
        return Gst.PadProbeReturn.OK

    def _append_log(self, line):
        try:
            with open(self._log_path, "a", errors="replace") as f:
                f.write(line + "\n")
        except OSError:
            pass


class ScreenRecorder(QObject):
    """Portal + PipeWire + GStreamer screen recorder."""

    started = Signal()
    stopping = Signal()  # a stop transition began (whichever control asked)
    finished = Signal(str)  # final file path
    failed = Signal(str)
    tick = Signal(str)  # elapsed time ("1:05"), once a second while recording
    paused_changed = Signal(bool)  # C1: pause/resume state
    # Capability flag: app.py gates the Pause UI on this (Windows' ffmpeg
    # recorder can't pause, so its controls must hide, not no-op).
    supports_pause = True

    # Finalize escalation ladder. An in-process pipeline can wedge waiting
    # for EOS indefinitely (observed 2026-06-06: still draining-failing 3+
    # min — journal pipewire-pulse overruns, orphaned .rendering tmp).
    # force_stop() (set NULL) abandons the wedged EOS wait and is the
    # in-process analog of the second-SIGINT / SIGKILL last resort.
    GRACE_MS = 5000
    KILL_MS = 10000

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.recording = False
        self._busy = False
        self._pipeline = None
        self._session: str | None = None
        self._tmp = self._out = None
        self._fd = -1
        self._conn = None
        self._subs: list[int] = []
        self._stopping = False
        self._watchdog: QTimer | None = None
        self._started_at: float | None = None
        self.log_path = ""
        # pause/resume (C1) + region crop (D1) + cursor halo (B1) state
        self.paused = False
        self._paused_at: float | None = None
        self._paused_total = 0.0
        self._crop = None
        self._halo = False

    # -- public ------------------------------------------------------------

    def available(self) -> bool:
        if not _HAVE_GIO:
            return False
        try:
            _gst()
            return True
        except (ImportError, ValueError):
            return False

    def start(self) -> None:
        if self.recording or self._busy:
            return
        if not self.available():
            self.failed.emit(
                "recording needs python3-gobject and GStreamer (Gst) bindings")
            return
        self._halo = bool(getattr(self.settings, "record_cursor_halo", False))
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
        if self._pipeline is None:
            return
        self._stopping = True
        self.stopping.emit()
        self._pipeline.send_eos()  # in-process analog of -e + SIGINT
        # Even if the pipeline already died (mux error etc.), finalize so
        # finished/failed always fires — the UI must never stay "Stopping".
        self._poll_exit(elapsed_ms=0)

    def pause(self) -> None:
        if not (self.recording and not self.paused and not self._stopping):
            return
        if self._pipeline is None:
            return
        self._pipeline.pause()
        self.paused = True
        self._paused_at = time.monotonic()
        self.paused_changed.emit(True)

    def resume(self) -> None:
        if not self.paused:
            return
        if self._paused_at is not None:
            self._paused_total += time.monotonic() - self._paused_at
        self._paused_at = None
        self.paused = False
        if self._pipeline is not None:
            self._pipeline.resume()
        self.paused_changed.emit(False)

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
            # 4 = METADATA (cursor delivered as spa_meta_cursor for the
            # halo to composite), 2 = EMBEDDED (baked into frames).
            # METADATA is PARKED: spa_meta_cursor isn't reachable through
            # PyGObject, so _draw_halo is a no-op. Requesting mode 4 while
            # the draw does nothing would yield a recording with NO cursor
            # at all — strictly worse. Stay on EMBEDDED until the source
            # works; flip to `4 if self._halo else 2` then.
            "cursor_mode": GLib.Variant("u", 2),
            # 0 = do not persist. We deliberately DON'T replay a saved
            # restore_token: with persist_mode=2 + token the portal skips
            # its picker after the first-ever recording, so you could never
            # change the screen/window again (Jack's bug, 2026-06-07). A
            # screenshot tool must let you pick the source every time —
            # same reasoning as scroll capture's fresh-pick.
            "persist_mode": GLib.Variant("u", 0),
        }
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

    def _make_pipeline(self, desc):
        """The ONLY Gst entry point. Overridable by tests."""
        return _GstPipeline(desc, self.log_path)

    def _launch_gst(self, fd: int, node: int) -> None:
        from .capture import timestamp_name, unique_path
        out = unique_path(self.settings.library_dir,
                          timestamp_name("Recording").replace(".png", ".mp4"))
        tmp_dir = os.path.join(self.settings.library_dir, ".rendering")
        os.makedirs(tmp_dir, exist_ok=True)
        sweep_stale_tmp(tmp_dir)
        tmp = os.path.join(tmp_dir, os.path.basename(out))
        self._tmp, self._out = tmp, out
        desc = build_pipeline_description(
            fd, node, tmp,
            mic_enabled=self.settings.mic_enabled,
            mic_device=self.settings.mic_device,
            noise_suppression=self.settings.noise_suppression,
            have_webrtcdsp=_have_gst_element("webrtcdsp"),
            crop=self._crop, halo=self._halo)

        logs = log_dir()
        os.makedirs(logs, exist_ok=True)
        self.log_path = os.path.join(logs, "recorder.log")
        try:
            with open(self.log_path, "w", errors="replace") as log:
                log.write(desc + "\n\n")
        except OSError:
            pass
        try:
            self._pipeline = self._make_pipeline(desc)
        except Exception as e:
            self._fail(f"could not start gstreamer: {e}")
            return
        self._connect_halo()
        # Watch for pipeline death for the whole recording (mux errors
        # can kill it minutes in), not just at startup.
        self._start_watchdog()
        self._busy = False
        self.recording = True
        self._started_at = time.monotonic()
        self.started.emit()

    def _connect_halo(self) -> None:
        """Wire the cairooverlay draw callback when halo compositing is on.

        Reading the cursor position from PipeWire's spa_meta_cursor is the
        known risk (B2) — see ROADMAP "Cursor halo (in-process)". The
        overlay element path is wired here; cursor-source correctness is a
        desktop checklist item / parked pending gi meta access."""
        if not self._halo or self._pipeline is None:
            return
        p = getattr(self._pipeline, "_p", None)
        if p is None:
            return
        try:
            overlay = p.get_by_name("halo")
            if overlay is not None:
                overlay.connect("draw", self._draw_halo)
        except Exception:
            pass

    def _draw_halo(self, overlay, cr, timestamp, duration) -> None:
        """Paint a translucent halo at the latest cursor position. The
        cursor coords (self._cursor_xy) are updated by a buffer pad probe;
        until spa_meta_cursor is reachable through gi this stays a no-op
        (parked) — see ROADMAP."""
        xy = getattr(self, "_cursor_xy", None)
        if xy is None:
            return
        cx, cy, radius = halo_geometry(xy[0], xy[1],
                                       getattr(self, "_frame_w", 0),
                                       getattr(self, "_frame_h", 0))
        try:
            cr.set_source_rgba(1, 1, 0, 0.35)
            cr.arc(cx, cy, radius, 0, 2 * 3.14159265)
            cr.fill()
        except Exception:
            pass

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
        if not self.recording:
            return ""
        return format_elapsed(elapsed_seconds(
            self._started_at, time.monotonic(),
            self._paused_total, self._paused_at))

    def _check_alive(self) -> None:
        if self._stopping:
            return  # _poll_exit owns the exit path now
        if (self._pipeline is not None
                and self._pipeline.poll_status() == "error"):
            self.recording = False
            tmp, out = self._tmp, self._out
            tail = self._pipeline.error_text()
            self._cleanup()
            partial = self._salvage_partial(tmp, out)
            self.failed.emit(
                f"recorder died: {tail[:160]} "
                f"(full log: {self.log_path}){partial}")
            return
        if not self.paused:
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

    def _poll_exit(self, elapsed_ms: int = 0, escalated: bool = False) -> None:
        if self._pipeline is None:
            return
        status = self._pipeline.poll_status()
        if status == "running":
            if elapsed_ms >= self.KILL_MS:
                self._pipeline.force_stop()           # hard give-up
            elif elapsed_ms >= self.GRACE_MS and not escalated:
                self._pipeline.force_stop()           # abandon wedged EOS
                escalated = True
            QTimer.singleShot(
                200, lambda: self._poll_exit(elapsed_ms + 200, escalated))
            return
        self.recording = False
        ok = (status == "eos" and self._tmp
              and os.path.exists(self._tmp)
              and os.path.getsize(self._tmp) > 0)
        tmp, out = self._tmp, self._out
        tail = self._pipeline.error_text()
        self._cleanup()
        if ok:
            shutil.move(tmp, out)
            self.finished.emit(out)
            return
        partial = self._salvage_partial(tmp, out)
        self.failed.emit(
            f"recording did not finalize: {tail[:160]} "
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
        if self._pipeline is not None:
            self._pipeline.force_stop()
            self._pipeline = None
        self._tmp = self._out = None
        self.paused = False
        self._paused_at = None
        self._paused_total = 0.0
        self._crop = None  # region crop is per-session (D2)
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
