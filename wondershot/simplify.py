"""AI image simplifier: vision LLM finds UI regions, the editor replaces
them with clean, fully editable objects (Snagit-better: the output is
RectItems on the canvas, not baked pixels).

Pure pieces live here, mirroring redact.py: the region prompt, the
JSON-reply parsing/clamping, and dominant-color sampling. The editor
turns Regions into filled RectItems — always non-destructive, one undo
macro.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from . import aiclient
from .redact import extract_json

# Fill for "text" regions: a neutral text-placeholder gray (Snagit-style
# blocked-out text runs). Chrome/image regions get a sampled color instead.
TEXT_FILL = "#c8c8c8"

REGION_KINDS = ("text", "image", "chrome")


@dataclass(frozen=True)
class Region:
    rect: QRect
    kind: str  # one of REGION_KINDS


def dominant_color(image: QImage, rect: QRect) -> QColor:
    """Most common color inside `rect`, robust to antialiasing noise.

    Pixels are bucketed to 3 bits per channel; the most populous bucket's
    average is returned. Sampled on a <=64x64 grid so large regions stay
    fast. Off-image rects fall back to neutral gray (never raises).
    """
    r = QRect(rect).intersected(image.rect())
    if image.isNull() or r.isEmpty():
        return QColor("#808080")
    img = image.convertToFormat(QImage.Format_ARGB32)
    step_x = max(1, r.width() // 64)
    step_y = max(1, r.height() // 64)
    counts: dict[tuple[int, int, int], list[int]] = {}
    for y in range(r.top(), r.top() + r.height(), step_y):
        for x in range(r.left(), r.left() + r.width(), step_x):
            c = img.pixelColor(x, y)
            key = (c.red() >> 5, c.green() >> 5, c.blue() >> 5)
            e = counts.setdefault(key, [0, 0, 0, 0])
            e[0] += 1
            e[1] += c.red()
            e[2] += c.green()
            e[3] += c.blue()
    n, sr, sg, sb = max(counts.values(), key=lambda e: e[0])
    return QColor(sr // n, sg // n, sb // n)
