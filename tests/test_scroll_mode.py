"""Scroll-mode routing through the app coordinator: tray entry gated on
availability (NOT KDE), trigger_capture('scroll') rides the existing
hide_for_capture path, the stop pill drives controller.stop(), and the
stitched PNG goes through the normal _on_captured path."""
import itertools
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

_counter = itertools.count()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []

    def __getattr__(self, k):
        if k in ("stroke_width", "font_size", "capture_delay",
                 "share_expiry_days", "quick_bar_timeout",
                 "video_blur_strength", "gif_fps", "gif_max_width"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick", "capture_cursor",
                                      "record")) else ""


class FakeController(QObject):
    started = Signal()
    captured = Signal(str)
    failed = Signal(str)
    instances = []

    def __init__(self, settings, source_factory=None, parent=None):
        super().__init__(parent)
        FakeController.instances.append(self)
        self.start_calls = 0
        self.stop_calls = 0
        self.running = False

    def start(self):
        self.start_calls += 1
        self.running = True

    def stop(self):
        self.stop_calls += 1
        self.running = False


def make_app(qapp, tmp_path, monkeypatch, scroll_ok=True):
    import wondershot.app as appmod
    import wondershot.scrollsource as scrollmod
    from wondershot.hotkey import NullHotkeyBackend
    FakeController.instances = []
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-sm-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings",
                        lambda: _Settings(str(tmp_path)))
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    monkeypatch.setattr(appmod, "scroll_capture_available",
                        lambda: scroll_ok)
    monkeypatch.setattr(scrollmod, "ScrollCaptureController",
                        FakeController)
    return appmod.GrabbitApp(qapp)


def _menu_texts(app):
    return [a.text() for a in app.tray.contextMenu().actions()]


def test_tray_has_scroll_entry_when_available(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch, scroll_ok=True)
    assert "Scrolling capture" in _menu_texts(app)
    assert app.gallery.scroll_ok is True


def test_tray_entry_absent_when_unavailable(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch, scroll_ok=False)
    assert "Scrolling capture" not in _menu_texts(app)
    assert app.gallery.scroll_ok is False


def _start_scroll(qapp, app):
    app.trigger_capture("scroll")
    # nothing visible -> hide_for_capture returns 0 -> singleShot(0)
    for _ in range(20):
        qapp.processEvents()
        if FakeController.instances:
            ctl = FakeController.instances[-1]
            if ctl.start_calls:
                return ctl
    raise AssertionError("controller never started")


def test_trigger_scroll_hides_windows_and_starts_controller(
        qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    app.gallery.show()
    app.trigger_capture("scroll")
    assert not app.gallery.isVisible()  # hide_for_capture ran first
    # gallery was visible -> hide_for_capture returns 300 ms; wait
    # wall-clock for the singleShot (plan deviation: bare processEvents
    # never spans the delay).
    from PySide6.QtTest import QTest
    for _ in range(50):
        QTest.qWait(10)
        if FakeController.instances and \
                FakeController.instances[-1].start_calls:
            break
    else:
        raise AssertionError("controller never started after the delay")


def test_started_shows_pill_and_pill_stops_controller(
        qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    pill = app._scroll_pill
    assert pill is not None and pill.isVisible()
    pill.stop_requested.emit()
    assert ctl.stop_calls == 1


def test_captured_routes_through_normal_captured_path(
        qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    seen = []
    monkeypatch.setattr(app, "_on_captured", seen.append)
    png = tmp_path / "ScrollCapture_x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nx")
    ctl.captured.emit(str(png))
    assert seen == [str(png)]
    assert app._scroll is None          # controller released
    assert app._scroll_pill is None     # pill closed


def test_failed_routes_through_capture_failed(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    seen = []
    monkeypatch.setattr(app, "_on_capture_failed", seen.append)
    ctl.failed.emit("portal said no")
    assert seen == ["portal said no"]
    assert app._scroll is None
    assert app._scroll_pill is None


def test_second_trigger_while_running_is_noop(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    app.trigger_capture("scroll")
    for _ in range(20):
        qapp.processEvents()
    assert len(FakeController.instances) == 1
    assert ctl.start_calls == 1


def test_tray_action_finishes_running_scroll(qapp, tmp_path, monkeypatch):
    # Spec Addendum 2 Track 4b: the tray is the second finish path
    # ("Ctrl+click tray or click Stop to finish").
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    action = next(a for a in app.tray.contextMenu().actions()
                  if a.text() == "Scrolling capture")
    action.trigger()
    assert ctl.stop_calls == 1
    assert app._scroll_pill is None  # pill closed by the finish path
