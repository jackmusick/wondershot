"""Bundled toolbar icons with system-theme fallback.

Windows (and any bare desktop) has NO icon theme, so every
``QIcon.fromTheme(name)`` silently renders blank — Jack's 2026-06-07
Windows pass: only Cut/Undo/Redo had glyphs. ``icon(name)`` prefers the
real theme (KDE users keep Breeze), then falls back to an SVG shipped in
``data/icons/`` tinted to the current palette at paint time, so the
glyphs follow light/dark and the disabled state for free.

SVGs are authored with stroke/fill ``#000`` as a color token; the engine
substitutes the palette's ButtonText color when rendering. Keep new
icons to that convention.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (QGuiApplication, QIcon, QIconEngine, QPainter,
                           QPalette, QPixmap)

ICON_DIR = os.path.join(os.path.dirname(__file__), "data", "icons")

_cache: dict[str, QIcon] = {}


def _svg_path(name: str) -> str:
    return os.path.join(ICON_DIR, f"{name}.svg")


class _PaletteSvgEngine(QIconEngine):
    """Render a bundled SVG tinted to the live palette per mode."""

    def __init__(self, svg_bytes: bytes):
        super().__init__()
        self._svg = svg_bytes

    def clone(self):
        return _PaletteSvgEngine(self._svg)

    def _color(self, mode):
        group = (QPalette.Disabled if mode == QIcon.Disabled
                 else QPalette.Normal)
        return QGuiApplication.palette().color(group, QPalette.ButtonText)

    def paint(self, painter, rect, mode, state):
        from PySide6.QtSvg import QSvgRenderer
        color = self._color(mode).name().encode()
        renderer = QSvgRenderer(QByteArray(self._svg.replace(b"#000", color)))
        renderer.render(painter, QRectF(rect))

    def pixmap(self, size: QSize, mode, state):
        # Render at the device pixel ratio so glyphs stay crisp on HiDPI.
        dpr = QGuiApplication.primaryScreen().devicePixelRatio() \
            if QGuiApplication.primaryScreen() else 1.0
        pm = QPixmap(size * dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        self.paint(p, QRect(QPoint(0, 0), size * dpr), mode, state)
        p.end()
        pm.setDevicePixelRatio(dpr)
        return pm


def icon(name: str) -> QIcon:
    """Theme icon if the platform has one, else our bundled tinted SVG."""
    if QIcon.hasThemeIcon(name):
        return QIcon.fromTheme(name)
    cached = _cache.get(name)
    if cached is not None:
        return cached
    path = _svg_path(name)
    if os.path.exists(path):
        with open(path, "rb") as f:
            ic = QIcon(_PaletteSvgEngine(f.read()))
    else:
        ic = QIcon()  # unmapped name: blank, same as before — add the SVG
    _cache[name] = ic
    return ic
