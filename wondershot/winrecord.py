# wondershot/winrecord.py
"""Windows screen recorder: ffmpeg ddagrab (Desktop Duplication, hw path)
with gdigrab fallback, dshow microphone, QProcess lifecycle.

Mirrors record.py's ScreenRecorder contract exactly: signals
started/stopping/finished/failed/tick, .rendering tmp + salvage, a
1-second watchdog, and a stop-escalation ladder. The graceful stop is
ffmpeg's own: 'q' on stdin finalizes the mp4 (the SIGINT-as-EOS analog);
escalation is QProcess.terminate() then kill(), and a killed pipeline's
partial file is KEPT (record.py's salvage mandate).

No GStreamer on Windows. Import-safe everywhere; nothing Windows-only
happens at import time.
"""

from __future__ import annotations

import os
import re
import shutil
import time

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .ffmpegutil import FfmpegMissing, ffmpeg_path, run_ffmpeg
from .record import log_dir, sweep_stale_tmp


# -- ffmpeg argument builders (pure) -----------------------------------------

def _encode_args(audio_device: str) -> list[str]:
    args = ["-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p"]
    if audio_device:
        args += ["-c:a", "aac", "-b:a", "160k"]
    return args


def _audio_input(audio_device: str) -> list[str]:
    if not audio_device:
        return []
    return ["-f", "dshow", "-i", f"audio={audio_device}"]


def ddagrab_args(tmp: str, fps: int = 30, audio_device: str = "") -> list[str]:
    """Desktop Duplication grab: hw frames, hwdownload for libx264."""
    return (["-y", "-hide_banner",
             "-f", "lavfi",
             "-i", f"ddagrab=framerate={fps},hwdownload,format=bgra"]
            + _audio_input(audio_device)
            + _encode_args(audio_device)
            + [tmp])


def gdigrab_args(tmp: str, fps: int = 30, audio_device: str = "") -> list[str]:
    """GDI fallback when the ffmpeg build lacks the ddagrab filter."""
    return (["-y", "-hide_banner",
             "-f", "gdigrab", "-framerate", str(fps),
             "-i", "desktop"]
            + _audio_input(audio_device)
            + _encode_args(audio_device)
            + [tmp])


# -- capability probe -----------------------------------------------------------

_ddagrab_cache: bool | None = None


def reset_probe_cache() -> None:
    """Test hook."""
    global _ddagrab_cache
    _ddagrab_cache = None


def have_ddagrab() -> bool:
    """Does this ffmpeg build ship the ddagrab lavfi source?"""
    global _ddagrab_cache
    if _ddagrab_cache is None:
        try:
            cp = run_ffmpeg(["-hide_banner", "-filters"], timeout=15)
            _ddagrab_cache = "ddagrab" in (cp.stdout or "")
        except (FfmpegMissing, OSError):
            _ddagrab_cache = False
    return _ddagrab_cache


# -- dshow microphone discovery ---------------------------------------------------

def parse_dshow_audio_devices(text: str) -> list[str]:
    """Device names from `ffmpeg -list_devices true -f dshow -i dummy`.

    Lines look like:  [dshow @ ...] "Microphone (Realtek)" (audio)
    """
    devices = []
    for line in text.splitlines():
        if "(audio)" not in line:
            continue
        m = re.search(r'"([^"]+)"', line)
        if m:
            devices.append(m.group(1))
    return devices


def list_dshow_audio_devices() -> list[str]:
    try:
        cp = run_ffmpeg(["-hide_banner", "-list_devices", "true",
                         "-f", "dshow", "-i", "dummy"], timeout=15)
    except (FfmpegMissing, OSError):
        return []
    # the device list goes to stderr and the command "fails" by design
    return parse_dshow_audio_devices(cp.stderr or "")


def pick_audio_device(devices: list[str], preferred: str) -> str:
    """settings.mic_device match, else the first device, else ''."""
    if preferred and preferred in devices:
        return preferred
    return devices[0] if devices else ""


