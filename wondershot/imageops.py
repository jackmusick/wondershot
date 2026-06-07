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


def rounded_corners(image: QImage, radius: int) -> QImage:
    """Clip the image to a rounded rect (corners go transparent)."""
    from PySide6.QtGui import QPainterPath
    out = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, image.width(), image.height(), radius, radius)
    p.setClipPath(path)
    p.drawImage(0, 0, image)
    p.end()
    return out


def bottom_fade(image: QImage, height: int) -> QImage:
    """Fade the bottom `height` pixels to transparent."""
    from PySide6.QtGui import QLinearGradient, QColor, QBrush
    out = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    h = min(max(1, height), out.height())
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    grad = QLinearGradient(0, out.height() - h, 0, out.height())
    grad.setColorAt(0.0, QColor(0, 0, 0, 255))
    grad.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(QRect(0, out.height() - h, out.width(), h), QBrush(grad))
    p.end()
    return out


def blurred_patch(image: QImage, rect: QRect, radius: int = 12) -> QImage:
    """Gaussian-blurred copy of just `rect` of `image`.

    Rendered via QGraphicsBlurEffect on a throwaway offscreen scene (the
    only gaussian Qt ships); requires a QApplication, so the widget
    imports stay local and the module import stays widget-free. The
    source is padded by `radius` then cropped back, so edge pixels blur
    against their real neighbors instead of transparency.
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import (
        QApplication, QGraphicsBlurEffect, QGraphicsPixmapItem,
        QGraphicsScene,
    )
    if not isinstance(QApplication.instance(), QApplication):
        # QGraphicsScene segfaults under a bare QGuiApplication (or no
        # app at all). Null patch -> PixelateItem's gray-rect fallback.
        return QImage()
    r = rect.normalized().intersected(image.rect())
    if r.isEmpty():
        return QImage()
    pr = r.adjusted(-radius, -radius, radius, radius).intersected(
        image.rect())
    region = image.copy(pr)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(region))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QImage(region.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    scene.render(p, QRectF(0, 0, region.width(), region.height()),
                 QRectF(0, 0, region.width(), region.height()))
    p.end()
    return out.copy(r.x() - pr.x(), r.y() - pr.y(), r.width(), r.height())
