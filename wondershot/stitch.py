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


# -- offset detection ------------------------------------------------------

def detect_offset(prev: np.ndarray, cur: np.ndarray,
                  band: int = 64, threshold: float = 8.0) -> int | None:
    """Vertical scroll distance between two grayscale frames.

    Overlap band matching: take the top `band` rows of cur and slide
    them down prev; at the true offset d, cur[y] == prev[y + d], so
    the band matches prev[d : d + band].

    Returns 0 for no motion, d > 0 for a downward scroll, or None
    when no candidate's mean abs difference beats `threshold`
    (scene change / unrelated frames).

    Known spike limitation: a uniform (featureless) band matches
    everywhere and resolves to d=0 (frame dropped) — acceptable.
    """
    h = prev.shape[0]
    band = min(band, h)
    strip = cur[:band]
    best_d: int | None = None
    best_score = threshold
    for d in range(0, h - band + 1):
        score = float(np.abs(prev[d:d + band] - strip).mean())
        if score < best_score:  # strict: ties keep the smallest d
            best_d, best_score = d, score
    return best_d


# -- fixed header/footer heuristic (best effort for the spike) ------------

def static_bands(prev: np.ndarray, cur: np.ndarray,
                 tolerance: float = 4.0) -> tuple[int, int]:
    """(header_height, footer_height): contiguous edge rows that are
    identical at the SAME y across a scrolled pair — i.e. window
    chrome / sticky headers that don't move while content scrolls.

    Best effort: scrolled content that coincidentally matches itself
    can inflate the bands; real pages rarely do. If the 'static'
    region covers the whole frame (frames identical), returns (0, 0).
    """
    row_same = np.abs(prev - cur).mean(axis=1) < tolerance
    h = len(row_same)
    header = 0
    while header < h and row_same[header]:
        header += 1
    footer = 0
    while footer < h and row_same[h - 1 - footer]:
        footer += 1
    if header + footer >= h:
        return (0, 0)
    return (header, footer)
