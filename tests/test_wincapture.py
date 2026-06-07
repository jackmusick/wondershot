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


# -- WinCaptureManager --------------------------------------------------------

from PySide6.QtGui import QImage as _QImage  # noqa: E402
from PySide6.QtCore import Qt as _Qt  # noqa: E402


class _Settings:
    capture_cursor = False
    capture_delay = 0

    def __init__(self, library_dir):
        self.library_dir = library_dir


def _fake_grab(w=200, h=100, virtual=None):
    """A grab seam returning a blue frame + its virtual rect."""
    img = _QImage(w, h, _QImage.Format_ARGB32)
    img.fill(_Qt.blue)
    v = virtual or QRect(0, 0, w, h)
    return lambda: (img, v)


def _manager(tmp_path, grab=None, window_rect=None):
    from wondershot.wincapture import WinCaptureManager
    return WinCaptureManager(_Settings(str(tmp_path)),
                             grab=grab or _fake_grab(),
                             window_rect=window_rect or (lambda: None))


def test_fullscreen_saves_png_and_emits_captured(qapp, tmp_path):
    m = _manager(tmp_path)
    got = []
    m.captured.connect(got.append)
    m.capture_fullscreen()
    assert len(got) == 1
    assert got[0].startswith(str(tmp_path))
    assert got[0].endswith(".png")
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (200, 100)


def test_fullscreen_grab_failure_emits_failed(qapp, tmp_path):
    def boom():
        raise OSError("no display")
    m = _manager(tmp_path, grab=boom)
    fails = []
    m.failed.connect(fails.append)
    m.capture_fullscreen()
    assert fails and "no display" in fails[0]


def test_active_window_crops_to_window_rect(qapp, tmp_path):
    m = _manager(tmp_path, window_rect=lambda: (10, 20, 50, 40))
    got = []
    m.captured.connect(got.append)
    m.capture_active_window()
    assert len(got) == 1
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (50, 40)
    assert m._pending_crop is None  # one-shot, like CaptureManager


def test_capture_window_is_active_window_on_windows(qapp, tmp_path):
    """No interactive window picker on Windows; 'window' == active window."""
    m = _manager(tmp_path, window_rect=lambda: (0, 0, 80, 60))
    got = []
    m.captured.connect(got.append)
    m.capture_window()
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (80, 60)


def test_active_window_no_window_emits_failed(qapp, tmp_path):
    m = _manager(tmp_path, window_rect=lambda: None)
    fails = []
    m.failed.connect(fails.append)
    m.capture_active_window()
    assert fails and "window" in fails[0]


def test_finish_emits_uncropped_when_rect_unusable(qapp, tmp_path):
    """Parity with test_capture_crop.py: degrade to the full shot."""
    m = _manager(tmp_path, window_rect=lambda: (9999, 9999, 10, 10))
    got = []
    m.captured.connect(got.append)
    m.capture_active_window()
    assert len(got) == 1
    assert _QImage(got[0]).width() == 200


def test_crop_respects_negative_virtual_origin(qapp, tmp_path):
    """Monitor left of primary: virtual origin is negative; the window
    rect is global. Same mapping rules as kwin.map_global_rect."""
    grab = _fake_grab(300, 100, virtual=QRect(-100, 0, 300, 100))
    m = _manager(tmp_path, grab=grab, window_rect=lambda: (-50, 10, 60, 40))
    got = []
    m.captured.connect(got.append)
    m.capture_active_window()
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (60, 40)


def test_capture_delay_defers_the_grab(qapp, tmp_path):
    m = _manager(tmp_path)
    m.settings.capture_delay = 1
    got = []
    m.captured.connect(got.append)
    m.capture_fullscreen()
    assert got == []  # deferred via QTimer, not synchronous
    deadline = __import__("time").monotonic() + 3
    while not got and __import__("time").monotonic() < deadline:
        qapp.processEvents()
    assert len(got) == 1
