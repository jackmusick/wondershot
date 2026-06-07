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