class WinScreenRecorder(QObject):
    """ffmpeg-based Windows recorder with ScreenRecorder's contract."""

    started = Signal()
    stopping = Signal()  # a stop transition began (whichever control asked)
    finished = Signal(str)  # final file path
    failed = Signal(str)
    tick = Signal(str)  # elapsed time ("1:05"), once a second

    # Escalation ladder, mirroring record.py: 'q' (graceful mp4
    # finalize) -> terminate() -> kill(). A killed pipeline's partial
    # file is salvaged, never deleted.
    GRACE_MS = 5000
    KILL_MS = 10000
    FPS = 30
    # A candidate that dies within this window never produced footage —
    # treat it as "couldn't initialize" (e.g. ddagrab with no D3D11 on a
    # VM/RDP) and transparently try the next builder. A later death is a
    # real failure: we salvage and report instead of restarting.
    FALLBACK_WINDOW_S = 3.0

    def __init__(self, settings, parent=None, program=None,
                 args_builder=None, fallback_builder=None):
        super().__init__(parent)
        self.settings = settings
        self.recording = False
        self._busy = False
        self._proc: QProcess | None = None
        self._tmp = self._out = None
        self._stopping = False
        self._watchdog: QTimer | None = None
        self._started_at: float | None = None
        self.log_path = ""
        self._program = program            # test seam; None = ffmpeg_path()
        self._args_builder = args_builder  # test seam; None = probe
        self._fallback_builder = fallback_builder  # test seam
        self._candidates: list = []        # ordered builders to try
        self._cand_idx = 0
        self._audio = ""

    # -- public ------------------------------------------------------------

    def available(self) -> bool:
        from .ffmpegutil import have_ffmpeg
        return have_ffmpeg()

    def start(self) -> None:
        if self.recording or self._busy:
            return
        self._busy = True
        try:
            program = self._program or ffmpeg_path()
        except FfmpegMissing as e:
            self._busy = False
            self.failed.emit(str(e))
            return
        from .capture import timestamp_name, unique_path
        out = unique_path(self.settings.library_dir,
                          timestamp_name("Recording").replace(".png", ".mp4"))
        tmp_dir = os.path.join(self.settings.library_dir, ".rendering")
        os.makedirs(tmp_dir, exist_ok=True)
        sweep_stale_tmp(tmp_dir)
        tmp = os.path.join(tmp_dir, os.path.basename(out))
        self._tmp, self._out = tmp, out

        self._audio = ""
        if getattr(self.settings, "mic_enabled", False):
            self._audio = pick_audio_device(
                list_dshow_audio_devices(),
                getattr(self.settings, "mic_device", ""))

        # Ordered builders to attempt. Probe path prefers ddagrab (hw
        # Desktop Duplication) with gdigrab as the runtime fallback; the
        # filter-presence probe can't tell whether ddagrab will actually
        # open a D3D11 device, so the real fallback is death-triggered.
        if self._args_builder is not None:
            self._candidates = [self._args_builder]
            if self._fallback_builder is not None:
                self._candidates.append(self._fallback_builder)
        else:
            self._candidates = ([ddagrab_args, gdigrab_args]
                                if have_ddagrab() else [gdigrab_args])
        self._cand_idx = 0
        self._program_resolved = program
        if not self._launch_current():
            return
        self._busy = False
        self.recording = True
        self._started_at = time.monotonic()
        self.started.emit()

    def _launch_current(self) -> bool:
        """Start ffmpeg with the current candidate. Returns False (and
        emits failed) only if even spawning the process fails."""
        builder = self._candidates[self._cand_idx]
        args = builder(self._tmp, fps=self.FPS, audio_device=self._audio)
        program = self._program_resolved

        logs = log_dir()
        os.makedirs(logs, exist_ok=True)
        self.log_path = os.path.join(logs, "recorder.log")
        try:
            mode = "a" if self._cand_idx else "w"
            with open(self.log_path, mode) as f:
                f.write(program + " " + " ".join(args) + "\n\n")
        except OSError:
            pass
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setStandardOutputFile(self.log_path, QProcess.Append)
        proc.start(program, args)
        if not proc.waitForStarted(5000):
            self._busy = False
            self._tmp = self._out = None
            self.failed.emit(f"could not start ffmpeg: {program}")
            return False
        self._proc = proc
        if self._watchdog is None:
            self._start_watchdog()
        return True

    def stop(self) -> None:
        if self._stopping:
            return  # double-stop (tray + toolbar) must not double-finalize
        if self._proc is None:
            return
        self._stopping = True
        self.stopping.emit()
        if self._proc.state() != QProcess.NotRunning:
            # ffmpeg's interactive quit: finalizes the mp4 moov, exit 0 —
            # the SIGINT-as-EOS analog (no SIGINT across consoles on
            # Windows).
            self._proc.write(b"q")
        # Even if ffmpeg already died, finalize so finished/failed always
        # fires — the UI must never stay "Stopping".
        self._poll_exit(elapsed_ms=0)

    # -- internals ---------------------------------------------------------

    def elapsed_str(self) -> str:
        if not self.recording or self._started_at is None:
            return ""
        s = int(time.monotonic() - self._started_at)
        return f"{s // 60}:{s % 60:02d}"

    def _start_watchdog(self) -> None:
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._check_alive)
        self._watchdog.start()

    def _check_alive(self) -> None:
        if self._stopping:
            return  # _poll_exit owns the exit path now
        if (self._proc is not None
                and self._proc.state() == QProcess.NotRunning):
            # A candidate that died almost immediately never produced
            # footage — try the next builder (ddagrab -> gdigrab) rather
            # than failing. A later death is a genuine pipeline failure.
            early = (self._started_at is not None
                     and time.monotonic() - self._started_at
                     < self.FALLBACK_WINDOW_S)
            if early and self._cand_idx + 1 < len(self._candidates):
                self._proc.deleteLater()
                self._proc = None
                self._cand_idx += 1
                if self._launch_current():
                    self._started_at = time.monotonic()
                return
            self.recording = False
            tmp, out = self._tmp, self._out
            self._cleanup()
            partial = self._salvage_partial(tmp, out)
            self.failed.emit(
                f"recorder died: {self._log_tail()[:160]} "
                f"(full log: {self.log_path}){partial}")
            return
        self.tick.emit(self.elapsed_str())

    def _log_tail(self) -> str:
        try:
            with open(self.log_path, errors="replace") as f:
                lines = [ln for ln in f.read().strip().splitlines()
                         if "rror" in ln or "Invalid" in ln] or ["unknown"]
            return lines[-1]
        except OSError:
            return "unknown"

    @staticmethod
    def _salvage_partial(tmp, out) -> str:
        """KEEP whatever was written (record.py's salvage mandate)."""
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
        if self._proc.state() != QProcess.NotRunning:
            if elapsed_ms >= self.KILL_MS:
                self._proc.kill()
            elif elapsed_ms >= self.GRACE_MS and not nudged:
                self._proc.terminate()  # WM_CLOSE; some builds ignore it
                nudged = True
            QTimer.singleShot(
                200, lambda: self._poll_exit(elapsed_ms + 200, nudged))
            return
        self.recording = False
        ok = (self._proc.exitStatus() == QProcess.NormalExit
              and self._proc.exitCode() == 0 and self._tmp
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
            f"(log: {self.log_path}){partial}")

    def _cleanup(self) -> None:
        self._stopping = False
        if self._watchdog is not None:
            self._watchdog.stop()
            self._watchdog = None
        if self._proc is not None:
            self._proc.deleteLater()
        self._proc = None
        self._tmp = self._out = None
