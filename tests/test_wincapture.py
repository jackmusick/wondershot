# tests/test_wincapture.py
import ctypes
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# -- import guard (spec item 5) ---------------------------------------------

def test_module_imports_cleanly_on_linux():
    """Nothing at module level may touch ctypes.windll or mss."""
    import wondershot.wincapture  # noqa: F401


# -- bgra_to_qimage -----------------------------------------------------------

def test_bgra_to_qimage_pixel_values(qapp):
    from wondershot.wincapture import bgra_to_qimage
    # one BGRA pixel: blue=10, green=20, red=30, alpha=255
    data = bytes([10, 20, 30, 255])
    img = bgra_to_qimage(data, 1, 1)
    c = img.pixelColor(0, 0)
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (30, 20, 10, 255)


def test_bgra_to_qimage_detaches_from_buffer(qapp):
    """mss frees its buffer after the grab; the QImage must own a copy."""
    from wondershot.wincapture import bgra_to_qimage
    data = bytearray([1, 2, 3, 255] * 4)
    img = bgra_to_qimage(bytes(data), 2, 2)
    del data
    assert img.width() == 2 and img.height() == 2
    img.pixelColor(1, 1)  # must not crash / read freed memory


# -- selection_rect -----------------------------------------------------------

def test_selection_rect_normalizes_any_drag_direction():
    from wondershot.wincapture import selection_rect
    bounds = QRect(0, 0, 200, 100)
    r = selection_rect(QPoint(50, 40), QPoint(10, 20), bounds)
    assert r == QRect(10, 20, 41, 21)  # QRect(p1, p2) is inclusive


def test_selection_rect_clamps_to_bounds():
    from wondershot.wincapture import selection_rect
    bounds = QRect(0, 0, 200, 100)
    r = selection_rect(QPoint(-30, -30), QPoint(500, 500), bounds)
    assert r == bounds


# -- active_window_rect (ctypes fakes, spec: "trivially fakeable") ------------

class FakeUser32:
    def __init__(self, hwnd=1234, win_rect=(5, 6, 105, 86)):
        self.hwnd = hwnd
        self.win_rect = win_rect

    def GetForegroundWindow(self):
        return self.hwnd

    def GetWindowRect(self, hwnd, rect_ref):
        r = rect_ref._obj
        r.left, r.top, r.right, r.bottom = self.win_rect
        return 1


class FakeDwmapi:
    """DwmGetWindowAttribute returning EXTENDED_FRAME_BOUNDS (no shadow)."""

    def __init__(self, rect=(10, 20, 110, 90), hresult=0):
        self.rect = rect
        self.hresult = hresult
        self.calls = []

    def DwmGetWindowAttribute(self, hwnd, attr, rect_ref, size):
        self.calls.append((hwnd, attr, size))
        if self.hresult != 0:
            return self.hresult
        r = rect_ref._obj
        r.left, r.top, r.right, r.bottom = self.rect
        return 0


def test_active_window_rect_uses_extended_frame_bounds():
    from wondershot.wincapture import (
        DWMWA_EXTENDED_FRAME_BOUNDS, RECT, active_window_rect)
    dwm = FakeDwmapi(rect=(10, 20, 110, 90))
    got = active_window_rect(user32=FakeUser32(), dwmapi=dwm)
    assert got == (10, 20, 100, 70)
    hwnd, attr, size = dwm.calls[0]
    assert hwnd == 1234
    assert attr == DWMWA_EXTENDED_FRAME_BOUNDS == 9
    assert size == ctypes.sizeof(RECT)


def test_active_window_rect_falls_back_to_getwindowrect():
    """DWM can fail (e.g. composition quirk); GetWindowRect is the net."""
    from wondershot.wincapture import active_window_rect
    got = active_window_rect(
        user32=FakeUser32(win_rect=(5, 6, 105, 86)),
        dwmapi=FakeDwmapi(hresult=-2147024809))
    assert got == (5, 6, 100, 80)


def test_active_window_rect_none_when_no_foreground_window():
    from wondershot.wincapture import active_window_rect
    assert active_window_rect(
        user32=FakeUser32(hwnd=0), dwmapi=FakeDwmapi()) is None


def test_active_window_rect_none_for_degenerate_rect():
    from wondershot.wincapture import active_window_rect
    assert active_window_rect(
        user32=FakeUser32(), dwmapi=FakeDwmapi(rect=(10, 20, 10, 20))) is None
