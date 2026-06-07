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
