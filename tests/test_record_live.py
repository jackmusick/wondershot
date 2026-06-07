"""Live in-process pipeline smoke tests (Linux dev box, NO portal).

Proves the REAL Gst.parse_launch + bus-driven lifecycle without a portal
session by sourcing from videotestsrc. The encode -> mux -> filesink chain
and bus EOS finalize are identical to production; only the source differs.

importorskip("gi") -> SKIPS on CI without GObject Introspection.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
gi = pytest.importorskip("gi")  # SKIPS on CI without GObject Introspection
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _gst_or_skip():
    try:
        from wondershot.record import _gst
        return _gst()
    except Exception:
        pytest.skip("GStreamer Gst bindings unavailable")


def _pump(qapp, done, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not done and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    return bool(done)


def test_live_force_stop_is_terminal(qapp, tmp_path):
    """REAL pipeline contract: after force_stop() (set NULL) poll_status
    MUST report a terminal status. set NULL posts neither EOS nor ERROR to
    the bus, so without this a genuinely wedged pipeline reports 'running'
    forever and the finalize loop hangs on 'Stopping…' (the exact failure
    the escalation ladder exists to prevent). The FakePipeline masks this."""
    _gst_or_skip()
    from wondershot.record import _GstPipeline
    desc = ("videotestsrc is-live=true ! videoconvert ! videorate ! "
            "video/x-raw,format=I420,framerate=30/1 ! identity name=pause ! "
            "x264enc tune=zerolatency ! h264parse ! queue ! mp4mux name=mux ! "
            f"filesink location={tmp_path / 'wedge.mp4'}")
    pipe = _GstPipeline(desc, str(tmp_path / "wedge.log"))
    deadline = time.monotonic() + 3
    while pipe.poll_status() == "running" and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    pipe.force_stop()
    assert pipe.poll_status() != "running", \
        "force_stop() must make poll_status terminal or the UI hangs"


def test_live_eos_finalizes_playable_mp4(qapp, tmp_path):
    """Real pipeline (videotestsrc, no portal): EOS must finalize a non-empty mp4."""
    _gst_or_skip()
    from wondershot.record import ScreenRecorder, _GstPipeline
    from tests.test_record import FakeSettings
    rec = ScreenRecorder(FakeSettings(str(tmp_path)))
    out = str(tmp_path / "r.mp4")
    tmp = str(tmp_path / ".rendering" / "r.mp4")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    rec.log_path = str(tmp_path / "rec.log")
    desc = ("videotestsrc num-buffers=30 ! videoconvert ! videorate ! "
            "video/x-raw,format=I420,framerate=30/1 ! "
            "x264enc speed-preset=veryfast tune=zerolatency ! h264parse ! "
            f"queue ! mp4mux name=mux ! filesink location={tmp}")
    rec._tmp, rec._out = tmp, out
    rec._pipeline = _GstPipeline(desc, rec.log_path)
    rec.recording = True
    rec._start_watchdog()
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(done.append)
    rec.stop()
    assert _pump(qapp, done, 15), "live pipeline never finalized"
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_live_cairooverlay_draw_callback_fires(qapp, tmp_path):
    """The cairooverlay 'draw' signal path works in-process (B2 wiring).

    Proves the overlay element negotiates and emits draw; cursor-source
    correctness (spa_meta_cursor) is a separate desktop checklist item."""
    Gst = _gst_or_skip()
    if Gst.ElementFactory.find("cairooverlay") is None:
        pytest.skip("cairooverlay element unavailable")
    from wondershot.record import _GstPipeline
    tmp = str(tmp_path / "halo.mp4")
    desc = ("videotestsrc num-buffers=10 ! videoconvert ! videorate ! "
            "video/x-raw,format=I420,framerate=30/1 ! "
            "videoconvert ! cairooverlay name=halo ! videoconvert ! "
            "x264enc speed-preset=veryfast tune=zerolatency ! h264parse ! "
            f"queue ! mp4mux name=mux ! filesink location={tmp}")
    pipe = _GstPipeline(desc, str(tmp_path / "halo.log"))
    fired = []
    overlay = pipe._p.get_by_name("halo")
    assert overlay is not None
    overlay.connect("draw", lambda *a: fired.append(1))
    deadline = time.monotonic() + 10
    while not fired and time.monotonic() < deadline:
        qapp.processEvents()
        if pipe.poll_status() in ("eos", "error"):
            break
        time.sleep(0.02)
    pipe.force_stop()
    assert fired, "cairooverlay draw callback never fired in-process"


def test_live_pause_resume_continuity(qapp, tmp_path):
    """C3: pause/resume the 'pause' identity mid-stream; the mp4 must still
    finalize (no mux error) and be non-empty (continuity check)."""
    _gst_or_skip()
    from wondershot.record import ScreenRecorder, _GstPipeline
    from tests.test_record import FakeSettings
    rec = ScreenRecorder(FakeSettings(str(tmp_path)))
    out = str(tmp_path / "pr.mp4")
    tmp = str(tmp_path / ".rendering" / "pr.mp4")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    rec.log_path = str(tmp_path / "pr.log")
    desc = ("videotestsrc is-live=true ! videoconvert ! videorate ! "
            "video/x-raw,format=I420,framerate=30/1 ! identity name=pause ! "
            "x264enc speed-preset=veryfast tune=zerolatency ! h264parse ! "
            f"queue ! mp4mux name=mux ! filesink location={tmp}")
    rec._tmp, rec._out = tmp, out
    rec._pipeline = _GstPipeline(desc, rec.log_path)
    rec.recording = True
    rec._started_at = time.monotonic()
    rec._start_watchdog()
    # run a bit, pause, run, resume, run, then stop
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.4:
        qapp.processEvents()
        time.sleep(0.02)
    rec.pause()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.4:
        qapp.processEvents()
        time.sleep(0.02)
    rec.resume()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.4:
        qapp.processEvents()
        time.sleep(0.02)
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(done.append)
    rec.stop()
    assert _pump(qapp, done, 15), "paused/resumed pipeline never finalized"
    assert os.path.exists(out) and os.path.getsize(out) > 0, \
        "resumed segment must produce a non-empty mp4 (no mux break)"
