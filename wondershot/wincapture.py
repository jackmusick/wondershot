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


class WinCaptureManager(QObject):
    """Windows capture backend with CaptureManager's exact contract.

    Same signals (captured/failed), same public methods, same one-shot
    _pending_crop -> _finish seam. capture_window has no interactive
    picker on Windows and aliases the active-window mode.
    capture_cursor is unsupported (see module docstring).
    """

    captured = Signal(str)
    failed = Signal(str)

    def __init__(self, settings, parent=None, grab=None, window_rect=None):
        super().__init__(parent)
        self.settings = settings
        self._grab = grab or grab_fullscreen          # test seam
        self._window_rect = window_rect or active_window_rect  # test seam
        self._pending_crop = None    # QRect: crop the next capture to this
        self._grab_virtual = None    # QRect of the last grab's desktop union
        self._crop_virtual = None    # test seam; None = use _grab_virtual
        self._overlay = None         # RegionOverlay while picking

    # -- public API (CaptureManager parity) -----------------------------

    def capture_region(self) -> None:
        self._pending_crop = None
        self._delayed(self._do_region)

    def capture_fullscreen(self) -> None:
        self._pending_crop = None
        self._delayed(self._do_fullscreen)

    def capture_window(self) -> None:
        # Windows has no single-window interactive pick; window mode IS
        # the active-window mode (the kwin "window-auto" analog).
        self.capture_active_window()

    def capture_active_window(self) -> None:
        self._pending_crop = None
        self._delayed(self._do_active_window)

    # -- plumbing ----------------------------------------------------------

    def _delayed(self, fn) -> None:
        delay_ms = int(getattr(self.settings, "capture_delay", 0) or 0) * 1000
        if delay_ms:
            QTimer.singleShot(delay_ms, fn)
        else:
            fn()

    def _grab_or_fail(self):
        try:
            img, virtual = self._grab()
        except Exception as e:  # noqa: BLE001 — mss raises ScreenShotError
            self.failed.emit(f"screen grab failed: {e}")
            return None
        self._grab_virtual = virtual
        return img

    def _do_fullscreen(self) -> None:
        img = self._grab_or_fail()
        if img is None:
            return
        self._save_and_finish(img)

    def _do_active_window(self) -> None:
        rect = self._window_rect()
        if rect is None:
            self.failed.emit("window geometry: no active window")
            return
        self._pending_crop = QRect(*rect)
        self._do_fullscreen()

    def _save_and_finish(self, img: QImage) -> None:
        path = unique_path(self.settings.library_dir, timestamp_name())
        if not img.save(path):
            self.failed.emit("could not save screenshot")
            return
        self._finish(path)

    def _finish(self, path: str) -> None:
        """Common tail: apply a pending window crop (CaptureManager seam)."""
        crop, self._pending_crop = self._pending_crop, None
        if crop is not None:
            virtual = self._crop_virtual or self._grab_virtual
            if virtual is not None:
                # False = unusable rect; degrade to the full shot
                crop_file_to_global_rect(path, crop, virtual)
        self.captured.emit(path)

    # -- region mode (the owned picker) --------------------------------------

    def _do_region(self) -> None:
        img = self._grab_or_fail()
        if img is None:
            return
        ov = RegionOverlay(img)
        ov.selected.connect(
            lambda rect: self._region_selected(img, rect))
        ov.cancelled.connect(self._region_cancelled)
        self._overlay = ov
        ov.show_on_desktop()

    def _region_selected(self, img: QImage, rect: QRect) -> None:
        self._overlay = None
        if rect.isEmpty():
            return  # degenerate mapping; treat as cancel
        out = img.copy(rect)
        path = unique_path(self.settings.library_dir, timestamp_name())
        if not out.save(path):
            self.failed.emit("could not save screenshot")
            return
        self.captured.emit(path)

    def _region_cancelled(self) -> None:
        # Cancelled picker: stay silent, exactly like a cancelled
        # spectacle region pick (capture.py _spectacle_done, code 0).
        self._overlay = None


MIN_SELECTION_PX = 4  # smaller than this is a click/slip, not a region


class RegionOverlay(QWidget):
    """Frameless fullscreen rubber-band picker over a frozen grab.

    We own the screen on Windows (no Wayland positioning bans), so the
    overlay covers the desktop, paints the grabbed frame, dims the
    unselected area, and emits selected(QRect) in IMAGE pixel
    coordinates (the grab is physical pixels; the widget is logical —
    map_global_rect does the scaling).
    """

    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self._image = image
        self._press: QPoint | None = None
        self._current: QPoint | None = None
        self._fired = False
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

    def show_on_desktop(self) -> None:
        """Cover the whole virtual desktop (all monitors)."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.virtualGeometry())
        self.show()
        self.raise_()
        self.activateWindow()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.drawImage(self.rect(), self._image)
        dim = QColor(0, 0, 0, 110)
        if self._press is None or self._current is None:
            p.fillRect(self.rect(), dim)
        else:
            sel = selection_rect(self._press, self._current, self.rect())
            for shade in (QRect(0, 0, self.width(), sel.top()),
                          QRect(0, sel.bottom() + 1, self.width(),
                                self.height() - sel.bottom() - 1),
                          QRect(0, sel.top(), sel.left(), sel.height()),
                          QRect(sel.right() + 1, sel.top(),
                                self.width() - sel.right() - 1,
                                sel.height())):
                p.fillRect(shade, dim)
            p.setPen(QPen(QColor("#26a69a"), 2))
            p.drawRect(sel)
        p.end()

    # -- input ----------------------------------------------------------------

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._press = self._current = ev.position().toPoint()
            self.update()

    def mouseMoveEvent(self, ev) -> None:
        if self._press is not None:
            self._current = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton or self._press is None:
            return
        sel = selection_rect(self._press, ev.position().toPoint(),
                             self.rect())
        self._press = self._current = None
        if (sel.width() < MIN_SELECTION_PX
                or sel.height() < MIN_SELECTION_PX):
            self._cancel()
            return
        img_rect = map_global_rect(
            sel, QRect(0, 0, self.width(), self.height()),
            self._image.width(), self._image.height())
        self._fired = True
        self.close()
        self.selected.emit(img_rect)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(ev)

    def _cancel(self) -> None:
        if self._fired:
            return
        self._fired = True
        self.close()
        self.cancelled.emit()
