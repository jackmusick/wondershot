"""Pure image operations — no widgets, unit-testable."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter


def crop(image: QImage, rect: QRect) -> QImage:
    """Return the sub-image inside rect (clamped to image bounds)."""
    r = rect.normalized().intersected(image.rect())
    if r.isEmpty():
        return image.copy()
    return image.copy(r)


def pixelated_patch(image: QImage, rect: QRect, block: int = 14) -> QImage:
    """Return a pixelated copy of just the region `rect` of `image`."""
    r = rect.normalized().intersected(image.rect())
    if r.isEmpty():
        return QImage()
    region = image.copy(r)
    small_w = max(1, r.width() // block)
    small_h = max(1, r.height() // block)
    # Smooth downscale averages colors; fast upscale gives hard blocks.
    small = region.scaled(
        small_w, small_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    )
    return small.scaled(r.size(), Qt.IgnoreAspectRatio, Qt.FastTransformation)


def pixelate(image: QImage, rect: QRect, block: int = 14) -> QImage:
    """Return a copy of `image` with `rect` pixelated in place."""
    r = rect.normalized().intersected(image.rect())
    out = image.copy()
    if r.isEmpty():
        return out
    patch = pixelated_patch(image, r, block)
    p = QPainter(out)
    p.drawImage(r.topLeft(), patch)
    p.end()
    return out


def cut_out(image: QImage, start: int, end: int, horizontal: bool) -> QImage:
    """Remove a band from the image and join the remaining halves.

    horizontal=True removes rows [start, end) (image gets shorter);
    horizontal=False removes columns [start, end) (image gets narrower).
    """
    if start > end:
        start, end = end, start
    if horizontal:
        start = max(0, start)
        end = min(image.height(), end)
        if end <= start:
            return image.copy()
        top = image.copy(0, 0, image.width(), start)
        bottom = image.copy(0, end, image.width(), image.height() - end)
        out = QImage(image.width(), start + bottom.height(), image.format())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawImage(0, 0, top)
        p.drawImage(0, start, bottom)
        p.end()
        return out
    else:
        start = max(0, start)
        end = min(image.width(), end)
        if end <= start:
            return image.copy()
        left = image.copy(0, 0, start, image.height())
        right = image.copy(end, 0, image.width() - end, image.height())
        out = QImage(start + right.width(), image.height(), image.format())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawImage(0, 0, left)
        p.drawImage(start, 0, right)
        p.end()
        return out
