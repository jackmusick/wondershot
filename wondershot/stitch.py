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


# -- offset detection (v2: multi-band consensus) ---------------------------

def _slide_band(prev_col: np.ndarray, strip_col: np.ndarray,
                threshold: float) -> tuple[int | None, float]:
    """Slide strip_col down prev_col; return (best_d, best_score).

    best_d is None when no candidate's mean abs difference beats
    threshold (in which case best_score is the threshold itself).
    Ties keep the smallest d (strict <).
    """
    h = prev_col.shape[0]
    band = strip_col.shape[0]
    best_d: int | None = None
    best_score = threshold
    for d in range(0, h - band + 1):
        score = float(np.abs(prev_col[d:d + band] - strip_col).mean())
        if score < best_score:
            best_d, best_score = d, score
    return best_d, best_score


def textured_xs(strip: np.ndarray, band_w: int, n: int,
                var_min: float) -> list[int]:
    """Up to n evenly spaced x positions whose (band_h, band_w) patch
    has variance >= var_min — flat patches (margins, blank panels)
    match everywhere and must not vote. Narrow images (width <=
    band_w) get the single full-width band at x=0."""
    w = strip.shape[1]
    if w <= band_w:
        return [0]
    xs = np.linspace(0, w - band_w, n).astype(int)
    return [int(x) for x in xs
            if float(strip[:, x:x + band_w].var()) >= var_min]


def _consensus(ds: list[int], n_candidates: int,
               tol: int) -> tuple[int | None, float]:
    """Median offset with outlier rejection.

    confidence = inlier fraction over the *candidate* band count, so
    bands that found no match at all (None) also dilute confidence.
    """
    if not ds:
        return None, 0.0
    med = int(np.median(ds))
    inliers = [d for d in ds if abs(d - med) <= tol]
    conf = len(inliers) / max(n_candidates, 1)
    return int(round(float(np.median(inliers)))), conf


def detect_offset(prev: np.ndarray, cur: np.ndarray,
                  band: int = 64, threshold: float = 8.0,
                  n_bands: int = 5, band_w: int = 48,
                  var_min: float = 100.0, tol: int = 2,
                  ) -> tuple[int | None, float]:
    """Vertical scroll distance between two grayscale frames.

    Takes the top `band` rows of cur and matches them against prev at
    up to `n_bands` texture-selected x positions (variance >= var_min;
    flat bands are skipped — they match everywhere). Each band votes
    an offset; the median with +-tol outlier rejection wins, and
    confidence is the inlier fraction. When consensus is weak
    (< 0.5) a full-width full-overlap slide is tried as a fallback,
    accepted only on a strong score (< threshold/2) at confidence
    0.5. Kinetic scrolling lands frames at fractional offsets: bands
    then disagree by +-1 (absorbed by tol) and mid-animation smear
    pushes per-band scores past threshold, so confidence collapses
    and the caller can skip the frame instead of mis-stitching it.

    Returns (offset, confidence): offset 0 means no motion, d > 0 a
    downward scroll, None no reliable match (scene change, blur,
    featureless frame). confidence is 0.0..1.0.
    """
    h = prev.shape[0]
    band = min(band, h)
    strip = cur[:band]
    xs = textured_xs(strip, band_w, n_bands, var_min)
    votes = [
        d for x in xs
        for d, _ in (_slide_band(prev[:, x:x + band_w],
                                 strip[:, x:x + band_w], threshold),)
        if d is not None
    ]
    d, conf = _consensus(votes, len(xs), tol)
    if d is not None and conf >= 0.5:
        return d, conf
    # Bands disagree or none were textured/matchable: full-overlap
    # correlation across the full width, accepted only when decisive.
    d_full, score = _slide_band(prev, strip, threshold)
    if d_full is not None and score < threshold * 0.5:
        return d_full, 0.5
    return None, 0.0


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


# -- accumulator -----------------------------------------------------------

class ScrollStitcher:
    """Accumulates scrolled viewport frames into one tall image.

    Feed frames via add_frame() in capture order; read the tall
    QImage from result(). Pure image math — safe to unit test and
    to reuse unchanged on Windows/macOS (WS-E).
    """

    def __init__(self, band: int = 64, col_step: int = 4):
        self.band = band
        self.col_step = col_step      # column subsampling for matching
        self._canvas: np.ndarray | None = None     # (H, W, 3) uint8
        self._prev_gray: np.ndarray | None = None  # full-res gray
        self._header = 0
        self._footer = 0
        self._bands_locked = False
        self.frames_used = 0
        self.frames_dropped = 0

    def add_frame(self, img: QImage) -> None:
        rgb = qimage_to_rgb(img)
        gray = to_gray(rgb)
        if self._canvas is None:
            self._canvas = rgb
            self._prev_gray = gray
            self.frames_used += 1
            return
        if float(np.abs(gray - self._prev_gray).mean()) < 1.0:
            self.frames_dropped += 1   # no motion: drop
            return
        if not self._bands_locked:
            # First moving pair defines the fixed chrome; freeze it
            # and re-crop the canvas (which is just frame 0 so far).
            self._header, self._footer = static_bands(
                self._prev_gray, gray)
            self._bands_locked = True
            self._canvas = self._crop(self._canvas)
        # v2 matches a few narrow bands, so full-resolution columns are
        # affordable — col_step subsampling is no longer applied (the
        # ctor still accepts it for API compatibility).
        d, confidence = detect_offset(
            self._crop(self._prev_gray), self._crop(gray),
            band=self.band)
        self._prev_gray = gray   # always resync, even on a miss
        if not d:                # None (scene change) or 0 (no scroll)
            self.frames_dropped += 1
            return
        self._canvas = np.vstack([self._canvas, self._crop(rgb)[-d:]])
        self.frames_used += 1

    def _crop(self, arr: np.ndarray) -> np.ndarray:
        end = arr.shape[0] - self._footer
        return arr[self._header:end]

    def result(self) -> QImage:
        if self._canvas is None:
            return QImage()
        return rgb_to_qimage(self._canvas)
