"""The tray tooltip mirrors the recording duration (recorder.tick)."""
import itertools
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def make_app(qapp, tmp_path, monkeypatch):
    import wondershot.app as appmod
    from wondershot.hotkey import NullHotkeyBackend
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-tt-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings",
                        lambda: _Settings(str(tmp_path)))
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    return appmod.GrabbitApp(qapp)


def test_tick_updates_tray_tooltip_and_action(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    a.recorder.tick.emit("1:05")
    assert a.tray.toolTip() == "Wondershot — recording 1:05"
    assert a.record_action.text() == "Stop recording (1:05)"


def test_tooltip_resets_when_recording_ends(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    a.recorder.tick.emit("0:10")
    a._on_recording_failed("boom")
    assert a.tray.toolTip() == "Wondershot — screenshots"
    a.recorder.tick.emit("0:11")
    p = str(tmp_path / "r.mp4")
    open(p, "wb").write(b"x")
    a._on_recording_finished(p)
    assert a.tray.toolTip() == "Wondershot — screenshots"
