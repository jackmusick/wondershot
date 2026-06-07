# wondershot/wincapture.py
"""Windows stills backend: mss grabs + ctypes window geometry + an owned
frameless region overlay.

The kwin.py analog for Windows. Import-safe on every platform: nothing
touches ctypes.windll or imports mss at module level; all Windows API
access goes through injectable seams (user32/dwmapi parameters, the
manager's grab function) so the Linux suite tests everything headless.

Cursor capture: mss grabs via BitBlt without the cursor and exposes no
option to include it — capture_cursor is documented unsupported on
Windows and the toggle is disabled in the capture panel.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .capture import timestamp_name, unique_path
from .kwin import crop_file_to_global_rect, map_global_rect

DWMWA_EXTENDED_FRAME_BOUNDS = 9


class RECT(ctypes.Structure):
    # Defined with portable c_long fields (not ctypes.wintypes) so the
    # Linux suite can build and inspect instances.
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _windll(name: str):
    """Lazy windll accessor — only ever evaluated on Windows."""
    return getattr(ctypes.windll, name)  # pragma: no cover (Windows only)


def bgra_to_qimage(data: bytes, w: int, h: int) -> QImage:
    """mss BGRA bytes -> detached ARGB32 QImage (mss reuses its buffer)."""
    img = QImage(data, w, h, w * 4, QImage.Format_ARGB32)
    return img.copy()


def selection_rect(press: QPoint, current: QPoint, bounds: QRect) -> QRect:
    """Normalized drag rectangle, clamped to the widget bounds.

    Corner sorting is explicit: Qt6's QRect.normalized() shifts a
    reversed rect by one pixel (it swaps the exclusive corners), which
    would make right-to-left drags one pixel smaller than the same
    drag left-to-right.
    """
    x1, x2 = sorted((press.x(), current.x()))
    y1, y2 = sorted((press.y(), current.y()))
    return QRect(QPoint(x1, y1), QPoint(x2, y2)).intersected(bounds)


def active_window_rect(user32=None, dwmapi=None):
    """(x, y, w, h) of the foreground window's visible frame, or None.

    DWMWA_EXTENDED_FRAME_BOUNDS excludes the invisible resize-border /
    drop-shadow that GetWindowRect includes; GetWindowRect is the
    fallback when DWM refuses.
    """
    user32 = user32 if user32 is not None else _windll("user32")
    dwmapi = dwmapi if dwmapi is not None else _windll("dwmapi")
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = RECT()
    res = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect),
        ctypes.sizeof(RECT))
    if res != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    return (rect.left, rect.top, w, h)


def grab_fullscreen():
    """Grab the whole virtual desktop (all monitors).

    Returns (QImage, QRect virtual) where virtual is the desktop union in
    the same physical-pixel space as the image — the crop space for
    _finish (left/top can be negative with monitors left of primary).
    """
    import mss  # lazy: pip extra `wondershot[windows]`
    with mss.mss() as sct:
        mon = sct.monitors[0]
        shot = sct.grab(mon)
        img = bgra_to_qimage(shot.bgra, shot.width, shot.height)
        return img, QRect(mon["left"], mon["top"],
                          mon["width"], mon["height"])
