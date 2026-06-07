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


# -- WinScreenRecorder lifecycle (Python stub child, runs anywhere) ------------

import sys
import time


class FakeSettings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.mic_enabled = False
        self.mic_device = ""
        self.screencast_token = ""


GRACEFUL_STUB = """\
import sys
out = sys.argv[-1]
with open(out, "wb") as f:
    f.write(b"mp4-header")
    f.flush()
    while True:
        ch = sys.stdin.read(1)
        if ch in ("q", ""):
            f.write(b"-finalized")
            break
sys.exit(0)
"""

WEDGED_STUB = """\
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)  # ignore terminate()
out = sys.argv[-1]
with open(out, "wb") as f:
    f.write(b"partial-footage")
    f.flush()
    while True:
        time.sleep(1)  # never reads stdin, never exits
"""

DYING_STUB = """\
import sys
out = sys.argv[-1]
with open(out, "wb") as f:
    f.write(b"partial-footage")
sys.exit(3)  # immediate death, like a mid-recording encoder error
"""


def _recorder(tmp_path, stub_src):
    from wondershot.winrecord import WinScreenRecorder
    stub = tmp_path / "stub.py"
    stub.write_text(stub_src)
    rec = WinScreenRecorder(
        FakeSettings(str(tmp_path)),
        program=sys.executable,
        args_builder=lambda tmp, fps=30, audio_device="":
            ["-u", str(stub), tmp])
    return rec


def wait_until(qapp, cond, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_start_emits_started_and_creates_tmp(qapp, tmp_path):
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    events = []
    rec.started.connect(lambda: events.append("started"))
    rec.failed.connect(lambda m: events.append(("failed", m)))
    rec.start()
    assert wait_until(qapp, lambda: events, 5)
    assert events[0] == "started"
    assert rec.recording is True
    assert os.path.dirname(rec._tmp).endswith(".rendering")
    rec.stop()
    wait_until(qapp, lambda: not rec.recording, 5)


def test_q_on_stdin_finalizes_and_emits_finished(qapp, tmp_path):
    """The 'q' graceful path is the SIGINT-as-EOS analog: exit 0, the
    finalized file moves out of .rendering into the library."""
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(lambda m: done.append(("failed", m)))
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    rec.stop()
    assert wait_until(qapp, lambda: done, 10)
    path = done[0]
    assert isinstance(path, str) and path.endswith(".mp4")
    assert os.path.dirname(path) == str(tmp_path)  # out of .rendering
    with open(path, "rb") as f:
        assert f.read() == b"mp4-header-finalized"
    assert rec.recording is False and rec._proc is None


def test_stop_emits_stopping_exactly_once(qapp, tmp_path):
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    stops, done = [], []
    rec.stopping.connect(lambda: stops.append(1))
    rec.finished.connect(done.append)
    rec.failed.connect(done.append)
    rec.stop()
    rec.stop()  # tray after toolbar: silent no-op
    assert stops == [1]
    assert wait_until(qapp, lambda: done, 10)


def test_escalation_kills_wedged_pipeline_and_keeps_partial(qapp, tmp_path):
    """ffmpeg can wedge ignoring 'q' (and SIGTERM in the stub, mirroring
    record.py's wedged-EOS forensics): the ladder must end in kill() and
    the partial recording must be KEPT."""
    rec = _recorder(tmp_path, WEDGED_STUB)
    rec.GRACE_MS = 400
    rec.KILL_MS = 900
    results = []
    rec.failed.connect(results.append)
    rec.finished.connect(results.append)
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    out_expected = rec._out
    rec.stop()
    assert wait_until(qapp, lambda: results, 10), \
        "escalation must finalize a stop-ignoring pipeline"
    assert rec.recording is False and rec._proc is None
    assert os.path.exists(out_expected)
    with open(out_expected, "rb") as f:
        assert f.read() == b"partial-footage"
    assert "partial" in results[0]


def test_watchdog_detects_death_and_salvages(qapp, tmp_path):
    """Encoder dies minutes in: failed fires without a stop click and
    the partial footage moves to the library (record.py mandate)."""
    rec = _recorder(tmp_path, DYING_STUB)
    failures = []
    rec.failed.connect(failures.append)
    rec.start()
    started = wait_until(qapp, lambda: rec.recording, 5)
    assert started
    out_expected = rec._out
    assert wait_until(qapp, lambda: failures, 5), \
        "watchdog must emit failed when the pipeline dies"
    assert rec.recording is False
    assert os.path.exists(out_expected)
    assert "partial" in failures[0]


def test_tick_emits_elapsed_while_recording(qapp, tmp_path):
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    rec._started_at = time.monotonic() - 65
    assert rec.elapsed_str() == "1:05"
    ticks = []
    rec.tick.connect(ticks.append)
    assert wait_until(qapp, lambda: ticks, 3)
    assert ticks[0].startswith("1:0")
    rec.stop()
    wait_until(qapp, lambda: not rec.recording, 5)


def test_available_tracks_ffmpeg(monkeypatch, tmp_path):
    from wondershot import ffmpegutil, winrecord
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: None)
    rec = winrecord.WinScreenRecorder(FakeSettings(str(tmp_path)))
    assert rec.available() is False
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert rec.available() is True
    ffmpegutil.reset_cache()


