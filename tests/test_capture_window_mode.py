import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    show_gallery_after_capture = True
    copy_after_capture = True
    capture_cursor = False
    capture_delay = 0


def _window_buttons(w):
    return [b for b in w.findChildren(QPushButton) if b.text() == "Window"]


def test_window_button_present_and_fires_mode(qapp):
    from wondershot.capture_window import CaptureWindow
    w = CaptureWindow(_Settings(), window_mode=True)
    btns = _window_buttons(w)
    assert len(btns) == 1
    fired = []
    w.capture_requested.connect(fired.append)
    btns[0].click()
    assert fired == ["window-auto"]


def test_window_button_hidden_without_probe(qapp):
    from wondershot.capture_window import CaptureWindow
    w = CaptureWindow(_Settings())  # default: no window mode
    assert not _window_buttons(w)
