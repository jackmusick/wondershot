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

REGION_PROMPT = (
    "This is a screenshot of an application or web page. Identify the "
    "major visual regions so the screenshot can be redrawn as a "
    "simplified mockup.\n"
    "Reply with ONLY a JSON array of objects, each "
    '{"type": "text"|"image"|"chrome", "x0": .., "y0": .., '
    '"x1": .., "y1": ..} with coordinates normalized to 0..1 relative '
    "to the image width/height (x0,y0 = top-left, x1,y1 = "
    "bottom-right).\n"
    'Use "text" for lines or blocks of text, "image" for photos, icons '
    'and illustrations, and "chrome" for window furniture: title bars, '
    "toolbars, menus, tabs, sidebars, buttons and input fields.\n"
    "Cover the visually significant regions; avoid overlapping boxes. "
    "Reply [] if nothing is recognizable. No prose, no markdown."
)


def parse_regions(reply: str, width: int, height: int) -> list[Region]:
    """LLM reply -> clamped pixel Regions. Junk entries are dropped
    silently (unknown kind, missing/non-numeric coords, empty after
    clamping); a non-JSON or non-array reply raises OSError, mirroring
    redact.parse_bboxes."""
    try:
        data = json.loads(extract_json(reply))
    except ValueError as e:
        raise OSError(f"AI reply was not JSON: {reply[:120]}") from e
    if not isinstance(data, list):
        raise OSError("AI reply was not a JSON array")
    img = QRect(0, 0, width, height)
    regions: list[Region] = []
    for box in data:
        if not isinstance(box, dict):
            continue
        kind = str(box.get("type", "")).strip().lower()
        if kind not in REGION_KINDS:
            continue
        try:
            x0 = float(box["x0"]) * width
            y0 = float(box["y0"]) * height
            x1 = float(box["x1"]) * width
            y1 = float(box["y1"]) * height
        except (KeyError, TypeError, ValueError):
            continue
        r = QRect(round(min(x0, x1)), round(min(y0, y1)),
                  round(abs(x1 - x0)), round(abs(y1 - y0))).intersected(img)
        if not r.isEmpty():
            regions.append(Region(r, kind))
    return regions


def simplify_regions(image, endpoint: str, api_key: str,
                     model: str) -> list[Region]:
    """Blocking pipeline (call from AIJob, never the GUI thread)."""
    reply = aiclient.chat(endpoint, api_key, model, REGION_PROMPT,
                          image=image)
    return parse_regions(reply, image.width(), image.height())
