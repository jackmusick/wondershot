"""Single chokepoint for invoking ffmpeg.

Every ffmpeg call site routes through here. Today this is PATH discovery
via shutil.which; WS-E (Windows/macOS packaging) will swap in a bundled
binary at this one seam and every caller gets it for free.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


class FfmpegMissing(RuntimeError):
    """ffmpeg is not installed / not on PATH."""

    def __init__(self):
        # User-facing: platform-appropriate hint, never our toolchain.
        # Bundled builds ship ffmpeg, so this should only fire on
        # from-source installs.
        hint = (" Install it (e.g. `sudo dnf install ffmpeg`) and restart"
                " Wondershot." if sys.platform.startswith("linux")
                else " Reinstalling Wondershot should restore it.")
        super().__init__("Wondershot couldn't find its video engine"
                         " (ffmpeg)." + hint)


def _bundled_ffmpeg() -> str | None:
    """ffmpeg shipped inside a frozen (PyInstaller) build, if any.

    One-dir layout puts payloads either next to the exe or under
    _internal (PyInstaller >= 6). Source checkouts return None and fall
    through to PATH discovery.
    """
    if not getattr(sys, "frozen", False):
        return None
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    base = os.path.dirname(sys.executable)
    for cand in (os.path.join(base, name),
                 os.path.join(base, "_internal", name)):
        if os.path.exists(cand):
            return cand
    return None


_path_cache: str | None = None


def reset_cache() -> None:
    """Test hook: forget the discovered path."""
    global _path_cache
    _path_cache = None


def ffmpeg_path() -> str:
    """Absolute path to the ffmpeg binary; raises FfmpegMissing if absent.

    Successful discovery is cached for the process lifetime; a miss is
    re-probed each call (the user may install ffmpeg mid-session).
    """
    global _path_cache
    if _path_cache is None:
        found = _bundled_ffmpeg() or shutil.which("ffmpeg")
        if not found:
            raise FfmpegMissing()
        _path_cache = found
    return _path_cache


def have_ffmpeg() -> bool:
    try:
        ffmpeg_path()
        return True
    except FfmpegMissing:
        return False


def run_ffmpeg(args: list[str],
               timeout: float = 60) -> subprocess.CompletedProcess:
    """Blocking ffmpeg run (capability probes, thumbnailers). Callers that
    must not block the UI use QProcess with ffmpeg_path() instead."""
    return subprocess.run([ffmpeg_path(), *args], capture_output=True,
                          text=True, timeout=timeout)
