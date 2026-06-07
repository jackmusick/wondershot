"""Single chokepoint for invoking ffmpeg.

Every ffmpeg call site routes through here. Today this is PATH discovery
via shutil.which; WS-E (Windows/macOS packaging) will swap in a bundled
binary at this one seam and every caller gets it for free.
"""

from __future__ import annotations

import shutil
import subprocess


class FfmpegMissing(RuntimeError):
    """ffmpeg is not installed / not on PATH."""

    def __init__(self):
        super().__init__(
            "ffmpeg was not found on PATH. Install it (e.g. "
            "`sudo dnf install ffmpeg`) and restart Wondershot.")


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
        found = shutil.which("ffmpeg")
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
