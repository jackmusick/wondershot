"""The scroll-capture stop pill: one affordance (click to finish),
emitted exactly once; Esc also finishes. Frameless/always-on-top
flags are the contract the compositor-placement approach relies on."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_click_emits_stop_once(qapp):
    from wondershot.capture_window import ScrollStopPill
    pill = ScrollStopPill()
    hits = []
    pill.stop_requested.connect(lambda: hits.append(1))
    btn = pill.findChild(QPushButton)
    assert btn is not None
    assert "finish" in btn.text().lower()
    btn.click()
    btn.click()  # double-click must not double-stop
    assert hits == [1]


def test_escape_emits_stop(qapp):
    from wondershot.capture_window import ScrollStopPill
    pill = ScrollStopPill()
    hits = []
    pill.stop_requested.connect(lambda: hits.append(1))
    QTest.keyClick(pill, Qt.Key_Escape)
    assert hits == [1]


def test_window_flags_frameless_on_top(qapp):
    from wondershot.capture_window import ScrollStopPill
    pill = ScrollStopPill()
    flags = pill.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
