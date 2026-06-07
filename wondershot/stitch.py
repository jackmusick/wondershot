"""Scroll-capture stitcher core (WS-D spike).

PORTABILITY SEAM (WS-E): this module consumes QImages only. It must
NEVER import PipeWire, GStreamer, or gi types — platform frame
delivery lives behind FrameSource implementations (scrollsource.py
on Linux today; Windows/macOS sources later).

Requires numpy (install the spike extra: pip install -e ".[spike]").
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


class FrameSource(QObject):
    """Delivers viewport frames as QImages.

    Implementations own all platform machinery (portals, PipeWire,
    GStreamer, native APIs); consumers only ever see QImages.
    """

    frame = Signal(QImage)
    started = Signal()
    failed = Signal(str)

    def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


# -- QImage <-> numpy ----------------------------------------------------

def qimage_to_rgb(img: QImage) -> np.ndarray:
    """Return an (H, W, 3) uint8 RGB copy of img (any source format)."""
    rgb = img.convertToFormat(QImage.Format_RGB888)
    h, w = rgb.height(), rgb.width()
    # Scanlines are padded to 4 bytes — slice each row to w*3.
    buf = np.frombuffer(rgb.constBits(), dtype=np.uint8,
                        count=rgb.sizeInBytes())
    buf = buf.reshape(h, rgb.bytesPerLine())
    return buf[:, :w * 3].reshape(h, w, 3).copy()


def rgb_to_qimage(arr: np.ndarray) -> QImage:
    """Return a detached QImage (Format_RGB888) from an (H, W, 3) array."""
    h, w, _ = arr.shape
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    img = QImage(arr.tobytes(), w, h, w * 3, QImage.Format_RGB888)
    return img.copy()  # detach from the Python buffer


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """(H, W) float32 luma for matching; exactness doesn't matter."""
    return rgb.astype(np.float32).mean(axis=2)
