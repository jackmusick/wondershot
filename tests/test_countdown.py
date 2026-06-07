"""CountdownOverlay: ticks to finished; Esc/click/close cancels.

App wiring: countdown=0 starts the recorder immediately; countdown>0
defers start until the overlay finishes; cancel never starts."""
import itertools
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_counter = itertools.count()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(qapp, cond, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_overlay_counts_down_to_finished(qapp):
    from wondershot.countdown import CountdownOverlay
    cd = CountdownOverlay(3, interval_ms=20)
    got = {"finished": 0, "cancelled": 0}
    cd.finished.connect(lambda: got.__setitem__("finished",
                                                got["finished"] + 1))
    cd.cancelled.connect(lambda: got.__setitem__("cancelled",
                                                 got["cancelled"] + 1))
    cd.show()
    assert cd.label.text() == "3"
    assert wait_until(qapp, lambda: got["finished"], 3)
    assert got == {"finished": 1, "cancelled": 0}


def test_overlay_esc_cancels(qapp):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from wondershot.countdown import CountdownOverlay
    cd = CountdownOverlay(5, interval_ms=10_000)
    got = {"finished": 0, "cancelled": 0}
    cd.finished.connect(lambda: got.__setitem__("finished", 1))
    cd.cancelled.connect(lambda: got.__setitem__("cancelled", 1))
    cd.show()
    cd.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                               Qt.NoModifier))
    qapp.processEvents()
    assert got == {"finished": 0, "cancelled": 1}


def test_overlay_close_emits_cancelled_once(qapp):
    from wondershot.countdown import CountdownOverlay
    cd = CountdownOverlay(5, interval_ms=10_000)
    got = []
    cd.cancelled.connect(lambda: got.append(1))
    cd.show()
    cd.close()
    qapp.processEvents()
    assert got == [1]


# ---- app wiring (make_app repeated from tests/test_record_sync.py) ----

class _Settings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []
        self.record_countdown = 0

    def __getattr__(self, k):
        if k in ("stroke_width", "font_size", "capture_delay",
                 "share_expiry_days", "quick_bar_timeout",
                 "video_blur_strength", "gif_fps", "gif_max_width"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick",
                                      "capture_cursor")) else ""


def make_app(qapp, tmp_path, monkeypatch):
    import wondershot.app as appmod
    from wondershot.hotkey import NullHotkeyBackend
    settings = _Settings(str(tmp_path))
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-cd-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings", lambda: settings)
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    return appmod.GrabbitApp(qapp), settings


def test_zero_countdown_starts_immediately(qapp, tmp_path, monkeypatch):
    a, settings = make_app(qapp, tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a._begin_recording()
    assert started == [1]
    assert getattr(a, "_countdown", None) is None


def test_countdown_defers_then_starts(qapp, tmp_path, monkeypatch):
    a, settings = make_app(qapp, tmp_path, monkeypatch)
    settings.record_countdown = 2
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a._begin_recording()
    assert started == []          # deferred
    assert a._countdown is not None
    a._countdown._timer.setInterval(20)  # fast-forward for the test
    assert wait_until(qapp, lambda: started, 3)
    assert started == [1]
    assert a._countdown is None


def test_second_press_cancels_countdown(qapp, tmp_path, monkeypatch):
    a, settings = make_app(qapp, tmp_path, monkeypatch)
    settings.record_countdown = 5
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a._begin_recording()
    assert a._countdown is not None
    a._begin_recording()          # press again = cancel, not start
    qapp.processEvents()
    assert started == []
    assert a._countdown is None
