# tests/test_win_factories.py
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    backend = "spectacle"
    capture_cursor = False
    capture_delay = 0
    mic_enabled = False
    mic_device = ""
    noise_suppression = True
    screencast_token = ""

    def __init__(self, library_dir="/tmp"):
        self.library_dir = library_dir


# -- capture factory ---------------------------------------------------------

def test_capture_factory_linux_is_byte_identical(qapp, monkeypatch):
    """Linux pin: the factory must return EXACTLY CaptureManager."""
    from wondershot import capture
    monkeypatch.setattr(sys, "platform", "linux")
    m = capture.create_capture_manager(_Settings())
    assert type(m) is capture.CaptureManager


def test_capture_factory_windows(qapp, monkeypatch):
    from wondershot import capture
    from wondershot.wincapture import WinCaptureManager
    monkeypatch.setattr(sys, "platform", "win32")
    m = capture.create_capture_manager(_Settings())
    assert type(m) is WinCaptureManager


# -- window-mode gate ---------------------------------------------------------

def test_window_capture_available_on_windows(monkeypatch):
    from wondershot import capture
    monkeypatch.setattr(sys, "platform", "win32")
    assert capture.window_capture_available() is True


def test_window_capture_available_linux_delegates_to_kwin(monkeypatch):
    from wondershot import capture
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("wondershot.kwin.kwin_available", lambda: False)
    assert capture.window_capture_available() is False
    monkeypatch.setattr("wondershot.kwin.kwin_available", lambda: True)
    assert capture.window_capture_available() is True


# -- recorder factory ----------------------------------------------------------

def test_recorder_factory_linux_is_byte_identical(qapp, monkeypatch):
    from wondershot import record
    monkeypatch.setattr(sys, "platform", "linux")
    r = record.create_screen_recorder(_Settings())
    assert type(r) is record.ScreenRecorder


def test_recorder_factory_windows(qapp, monkeypatch):
    from wondershot import record
    from wondershot.winrecord import WinScreenRecorder
    monkeypatch.setattr(sys, "platform", "win32")
    r = record.create_screen_recorder(_Settings())
    assert type(r) is WinScreenRecorder


def test_win_recorder_has_screenrecorder_signal_contract(qapp):
    """app.py connects these five names blind; both classes must have them."""
    from wondershot.winrecord import WinScreenRecorder
    rec = WinScreenRecorder(_Settings())
    for name in ("started", "stopping", "finished", "failed", "tick"):
        assert hasattr(rec, name), name
    assert hasattr(rec, "recording") and hasattr(rec, "available")
    assert callable(rec.start) and callable(rec.stop)
    assert callable(rec.elapsed_str)
