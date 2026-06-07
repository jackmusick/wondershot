import os
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="recorder tests drive POSIX subprocesses (true/sleep, SIGINT-as-EOS);"
           " the recorder itself is Linux-only (portal/PipeWire/gst)",
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeSettings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.mic_enabled = False
        self.mic_device = ""
        self.noise_suppression = True
        self.screencast_token = ""


def make_recorder(tmp_path):
    from wondershot.record import ScreenRecorder
    return ScreenRecorder(FakeSettings(str(tmp_path)))


def wait_until(qapp, cond, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def dead_proc():
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc


def test_stop_with_dead_pipeline_emits_signal(qapp, tmp_path):
    """The gst process can die mid-recording (e.g. mux error). Stop must
    still finalize and emit, not leave the UI on 'Stopping' forever."""
    rec = make_recorder(tmp_path)
    rec._proc = dead_proc()
    rec.recording = True
    rec._tmp = str(tmp_path / ".rendering" / "r.mp4")
    rec._out = str(tmp_path / "r.mp4")
    results = []
    rec.failed.connect(lambda m: results.append(("failed", m)))
    rec.finished.connect(lambda p: results.append(("finished", p)))
    rec.stop()
    assert wait_until(qapp, lambda: results, 3), \
        "stop() on a dead pipeline must emit finished or failed"
    assert rec.recording is False
    assert rec._proc is None


def test_watchdog_detects_late_pipeline_death(qapp, tmp_path):
    """Pipeline death after the initial liveness check must surface as
    failed (resetting recording state) without the user pressing stop."""
    rec = make_recorder(tmp_path)
    rec._proc = dead_proc()
    rec.recording = True
    failures = []
    rec.failed.connect(failures.append)
    rec._start_watchdog()
    assert wait_until(qapp, lambda: failures, 3), \
        "watchdog must emit failed when the pipeline dies"
    assert rec.recording is False
    assert rec._proc is None


def test_video_branch_sanitizes_timestamps(tmp_path):
    """pipewiresrc intermittently emits buffers without PTS, which is
    fatal to mp4mux; videorate + fixed framerate caps absorb them."""
    rec = make_recorder(tmp_path)
    args = rec._gst_args(fd=5, node=7, tmp=str(tmp_path / "t.mp4"))
    assert "videorate" in args
    assert any("framerate=" in a for a in args)


def test_elapsed_and_tick_while_recording(qapp, tmp_path):
    """The watchdog doubles as the elapsed-time ticker for the UI."""
    rec = make_recorder(tmp_path)
    proc = subprocess.Popen(["sleep", "10"])
    try:
        rec._proc = proc
        rec.recording = True
        rec._started_at = time.monotonic() - 65
        assert rec.elapsed_str() == "1:05"
        ticks = []
        rec.tick.connect(ticks.append)
        rec._start_watchdog()
        assert wait_until(qapp, lambda: ticks, 3), \
            "watchdog must tick elapsed time while recording"
        assert ticks[0].startswith("1:0")
    finally:
        proc.kill()
        proc.wait()


def test_log_dir_uses_standard_cache_location():
    """recorder.log must live under the platform cache dir, not ~/.cache."""
    from PySide6.QtCore import QStandardPaths
    from wondershot.record import log_dir
    base = QStandardPaths.writableLocation(
        QStandardPaths.GenericCacheLocation)
    assert log_dir() == os.path.join(base, "wondershot")


def test_recorder_restore_token_hook_reads_settings(qapp, tmp_path):
    from wondershot.record import ScreenRecorder
    settings = FakeSettings(str(tmp_path))
    settings.screencast_token = "recorder-grant"
    rec = ScreenRecorder(settings)
    assert rec._restore_token() == "recorder-grant"


def test_recorder_save_token_hook_persists(qapp, tmp_path):
    from wondershot.record import ScreenRecorder
    settings = FakeSettings(str(tmp_path))
    rec = ScreenRecorder(settings)
    rec._save_restore_token("new-grant")
    assert settings.screencast_token == "new-grant"


def test_stop_emits_stopping_exactly_once(qapp, tmp_path):
    """Both UIs key their 'Stopping…' state off this signal; a second
    stop click (tray after toolbar) must not re-emit."""
    rec = make_recorder(tmp_path)
    proc = subprocess.Popen(["sleep", "30"])
    rec._proc = proc
    rec.recording = True
    rec._tmp = str(tmp_path / ".rendering" / "r.mp4")
    rec._out = str(tmp_path / "r.mp4")
    stops = []
    rec.stopping.connect(lambda: stops.append(1))
    done = []
    rec.failed.connect(lambda m: done.append(m))
    rec.finished.connect(lambda p: done.append(p))
    rec.stop()
    rec.stop()  # the second control's click: silent no-op, no re-emit
    assert stops == [1]
    assert wait_until(qapp, lambda: done, 5)
    proc.poll() is not None or (proc.kill(), proc.wait())


def test_stop_escalates_when_eos_wait_wedges(qapp, tmp_path):
    """2026-06-06 forensics: gst-launch wedged in 'Waiting for EOS' for
    3+ minutes (journal pulse overruns, orphaned .rendering tmp). The
    finalize loop must escalate: SIGINT -> second SIGINT -> SIGKILL."""
    rec = make_recorder(tmp_path)
    # a child that ignores SIGINT entirely == a wedged EOS wait
    proc = subprocess.Popen(["bash", "-c", 'trap "" INT; sleep 60'])
    rec._proc = proc
    rec.recording = True
    rec._tmp = str(tmp_path / ".rendering" / "r.mp4")
    rec._out = str(tmp_path / "r.mp4")
    rec.GRACE_MS = 400   # speed the ladder up for the test
    rec.KILL_MS = 900
    log = tmp_path / "recorder.log"
    log.write_text("gst output\nERROR: from element mux: wedged\n")
    rec.log_path = str(log)
    results = []
    rec.failed.connect(lambda m: results.append(m))
    rec.finished.connect(lambda p: results.append(p))
    rec.stop()
    assert wait_until(qapp, lambda: results, 8), \
        "escalation must finalize a SIGINT-ignoring pipeline"
    assert rec.recording is False
    assert rec._proc is None
    assert "ERROR" in results[0], \
        "the did-not-finalize message must surface the gst log tail"
    proc.poll() is not None or (proc.kill(), proc.wait())


def test_sigkill_keeps_partial_recording(qapp, tmp_path):
    """When the ladder ends in SIGKILL the partial recording must be
    KEPT, not deleted — minutes of footage may be salvageable."""
    rec = make_recorder(tmp_path)
    proc = subprocess.Popen(["bash", "-c", 'trap "" INT; sleep 60'])
    rec._proc = proc
    rec.recording = True
    d = tmp_path / ".rendering"
    d.mkdir()
    tmp = d / "r.mp4"
    tmp.write_bytes(b"partial-footage")
    out = tmp_path / "r.mp4"
    rec._tmp = str(tmp)
    rec._out = str(out)
    rec.GRACE_MS = 400
    rec.KILL_MS = 900
    results = []
    rec.failed.connect(lambda m: results.append(m))
    rec.finished.connect(lambda p: results.append(p))
    rec.stop()
    assert wait_until(qapp, lambda: results, 8)
    assert out.exists() and out.read_bytes() == b"partial-footage", \
        "the partial recording must survive the SIGKILL path"
    assert not tmp.exists()  # moved out of .rendering, not left to the sweep
    assert "partial" in results[0]
    proc.poll() is not None or (proc.kill(), proc.wait())


def test_sweep_stale_tmp_removes_old_orphans_only(tmp_path):
    """Four orphaned mp4s sat in .rendering on 2026-06-06 (EOS wedges +
    app restarts). Old files are dead; fresh ones may be live."""
    import time as _time
    from wondershot.record import sweep_stale_tmp
    d = tmp_path / ".rendering"
    d.mkdir()
    old = d / "Recording_old.mp4"
    old.write_bytes(b"x")
    os.utime(old, (_time.time() - 7200, _time.time() - 7200))
    fresh = d / "Recording_fresh.mp4"
    fresh.write_bytes(b"x")
    sweep_stale_tmp(str(d))
    assert not old.exists()
    assert fresh.exists()
