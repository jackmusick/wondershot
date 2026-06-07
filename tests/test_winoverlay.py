# tests/test_winoverlay.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _image(w=400, h=200):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.darkGreen)
    return img


def _overlay(img=None):
    from wondershot.wincapture import RegionOverlay
    ov = RegionOverlay(img or _image())
    ov.resize(400, 200)  # offscreen: showFullScreen is meaningless; fix size
    ov.show()
    return ov


def test_drag_emits_selected_in_image_pixels(qapp):
    ov = _overlay()
    got = []
    ov.selected.connect(got.append)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(10, 20))
    QTest.mouseMove(ov, QPoint(110, 80))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(110, 80))
    assert len(got) == 1
    # widget == image size here, so coordinates map 1:1 (inclusive QRect)
    assert got[0] == QRect(10, 20, 101, 61)


def test_drag_maps_through_scale_when_image_is_hidpi(qapp):
    """Image is 2x the widget (physical vs logical pixels)."""
    ov = _overlay(_image(800, 400))
    got = []
    ov.selected.connect(got.append)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(10, 20))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(110, 80))
    r = got[0]
    assert (r.x(), r.y()) == (20, 40)
    assert abs(r.width() - 202) <= 2 and abs(r.height() - 122) <= 2


def test_tiny_drag_is_a_cancel(qapp):
    ov = _overlay()
    sel, can = [], []
    ov.selected.connect(sel.append)
    # cancelled carries no payload; list.append needs exactly one arg
    ov.cancelled.connect(lambda: can.append(1))
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(51, 51))
    assert sel == [] and len(can) == 1


def test_escape_cancels(qapp):
    ov = _overlay()
    can = []
    ov.cancelled.connect(lambda: can.append(1))
    QTest.keyClick(ov, Qt.Key_Escape)
    assert len(can) == 1


def test_region_capture_saves_selection(qapp, tmp_path):
    """End-to-end through WinCaptureManager with a driven overlay."""
    from wondershot.wincapture import WinCaptureManager

    class S:
        capture_delay = 0
        capture_cursor = False

        def __init__(self, d):
            self.library_dir = d

    img = _image(400, 200)
    m = WinCaptureManager(S(str(tmp_path)),
                          grab=lambda: (img, QRect(0, 0, 400, 200)),
                          window_rect=lambda: None)
    got = []
    m.captured.connect(got.append)
    m.capture_region()
    ov = m._overlay
    assert ov is not None
    ov.resize(400, 200)
    # NB: QPoint(0, 0) is null and QTest substitutes the widget center;
    # start the drag at (1, 1) instead.
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(100, 50))
    assert len(got) == 1
    out = QImage(got[0])
    assert (out.width(), out.height()) == (100, 50)
    assert m._overlay is None  # released after selection


def test_region_cancel_is_silent(qapp, tmp_path):
    """Esc on the overlay = cancelled picker: no captured, no failed
    (same semantics as a cancelled spectacle pick)."""
    from wondershot.wincapture import WinCaptureManager

    class S:
        capture_delay = 0
        capture_cursor = False

        def __init__(self, d):
            self.library_dir = d

    m = WinCaptureManager(S(str(tmp_path)),
                          grab=lambda: (_image(), QRect(0, 0, 400, 200)),
                          window_rect=lambda: None)
    events = []
    m.captured.connect(lambda p: events.append(("cap", p)))
    m.failed.connect(lambda msg: events.append(("fail", msg)))
    m.capture_region()
    QTest.keyClick(m._overlay, Qt.Key_Escape)
    assert events == []
    assert m._overlay is None
