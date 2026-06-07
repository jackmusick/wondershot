"""ScrollCaptureController: the testable mode state machine behind the
scroll-capture UI. Frames come from an injectable FrameSource (fake
here); stop() stitches and writes a PNG into the library, emitting
captured(path) so the app coordinator can reuse the normal captured
path (quick bar / preview / clipboard)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QImage


@pytest.fixture(scope="session")
def qapp():
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


class FakeSettings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.mic_enabled = False
        self.mic_device = ""
        self.noise_suppression = True
        self.screencast_token = ""


class FakeSource(QObject):
    frame = Signal(QImage)
    started = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.started_calls = 0
        self.stopped = False

    def start(self):
        self.started_calls += 1
        self.started.emit()

    def stop(self):
        self.stopped = True


def _img(color):
    img = QImage(64, 48, QImage.Format_RGB32)
    img.fill(color)
    return img


def make(qapp, tmp_path):
    from wondershot.scrollsource import ScrollCaptureController
    source = FakeSource()
    ctl = ScrollCaptureController(FakeSettings(str(tmp_path)),
                                  source_factory=lambda: source)
    return ctl, source


def test_happy_path_saves_png_and_emits_captured(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    got = []
    ctl.captured.connect(got.append)
    ctl.start()
    assert ctl.running
    source.frame.emit(_img("#336699"))
    qapp.processEvents()  # queued cross-thread delivery in production
    ctl.stop()
    assert source.stopped
    assert len(got) == 1
    path = got[0]
    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path).startswith("ScrollCapture_")
    saved = QImage(path)
    assert (saved.width(), saved.height()) == (64, 48)
    assert not ctl.running


def test_no_frames_emits_failed_and_no_file(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    fails, got = [], []
    ctl.failed.connect(fails.append)
    ctl.captured.connect(got.append)
    ctl.start()
    ctl.stop()
    assert got == []
    assert len(fails) == 1
    assert os.listdir(tmp_path) == []


def test_source_failure_is_forwarded_and_resets(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    fails = []
    ctl.failed.connect(fails.append)
    ctl.start()
    source.failed.emit("portal said no")
    assert fails == ["portal said no"]
    assert not ctl.running


def test_started_signal_is_relayed(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    hits = []
    ctl.started.connect(lambda: hits.append(1))
    ctl.start()
    assert hits == [1]


def test_double_start_is_noop(qapp, tmp_path):
    from wondershot.scrollsource import ScrollCaptureController
    calls = []

    def factory():
        calls.append(1)
        return FakeSource()

    ctl = ScrollCaptureController(FakeSettings(str(tmp_path)),
                                  source_factory=factory)
    ctl.start()
    ctl.start()
    assert calls == [1]


def test_stop_when_idle_is_noop(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    fails, got = [], []
    ctl.failed.connect(fails.append)
    ctl.captured.connect(got.append)
    ctl.stop()
    assert fails == [] and got == []


def test_availability_gate_is_a_function_not_kde(qapp):
    # Gate is gi + Gst + numpy — NOT kwin/KDE. We only pin the contract
    # shape here (callable returning bool); the truthiness depends on
    # what's installed on the box running the suite.
    from wondershot.scrollsource import scroll_capture_available
    assert isinstance(scroll_capture_available(), bool)


def test_save_failure_emits_failed_not_captured(qapp, tmp_path):
    # library_dir vanished mid-session: QImage.save returns False and
    # the controller must report failure, not toast success over a
    # lost scroll session.
    ctl, source = make(qapp, tmp_path / "gone")
    fails, got = [], []
    ctl.failed.connect(fails.append)
    ctl.captured.connect(got.append)
    ctl.start()
    source.frame.emit(_img("#336699"))
    qapp.processEvents()
    ctl.stop()
    assert got == []
    assert len(fails) == 1 and "could not save" in fails[0]