def test_start_without_ffmpeg_emits_failed(qapp, monkeypatch, tmp_path):
    from wondershot import ffmpegutil, winrecord
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: None)
    rec = winrecord.WinScreenRecorder(FakeSettings(str(tmp_path)))
    fails = []
    rec.failed.connect(fails.append)
    rec.start()
    assert fails and "ffmpeg" in fails[0]
    ffmpegutil.reset_cache()


def test_early_death_falls_back_to_next_builder(qapp, tmp_path):
    """ddagrab with no D3D11 (VMs/RDP) dies ~instantly; the recorder must
    transparently relaunch the gdigrab candidate instead of emitting
    failed. Proven here with a dying first builder + graceful second."""
    from wondershot.winrecord import WinScreenRecorder
    dying = tmp_path / "dying.py"
    dying.write_text(DYING_STUB)
    graceful = tmp_path / "graceful.py"
    graceful.write_text(GRACEFUL_STUB)
    rec = WinScreenRecorder(
        FakeSettings(str(tmp_path)),
        program=sys.executable,
        args_builder=lambda tmp, fps=30, audio_device="": ["-u", str(dying), tmp],
        fallback_builder=lambda tmp, fps=30, audio_device="": ["-u", str(graceful), tmp])
    failures = []
    rec.failed.connect(failures.append)
    rec.start()
    # it should settle on the graceful (second) candidate and stay up
    assert wait_until(qapp, lambda: rec._cand_idx == 1 and rec.recording, 6), \
        "recorder must fall back to the second builder and keep recording"
    assert not failures
    out_expected = rec._out
    rec.stop()
    assert wait_until(qapp, lambda: not rec.recording, 6)
    finished = wait_until(qapp, lambda: os.path.exists(out_expected), 2)
    assert finished and not failures


def test_no_fallback_when_single_builder_dies(qapp, tmp_path):
    """A lone candidate that dies still fails (no phantom fallback)."""
    rec = _recorder(tmp_path, DYING_STUB)  # no fallback_builder
    failures = []
    rec.failed.connect(failures.append)
    rec.start()
    assert wait_until(qapp, lambda: failures, 6)
    assert rec._cand_idx == 0


def test_late_death_does_not_fall_back(qapp, tmp_path):
    """A builder that ran a while then died is a real failure, not a
    fallback trigger — we must not discard footage and restart."""
    from wondershot.winrecord import WinScreenRecorder
    dying = tmp_path / "dying.py"
    dying.write_text(DYING_STUB)
    graceful = tmp_path / "graceful.py"
    graceful.write_text(GRACEFUL_STUB)
    rec = WinScreenRecorder(
        FakeSettings(str(tmp_path)),
        program=sys.executable,
        args_builder=lambda tmp, fps=30, audio_device="": ["-u", str(dying), tmp],
        fallback_builder=lambda tmp, fps=30, audio_device="": ["-u", str(graceful), tmp])
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    rec._started_at = time.monotonic() - 30  # pretend it ran 30s before dying
    failures = []
    rec.failed.connect(failures.append)
    assert wait_until(qapp, lambda: failures, 6), "late death is a real failure"
    assert rec._cand_idx == 0  # never fell back
