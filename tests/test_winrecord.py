# tests/test_winrecord.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_module_imports_cleanly_on_linux():
    import wondershot.winrecord  # noqa: F401


# -- args builders -------------------------------------------------------------

def test_ddagrab_args_use_lavfi_with_hwdownload(tmp_path):
    from wondershot.winrecord import ddagrab_args
    tmp = str(tmp_path / "r.mp4")
    args = ddagrab_args(tmp, fps=30, audio_device="")
    assert args[:2] == ["-y", "-hide_banner"]
    i = args.index("-i")
    assert args[i - 2:i] == ["-f", "lavfi"]
    assert args[i + 1] == "ddagrab=framerate=30,hwdownload,format=bgra"
    assert "libx264" in args and "yuv420p" in args
    assert args[-1] == tmp
    assert "dshow" not in args and "-c:a" not in args


def test_ddagrab_args_with_audio_device(tmp_path):
    from wondershot.winrecord import ddagrab_args
    args = ddagrab_args(str(tmp_path / "r.mp4"), fps=30,
                        audio_device="Microphone (Realtek Audio)")
    i = args.index("dshow")
    assert args[i - 1] == "-f"
    assert args[i + 2] == "audio=Microphone (Realtek Audio)"
    assert "aac" in args


def test_gdigrab_args_fallback(tmp_path):
    from wondershot.winrecord import gdigrab_args
    tmp = str(tmp_path / "r.mp4")
    args = gdigrab_args(tmp, fps=30, audio_device="")
    i = args.index("gdigrab")
    assert args[i - 1] == "-f"
    assert "desktop" in args
    assert "libx264" in args and args[-1] == tmp


# -- dshow device discovery -----------------------------------------------------

DSHOW_OUTPUT = """\
[dshow @ 0000020] "Integrated Camera" (video)
[dshow @ 0000020]   Alternative name "@device_pnp_...."
[dshow @ 0000020] "Microphone (Realtek(R) Audio)" (audio)
[dshow @ 0000020]   Alternative name "@device_cm_...."
[dshow @ 0000020] "Stereo Mix (Realtek(R) Audio)" (audio)
dummy: Immediate exit requested
"""


def test_parse_dshow_audio_devices():
    from wondershot.winrecord import parse_dshow_audio_devices
    assert parse_dshow_audio_devices(DSHOW_OUTPUT) == [
        "Microphone (Realtek(R) Audio)",
        "Stereo Mix (Realtek(R) Audio)",
    ]


def test_parse_dshow_audio_devices_empty():
    from wondershot.winrecord import parse_dshow_audio_devices
    assert parse_dshow_audio_devices("no devices here") == []


def test_pick_audio_device_prefers_settings_match():
    from wondershot.winrecord import pick_audio_device
    devs = ["Microphone (Realtek(R) Audio)", "Stereo Mix (Realtek(R) Audio)"]
    assert pick_audio_device(devs, "Stereo Mix (Realtek(R) Audio)") == \
        "Stereo Mix (Realtek(R) Audio)"
    assert pick_audio_device(devs, "Gone Device") == devs[0]
    assert pick_audio_device(devs, "") == devs[0]
    assert pick_audio_device([], "anything") == ""


# -- ddagrab probe ----------------------------------------------------------------

def test_have_ddagrab_parses_filters_output(monkeypatch):
    import subprocess
    from wondershot import winrecord
    winrecord.reset_probe_cache()

    def fake_run(args, timeout=60):
        return subprocess.CompletedProcess(
            args, 0, stdout=" ... ddagrab          Grab desktop ...", stderr="")

    monkeypatch.setattr(winrecord, "run_ffmpeg", fake_run)
    assert winrecord.have_ddagrab() is True


def test_have_ddagrab_false_without_filter(monkeypatch):
    import subprocess
    from wondershot import winrecord
    winrecord.reset_probe_cache()
    monkeypatch.setattr(
        winrecord, "run_ffmpeg",
        lambda args, timeout=60: subprocess.CompletedProcess(
            args, 0, stdout="gdigrab only here", stderr=""))
    assert winrecord.have_ddagrab() is False


def test_have_ddagrab_false_when_ffmpeg_missing(monkeypatch):
    from wondershot import winrecord
    from wondershot.ffmpegutil import FfmpegMissing
    winrecord.reset_probe_cache()

    def boom(args, timeout=60):
        raise FfmpegMissing()

    monkeypatch.setattr(winrecord, "run_ffmpeg", boom)
    assert winrecord.have_ddagrab() is False
