# AI Simplifier + Editor Backlog Implementation Plan (Track 4a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the AI image simplifier (vision LLM → editable canvas objects, Snagit-better) plus four editor-backlog items: text alignment, style-change undo, a gaussian-blur sibling of the pixelate tool, and drag-to-swap step renumbering.

**Architecture:** A new `wondershot/simplify.py` holds the pure pieces (region prompt, JSON parsing/clamping, dominant-color sampling) mirroring `redact.py`'s shape; the editor gets an `AI Simplify` toolbar action that runs `simplify.simplify_regions` on an `AIJob` behind a progress dialog and converts the returned typed regions into filled `RectItem`s inside one undo macro — non-destructive, fully editable afterwards. Editor-backlog work rides on two new mechanisms: a `StyleCommand` undo command that replaces the properties panel's direct mutation (alignment, color, stroke, font size all flow through it), and a `GaussianBlurItem` subclassing `PixelateItem` with a swapped patch-renderer. Every new item/property serializes through the sidecar `to_dict`/`from_dict` round-trip and extends `tests/test_items_serialize.py`.

**Tech Stack:** Python 3 + PySide6 (QGraphicsScene editor, QUndoStack), stdlib HTTP via existing `aiclient.py`, pytest with `QT_QPA_PLATFORM=offscreen`.

**Execution environment:** Worktree `/home/jack/GitHub/grabbit-wt/simplifier-editor` (branched from `main`). Note: the orchestrator will cherry-pick the plan commit into your branch before you start; just verify the plan file exists in your worktree. Then set up the venv:

```bash
cd /home/jack/GitHub/grabbit-wt/simplifier-editor
test -f docs/superpowers/plans/2026-06-07-simplifier-editor-backlog.md || echo "PLAN MISSING — stop"
python -m venv .venv
.venv/bin/pip install -e ".[spike]" pytest
```

Run ALL tests with `QT_QPA_PLATFORM=offscreen` (the env var is also set defensively at the top of every test module, matching the existing files). Full-suite check: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ -q` — 277 tests green on main before you start.

**Explicit scope notes:**
- *Rotate-cursor polish*: already shipped — `items.rotate_cursor()` draws a curved-arrow cursor and `HandleItem` applies it to the rotate grip. **No work**; do not touch it.
- *Text-box edge snapping*: **deliberately deferred** — this IS in the spec's Track 4a brief ("text alignment (left/center/right) + edge snapping in text boxes"), but the spec one-liner is ambiguous about what snaps to what (text to box edges vs. box to image edges) and needs a design call. Task 11 MUST append one backlog line to ROADMAP.md recording the deferral (ROADMAP.md is shared with track 4b — **append-only**, never edit existing lines). Flag the deferral in your completion report so the orchestrator can decide whether it ships in a follow-up.
- *Cross-track file boundary*: track 4b (running in parallel) owns `gallery.py`, `app.py`, `capture_window.py`, `scrollsource.py`, `cli.py` — **do not touch them**. `settings.py`, `settings_dialog.py`, and `ROADMAP.md` are shared, append-only; this plan touches none of them except the single ROADMAP.md backlog line in Task 11.
- *Settings stubs landmine*: this plan adds **zero** new settings keys read during widget construction (the simplifier reuses the existing `ai_endpoint`/`ai_api_key`/`ai_model` keys, already read via `getattr` with defaults; the blur tool uses a fixed default radius like pixelate's fixed `block=14`). Task 11 still verifies this with a grep so the batch-3 merge crash cannot recur.

---

## File Structure

```
wondershot/
  simplify.py          NEW — region prompt, Region dataclass, parse_regions(),
                       dominant_color(), simplify_regions() blocking pipeline
  items.py             MODIFIED — RectItem optional fill (+serialization),
                       TextItem alignment (+serialization), GaussianBlurItem
                       (subclass of PixelateItem, type "blur"), get_style/
                       apply_style grow "align", item_from_dict dispatches "blur"
  imageops.py          MODIFIED — blurred_patch() (gaussian region blur)
  editor.py            MODIFIED — StyleCommand + SwapStepNumbersCommand undo
                       commands, AI Simplify toolbar action + apply_simplify_regions,
                       Tool.BLUR + _apply_blur, alignment buttons in the
                       properties panel, step-drag swap hooks in CanvasView
tests/
  test_simplify.py     NEW — pure functions: parsing, clamping, dominant color
  test_editor_simplify.py  NEW — editor integration (objects, macro-undo, toolbar)
  test_editor_backlog.py   NEW — style undo, alignment panel, blur tool, step swap
  test_items_serialize.py  MODIFIED — fill, align, blur round-trips (MANDATORY)
  test_imageops.py     MODIFIED — blurred_patch tests
```

Responsibilities: `simplify.py` is pure/headless-testable (no widgets, like `redact.py`); all GUI glue stays in `editor.py`; all serialization stays in `items.py`.

---

### Task 1: RectItem optional fill (serialization first)

The simplifier emits *filled* rectangles. `RectItem` today is outline-only (`Qt.NoBrush`) and its dict has no brush. Add an optional `fill` that is backward/forward compatible: absent key ⇒ no brush, exactly today's behavior.

**Files:**
- Modify: `wondershot/items.py` (RectItem, ~lines 192-212)
- Test: `tests/test_items_serialize.py`

- [x] **Step 1: Write the failing tests** — append to `tests/test_items_serialize.py`:

```python
def test_rect_fill_roundtrip(qapp):
    from PySide6.QtCore import Qt
    from wondershot.items import RectItem
    item = RectItem(QRectF(1, 2, 30, 20), QColor("#202020"), 1,
                    fill=QColor("#c8c8c8"))
    assert item.brush().style() != Qt.NoBrush
    out = roundtrip(item)
    assert out.brush().color() == QColor("#c8c8c8")
    assert out.brush().style() != Qt.NoBrush
    assert out.pen().color() == QColor("#202020")


def test_rect_without_fill_stays_hollow(qapp):
    from PySide6.QtCore import Qt
    from wondershot.items import RectItem
    item = RectItem(QRectF(0, 0, 10, 10), QColor("red"), 3)
    d = item.to_dict()
    assert "fill" not in d              # old sidecars stay byte-identical
    out = roundtrip(item)
    assert out.brush().style() == Qt.NoBrush
```

- [x] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_items_serialize.py -v -k fill`
Expected: FAIL — `TypeError: ... __init__() got an unexpected keyword argument 'fill'`

- [x] **Step 3: Implement** — replace `RectItem` in `wondershot/items.py`:

```python
class RectItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, color: QColor, width: int,
                 fill: QColor | None = None):
        super().__init__(rect)
        _mark(self)
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self._fill = QColor(fill) if fill is not None else None
        self.setBrush(QBrush(self._fill) if self._fill is not None
                      else Qt.NoBrush)

    def to_dict(self) -> dict:
        r = self.rect()
        d = {"type": "rect",
             "rect": [r.x(), r.y(), r.width(), r.height()],
             "color": _color_str(self.pen().color()),
             "width": self.pen().width(), **_transform_dict(self)}
        if self._fill is not None:
            d["fill"] = _color_str(self._fill)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RectItem":
        r = d["rect"]
        fill = QColor(d["fill"]) if d.get("fill") else None
        item = cls(QRectF(r[0], r[1], r[2], r[3]),
                   QColor(d["color"]), int(d["width"]), fill=fill)
        _apply_transform(item, d)
        return item
```

- [x] **Step 4: Run the whole serialize file** (existing rect tests must still pass)

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_items_serialize.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add wondershot/items.py tests/test_items_serialize.py
git commit -m "feat(items): optional fill on RectItem, serialized only when set"
```

---

### Task 2: simplify.py — dominant_color (pure, TDD)

Sample the dominant color of a region: bucket pixels to 3 bits/channel (so antialiasing noise collapses into one bucket), pick the most populous bucket, return that bucket's average color. Grid-sampled so huge regions stay fast.

**Files:**
- Create: `wondershot/simplify.py`
- Create: `tests/test_simplify.py`

- [x] **Step 1: Write the failing tests** — create `tests/test_simplify.py`:

```python
"""Pure-function tests for the AI simplifier (no editor, no network)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _img(w, h, color):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return img


def test_dominant_color_solid_region(qapp):
    from wondershot.simplify import dominant_color
    img = _img(100, 80, "#3daee9")
    assert dominant_color(img, QRect(10, 10, 50, 40)) == QColor("#3daee9")


def test_dominant_color_majority_wins(qapp):
    from wondershot.simplify import dominant_color
    img = _img(100, 100, "#102030")          # majority: dark blue
    p = QPainter(img)
    p.fillRect(0, 0, 100, 20, QColor("#ffffff"))   # minority stripe
    p.end()
    c = dominant_color(img, QRect(0, 0, 100, 100))
    assert c == QColor("#102030")


def test_dominant_color_clamps_and_falls_back(qapp):
    from wondershot.simplify import dominant_color
    img = _img(50, 50, "#ff0000")
    # fully off-image -> neutral fallback, never a crash
    assert dominant_color(img, QRect(200, 200, 10, 10)) == QColor("#808080")
    # partially off-image -> clamped, still the image color
    assert dominant_color(img, QRect(45, 45, 30, 30)) == QColor("#ff0000")
```

- [x] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_simplify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wondershot.simplify'`

- [x] **Step 3: Implement** — create `wondershot/simplify.py`:

```python
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
```

(The prompt/parsing/pipeline functions arrive in Task 3 — keep this commit to `dominant_color` plus module scaffolding.)

- [x] **Step 4: Run to verify pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_simplify.py -v`
Expected: 3 PASS

- [x] **Step 5: Commit**

```bash
git add wondershot/simplify.py tests/test_simplify.py
git commit -m "feat(simplify): dominant_color region sampler (pure, bucketed)"
```

---

### Task 3: simplify.py — region prompt, parsing, clamping, pipeline

Same pure-function discipline as `redact.parse_bboxes`: the LLM returns normalized bboxes + a type label; parsing clamps to the image, drops malformed entries and unknown kinds, never raises on junk geometry (only on non-JSON).

**Files:**
- Modify: `wondershot/simplify.py`
- Test: `tests/test_simplify.py`

- [x] **Step 1: Write the failing tests** — append to `tests/test_simplify.py`:

```python
def test_parse_regions_normalized_to_pixels(qapp):
    from wondershot.simplify import parse_regions
    reply = ('[{"type": "text", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.2},'
             ' {"type": "chrome", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.05}]')
    regions = parse_regions(reply, 1000, 800)
    assert len(regions) == 2
    assert regions[0].kind == "text"
    assert regions[0].rect == QRect(100, 80, 400, 80)
    assert regions[1].kind == "chrome"
    assert regions[1].rect == QRect(0, 0, 1000, 40)


def test_parse_regions_unwraps_fences_and_clamps(qapp):
    from wondershot.simplify import parse_regions
    reply = ('```json\n[{"type": "IMAGE", "x0": 0.9, "y0": 0.9, '
             '"x1": 1.4, "y1": 1.4}]\n```')
    regions = parse_regions(reply, 100, 100)
    assert len(regions) == 1
    assert regions[0].kind == "image"          # kind is case-normalized
    assert regions[0].rect == QRect(90, 90, 10, 10)   # clamped to image


def test_parse_regions_skips_junk(qapp):
    from wondershot.simplify import parse_regions
    reply = ('[{"type": "hologram", "x0": 0, "y0": 0, "x1": 0.5, "y1": 0.5},'
             ' {"type": "text"},'
             ' "not an object",'
             ' {"type": "text", "x0": "a", "y0": 0, "x1": 0.5, "y1": 0.5},'
             ' {"type": "text", "x0": 0.5, "y0": 0.5, "x1": 0.5, "y1": 0.5}]')
    assert parse_regions(reply, 100, 100) == []   # unknown kind, missing
    # coords, wrong shape, non-numeric, zero-area: all silently dropped


def test_parse_regions_rejects_non_json(qapp):
    from wondershot.simplify import parse_regions
    with pytest.raises(OSError):
        parse_regions("I could not find any regions, sorry!", 100, 100)
    with pytest.raises(OSError):
        parse_regions('{"regions": []}', 100, 100)   # not an array


def test_simplify_regions_pipeline_calls_chat(qapp, monkeypatch):
    import wondershot.simplify as simplify
    calls = {}

    def fake_chat(endpoint, api_key, model, prompt, image=None, timeout=120):
        calls.update(endpoint=endpoint, model=model, prompt=prompt,
                     image=image)
        return '[{"type": "text", "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}]'

    monkeypatch.setattr(simplify.aiclient, "chat", fake_chat)
    img = _img(200, 100, "white")
    regions = simplify.simplify_regions(img, "http://localhost:1234", "k",
                                        "llava")
    assert calls["model"] == "llava"
    assert calls["image"] is img               # vision call carries the image
    assert "JSON array" in calls["prompt"]
    assert regions == [simplify.Region(QRect(0, 0, 100, 50), "text")]
```

- [x] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_simplify.py -v`
Expected: the 5 new tests FAIL with `ImportError: cannot import name 'parse_regions'` (the 3 Task-2 tests still pass)

- [x] **Step 3: Implement** — append to `wondershot/simplify.py`:

```python
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
```

- [x] **Step 4: Run to verify pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_simplify.py -v`
Expected: 8 PASS

- [x] **Step 5: Commit**

```bash
git add wondershot/simplify.py tests/test_simplify.py
git commit -m "feat(simplify): region prompt, parse_regions clamping, chat pipeline"
```

---

### Task 4: Editor integration — AI Simplify action + apply_simplify_regions

Mirror `ai_redact` exactly: gate on `ai_configured`, snapshot the base image, run on `_start_ai_job` behind the cancelable progress dialog, then materialize the regions as **objects** inside one undo macro. Region → object mapping: `text` → `RectItem` filled `TEXT_FILL` (gray text-run block); `chrome` → `RectItem` filled with the region's dominant color (palette-matched); `image` → dominant-color fill with a slightly darker 1-px outline so adjacent placeholders stay distinguishable.

**Files:**
- Modify: `wondershot/editor.py` (toolbar in `_build_toolbar` after the redact action ~line 601; new methods next to `ai_redact`/`apply_redact_regions` ~lines 721-764)
- Create: `tests/test_editor_simplify.py`

- [x] **Step 1: Write the failing tests** — create `tests/test_editor_simplify.py`:

```python
"""Editor integration for the AI simplifier (offscreen, no network)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_editor(qapp, w=400, h=300, color="white"):
    from wondershot.editor import EditorWindow
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return EditorWindow(image=img)


def test_apply_simplify_regions_builds_editable_objects(qapp):
    from wondershot.items import RectItem, is_annotation
    from wondershot.simplify import Region, TEXT_FILL
    ed = make_editor(qapp, color="#204060")
    n = ed.apply_simplify_regions([
        Region(QRect(10, 10, 100, 20), "text"),
        Region(QRect(0, 0, 400, 30), "chrome"),
        Region(QRect(50, 100, 80, 60), "image"),
    ])
    assert n == 3
    rects = [i for i in ed.scene.items() if isinstance(i, RectItem)]
    assert len(rects) == 3
    assert all(is_annotation(i) for i in rects)        # editable afterwards
    fills = {i.brush().color().name() for i in rects}
    assert QColor(TEXT_FILL).name() in fills           # text -> gray block
    assert "#204060" in fills                          # chrome -> sampled color
    # non-destructive: the base image is untouched
    assert ed.base_image.pixelColor(15, 15) == QColor("#204060")


def test_apply_simplify_is_one_undo_macro(qapp):
    from wondershot.items import RectItem
    from wondershot.simplify import Region
    ed = make_editor(qapp)
    ed.apply_simplify_regions([Region(QRect(10, 10, 100, 20), "text"),
                               Region(QRect(10, 60, 100, 20), "chrome")])
    ed.undo_stack.undo()                               # ONE undo clears all
    assert [i for i in ed.scene.items() if isinstance(i, RectItem)] == []
    ed.undo_stack.redo()
    assert len([i for i in ed.scene.items()
                if isinstance(i, RectItem)]) == 2


def test_apply_simplify_clamps_and_skips_tiny(qapp):
    from wondershot.simplify import Region
    ed = make_editor(qapp, 400, 300)
    n = ed.apply_simplify_regions([
        Region(QRect(390, 290, 100, 100), "chrome"),   # clamped, kept
        Region(QRect(0, 0, 2, 2), "text"),             # degenerate -> skipped
        Region(QRect(500, 500, 50, 50), "image"),      # off-canvas -> skipped
    ])
    assert n == 1


def test_simplify_action_on_toolbar_and_unconfigured_guard(qapp):
    ed = make_editor(qapp)
    assert ed.simplify_action.text() == "AI Simplify"
    ed.ai_simplify()    # settings is None -> guard fires, no job starts
    assert "Settings" in ed.statusBar().currentMessage()
    assert not hasattr(ed, "_ai_job")    # _start_ai_job never ran


def test_simplify_done_error_path_keeps_scene_clean(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from wondershot.items import RectItem
    ed = make_editor(qapp)
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: QMessageBox.Ok)
    ed._simplify_done(None, "boom")
    assert [i for i in ed.scene.items() if isinstance(i, RectItem)] == []
```

- [x] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_simplify.py -v`
Expected: FAIL — `AttributeError: 'EditorWindow' object has no attribute 'apply_simplify_regions'` (and `simplify_action`)

- [x] **Step 3: Implement** — in `wondershot/editor.py`:

(a) In `_build_toolbar`, directly after `tb.addAction(self.redact_action)`:

```python
        self.simplify_action = self._act("AI Simplify", "image-x-generic")
        self.simplify_action.setToolTip(
            "Replace UI regions with clean editable blocks (Settings → AI)")
        self.simplify_action.triggered.connect(self.ai_simplify)
        tb.addAction(self.simplify_action)
```

(b) In the `# -- AI actions` section, after `apply_redact_regions`:

```python
    def ai_simplify(self) -> None:
        from .aiclient import ai_configured
        from . import simplify
        if not (self.settings and ai_configured(self.settings)):
            self.statusBar().showMessage(
                "Configure an AI endpoint in Settings → AI first", 6000)
            return
        s = self.settings
        image = self.base_image.copy()  # snapshot off the GUI thread's state
        endpoint, key, model = s.ai_endpoint, s.ai_api_key, s.ai_model
        self._start_ai_job(
            lambda: simplify.simplify_regions(image, endpoint, key, model),
            "Simplifying UI…", self._simplify_done)

    def _simplify_done(self, regions, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Wondershot",
                                f"AI Simplify failed: {error}")
            return
        self.apply_simplify_regions(regions or [])

    def apply_simplify_regions(self, regions) -> int:
        """Region -> filled RectItem objects, one undo macro, never
        destructive: text runs get a neutral gray block, chrome gets the
        region's dominant color, images get the dominant color plus a
        slightly darker outline. Everything stays editable afterwards."""
        from . import simplify
        img_rect = QRect(0, 0, self.base_image.width(),
                         self.base_image.height())
        kept: list[tuple[QRect, str]] = []
        for reg in regions:
            c = QRect(reg.rect).intersected(img_rect)
            if c.width() >= 4 and c.height() >= 4:
                kept.append((c, reg.kind))
        if kept:
            self.undo_stack.beginMacro("AI simplify")
            try:
                for c, kind in kept:
                    if kind == "text":
                        fill = QColor(simplify.TEXT_FILL)
                    else:
                        fill = simplify.dominant_color(self.base_image, c)
                    pen = fill.darker(115) if kind == "image" else QColor(fill)
                    item = RectItem(QRectF(c), pen, 1, fill=fill)
                    self.undo_stack.push(
                        AddItemCommand(self, item, "AI simplify"))
            finally:
                self.undo_stack.endMacro()
        msg = (f"AI Simplify: replaced {len(kept)} region(s) — every block "
               "is editable; Ctrl+Z undoes them all" if kept
               else "AI Simplify: no regions found")
        self.statusBar().showMessage(msg, 8000)
        return len(kept)
```

- [x] **Step 4: Run to verify pass** (plus the existing editor suites — same file touched)

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_simplify.py tests/test_editor.py tests/test_editor_ai.py tests/test_editor_sidecar.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add wondershot/editor.py tests/test_editor_simplify.py
git commit -m "feat(editor): AI Simplify action — regions become editable filled rects, one undo macro"
```

---

### Task 5: Style-change undo (StyleCommand)

Today `_apply_to_selection` mutates items directly and calls `undo_stack.resetClean()` — restyles are not undoable. Replace with a `StyleCommand` that snapshots each item's style (via the existing `get_style`) before applying. Consecutive identical-shape changes merge (spinbox arrow-hold would otherwise flood the stack).

**Files:**
- Modify: `wondershot/editor.py` (`StyleCommand` next to `GripCommand` ~line 209; `_apply_to_selection` ~line 956)
- Create: `tests/test_editor_backlog.py`

- [x] **Step 1: Write the failing tests** — create `tests/test_editor_backlog.py`:

```python
"""Editor backlog: style undo, text alignment, blur tool, step renumbering."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_editor(qapp, w=400, h=300, color="white"):
    from wondershot.editor import EditorWindow
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return EditorWindow(image=img)


def _add_selected_rect(ed, color="#ff0000", width=4):
    from wondershot.items import RectItem
    item = RectItem(QRectF(10, 10, 100, 60), QColor(color), width)
    ed.scene.addItem(item)
    ed.scene.clearSelection()
    item.setSelected(True)
    return item


def test_style_change_is_undoable(qapp):
    ed = make_editor(qapp)
    item = _add_selected_rect(ed, "#ff0000", 4)
    ed._apply_to_selection(color=QColor("#00ff00"), width=9)
    assert item.pen().color() == QColor("#00ff00")
    assert item.pen().width() == 9
    assert not ed.undo_stack.isClean()
    ed.undo_stack.undo()
    assert item.pen().color() == QColor("#ff0000")
    assert item.pen().width() == 4
    ed.undo_stack.redo()
    assert item.pen().color() == QColor("#00ff00")


def test_consecutive_same_kind_style_changes_merge(qapp):
    ed = make_editor(qapp)
    item = _add_selected_rect(ed, "#ff0000", 4)
    before = ed.undo_stack.count()
    for w in (5, 6, 7):                  # spinbox arrow-hold simulation
        ed._apply_to_selection(width=w)
    assert ed.undo_stack.count() == before + 1   # merged into one entry
    ed.undo_stack.undo()
    assert item.pen().width() == 4               # straight back to the start


def test_text_font_size_change_is_undoable(qapp):
    from wondershot.items import TextItem
    ed = make_editor(qapp)
    t = TextItem(QPointF(5, 5), QColor("#112233"), point_size=18)
    t.setPlainText("hi")
    ed.scene.addItem(t)
    ed.scene.clearSelection()
    t.setSelected(True)
    ed._apply_to_selection(font_size=30)
    assert t.font().pointSize() == 30
    ed.undo_stack.undo()
    assert t.font().pointSize() == 18
```

- [x] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_backlog.py -v`
Expected: FAIL — undo() does not restore the old style (current code mutates directly), and the merge test fails on stack count

- [x] **Step 3: Implement** — in `wondershot/editor.py`:

(a) Add after `GripCommand`:

```python
class StyleCommand(QUndoCommand):
    """Undo entry for a properties-panel restyle (color / stroke / font
    size / alignment). The before-state per item comes from get_style,
    whose keys are exactly apply_style's kwargs. Consecutive changes to
    the same items with the same kwarg shape merge (spinbox arrow-hold)."""

    _ID = 0xE57         # arbitrary, shared by all StyleCommands

    def __init__(self, editor: "EditorWindow", items, kwargs: dict):
        super().__init__("restyle")
        from .items import get_style
        self.editor = editor
        self.items = list(items)
        self.kwargs = dict(kwargs)
        self.before = [dict(get_style(i)) for i in self.items]

    def id(self) -> int:  # noqa: A003
        return self._ID

    def mergeWith(self, other) -> bool:  # noqa: N802
        if (other.items == self.items
                and set(other.kwargs) == set(self.kwargs)):
            self.kwargs = dict(other.kwargs)
            return True
        return False

    def redo(self):
        from .items import apply_style
        for it in self.items:
            apply_style(it, **self.kwargs)

    def undo(self):
        from .items import apply_style
        for it, b in zip(self.items, self.before):
            apply_style(it, **b)
```

(b) Replace `_apply_to_selection`:

```python
    def _apply_to_selection(self, **kwargs) -> None:
        items = self._selected_annotations()
        if not items:
            return
        self.undo_stack.push(StyleCommand(self, items, kwargs))
```

(`resetClean()` is gone: pushing a real command makes the stack dirty, which is what the old call faked.)

**Pitfall to verify while implementing:** `get_style` for a `TextItem` returns `{"color", "font_size"}` and for shapes `{"color", "width"}` — every key is a valid `apply_style` kwarg, so `apply_style(it, **b)` restores cleanly. When Task 6 adds `"align"`, it joins both dicts symmetrically; do not special-case.

- [x] **Step 4: Run to verify pass** (plus the editor suites — `_apply_to_selection` callers unchanged)

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_backlog.py tests/test_editor.py tests/test_editor_sidecar.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add wondershot/editor.py tests/test_editor_backlog.py
git commit -m "feat(editor): properties-panel restyles go on the undo stack (merging StyleCommand)"
```

---

### Task 6: Text alignment — TextItem property + serialization + panel buttons

`TextItem` gets `set_alignment("left"|"center"|"right")` via the document's default `QTextOption` (alignment is only *visible* when a `textWidth` is set — auto-width labels hug their text; that's correct Qt behavior and matches boxed text being the use case). Serialized as `"align"`, defaulted `"left"` so old sidecars are untouched. Panel: three exclusive buttons on the text row, undoable because they route through Task 5's `StyleCommand`.

**Files:**
- Modify: `wondershot/items.py` (TextItem ~lines 299-348; `get_style`/`apply_style` ~lines 546-594)
- Modify: `wondershot/editor.py` (`_build_panel` ~line 846, `_update_panel_rows`, `_sync_panel`)
- Test: `tests/test_items_serialize.py`, `tests/test_editor_backlog.py`

- [x] **Step 1: Write the failing serialization tests** — append to `tests/test_items_serialize.py`:

```python
def test_text_alignment_roundtrip(qapp):
    from wondershot.items import TextItem
    from PySide6.QtCore import Qt
    item = TextItem(QPointF(0, 0), QColor("red"))
    item.setPlainText("centered")
    item.setTextWidth(200.0)
    item.set_alignment("center")
    d = item.to_dict()
    assert d["align"] == "center"
    out = roundtrip(item)
    assert out.alignment() == "center"
    assert out.document().defaultTextOption().alignment() \
        & Qt.AlignHCenter


def test_text_alignment_defaults_left_for_old_sidecars(qapp):
    from wondershot.items import TextItem, item_from_dict
    item = TextItem(QPointF(0, 0), QColor("red"))
    assert item.alignment() == "left"
    d = item.to_dict()
    del d["align"]                       # sidecar written by an older build
    out = item_from_dict(d)
    assert out.alignment() == "left"
```

- [x] **Step 2: Write the failing editor tests** — append to `tests/test_editor_backlog.py`:

```python
def _add_selected_text(ed, text="hello"):
    from wondershot.items import TextItem
    t = TextItem(QPointF(5, 5), QColor("#112233"), point_size=18)
    t.setPlainText(text)
    t.setTextWidth(150.0)
    ed.scene.addItem(t)
    ed.scene.clearSelection()
    t.setSelected(True)
    return t


def test_alignment_buttons_exist_and_apply_undoably(qapp):
    ed = make_editor(qapp)
    t = _add_selected_text(ed)
    assert set(ed.align_buttons) == {"left", "center", "right"}
    ed.align_buttons["right"].click()
    assert t.alignment() == "right"
    ed.undo_stack.undo()
    assert t.alignment() == "left"


def test_panel_sync_reflects_selected_text_alignment(qapp):
    ed = make_editor(qapp)
    t = _add_selected_text(ed)
    t.set_alignment("center")
    ed._sync_panel()
    assert ed.align_buttons["center"].isChecked()
    # syncing must NOT push an undo command (guarded by _syncing_panel)
    n = ed.undo_stack.count()
    ed._sync_panel()
    assert ed.undo_stack.count() == n
```

- [x] **Step 3: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_items_serialize.py tests/test_editor_backlog.py -v -k align`
Expected: FAIL — `AttributeError: 'TextItem' object has no attribute 'set_alignment'` / no `align_buttons`

- [x] **Step 4: Implement items.py** —

(a) Module-level, near the top of `TextItem`:

```python
_TEXT_ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
               "right": Qt.AlignRight}
```

(b) In `TextItem.__init__`, after `self.setFont(font)`:

```python
        self._align = "left"
```

(c) New methods on `TextItem`:

```python
    def set_alignment(self, align: str) -> None:
        """left / center / right — visible once the item has a textWidth
        (auto-width labels hug their text, so there is nothing to align)."""
        self._align = align if align in _TEXT_ALIGN else "left"
        opt = self.document().defaultTextOption()
        opt.setAlignment(_TEXT_ALIGN[self._align])
        self.document().setDefaultTextOption(opt)
        self.update()

    def alignment(self) -> str:
        return self._align
```

(d) `TextItem.to_dict` grows `"align": self._align` (add to the returned dict), and `from_dict` gains, right before `_apply_transform(item, d)`:

```python
        item.set_alignment(d.get("align", "left"))
```

(e) `get_style` — in the `TextItem` branch add:

```python
        style["align"] = item.alignment()
```

(f) `apply_style` — new signature and TextItem branch:

```python
def apply_style(item, color: QColor | None = None, width: int | None = None,
                font_size: int | None = None,
                align: str | None = None) -> None:
```

and inside the `TextItem` branch, after the font-size block:

```python
        if align is not None:
            item.set_alignment(align)
```

- [x] **Step 5: Implement editor.py panel** — in `_build_panel`, after the `font_spin` row:

```python
        from PySide6.QtWidgets import QHBoxLayout, QToolButton
        align_w = QWidget(w)
        align_lay = QHBoxLayout(align_w)
        align_lay.setContentsMargins(0, 0, 0, 0)
        self.align_buttons: dict[str, QToolButton] = {}
        for name, icon in (("left", "format-justify-left"),
                           ("center", "format-justify-center"),
                           ("right", "format-justify-right")):
            b = QToolButton(align_w)
            b.setIcon(QIcon.fromTheme(icon))
            b.setToolTip(f"Align {name}")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _=False, a=name: self._align_changed(a))
            align_lay.addWidget(b)
            self.align_buttons[name] = b
        self.align_buttons["left"].setChecked(True)
        self._align_widget = align_w
        form.addRow("Align", align_w)
```

(`QWidget` is already imported inside `_build_panel`; `QIcon` is a module-level import.)

New handler next to `_font_changed`:

```python
    def _align_changed(self, align: str) -> None:
        if self._syncing_panel:
            return
        self._apply_to_selection(align=align)
```

In `_update_panel_rows`, after the `font_spin` line:

```python
        self._panel_form.setRowVisible(self._align_widget, text)
```

In `_sync_panel`, inside the `try:` block after the `font_size` case:

```python
            if "align" in style:
                self.align_buttons[style["align"]].setChecked(True)
```

- [x] **Step 6: Run to verify pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_items_serialize.py tests/test_editor_backlog.py tests/test_editor.py tests/test_editor_sidecar.py -v`
Expected: ALL PASS

- [x] **Step 7: Commit**

```bash
git add wondershot/items.py wondershot/editor.py tests/test_items_serialize.py tests/test_editor_backlog.py
git commit -m "feat(editor): text alignment — serialized, panel buttons, undoable via StyleCommand"
```

---

### Task 7: imageops.blurred_patch (gaussian region blur)

Counterpart of `pixelated_patch`: a gaussian-blurred copy of just `rect`. Implementation renders through `QGraphicsBlurEffect` on a throwaway offscreen `QGraphicsScene` (works headless; needs a `QApplication`, which both the editor and the test fixture provide — keep the widget imports local so the module import stays pure). The source region is padded by the radius before blurring and cropped after, so edge pixels blur against real neighbors instead of transparency (no darkened halo).

**Files:**
- Modify: `wondershot/imageops.py`
- Test: `tests/test_imageops.py`

- [x] **Step 1: Upgrade the file's app fixture.** `tests/test_imageops.py` has an autouse session fixture that creates a `QGuiApplication` — but `blurred_patch` renders through `QGraphicsScene`, which needs a full **`QApplication`** (a `QGuiApplication` subclass, so existing tests are unaffected; when other suites already created a `QApplication`, `instance()` returns it either way). Replace the existing fixture body in `tests/test_imageops.py`:

```python
@pytest.fixture(scope="session", autouse=True)
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
```

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_imageops.py -v` — Expected: ALL PASS (pure fixture widening, no behavior change).

- [x] **Step 2: Write the failing tests** — append to `tests/test_imageops.py` (it already imports `pytest`, `QRect`, `QColor`, `QImage` at the top):

```python
def _half_and_half(w=120, h=80):
    from PySide6.QtGui import QPainter
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("black"))
    p = QPainter(img)
    p.fillRect(w // 2, 0, w // 2, h, QColor("white"))
    p.end()
    return img


def test_blurred_patch_softens_the_boundary(qapp):
    from wondershot.imageops import blurred_patch
    img = _half_and_half()
    r = QRect(30, 10, 60, 60)            # straddles the black/white edge
    patch = blurred_patch(img, r, radius=10)
    assert patch.size() == r.size()
    edge = patch.pixelColor(30, 30)      # on the boundary (x=60 in image)
    assert 40 < edge.red() < 215         # blended, neither pure b nor w
    far = patch.pixelColor(2, 30)        # deep in the black half
    assert far.red() < 40                # interior barely affected


def test_blurred_patch_clamps_and_empty(qapp):
    from wondershot.imageops import blurred_patch
    img = _half_and_half()
    assert blurred_patch(img, QRect(500, 500, 10, 10)).isNull()
    patch = blurred_patch(img, QRect(110, 70, 50, 50), radius=6)
    assert patch.size() == QRect(110, 70, 50, 50).intersected(
        img.rect()).size()
```

- [x] **Step 3: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_imageops.py -v -k blurred`
Expected: FAIL — `ImportError: cannot import name 'blurred_patch'`

- [x] **Step 4: Implement** — append to `wondershot/imageops.py`:

```python
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
        QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene,
    )
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
```

- [x] **Step 5: Run to verify pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_imageops.py -v`
Expected: ALL PASS

- [x] **Step 6: Commit**

```bash
git add wondershot/imageops.py tests/test_imageops.py
git commit -m "feat(imageops): blurred_patch — gaussian region blur via offscreen QGraphicsBlurEffect"
```

---

### Task 8: GaussianBlurItem (items.py + serialization)

A soft sibling of `PixelateItem` with identical move/resize/serialize behavior. First a tiny refactor: extract the patch renderer out of `PixelateItem._regen` into an overridable `_patch_for` hook, then subclass. Subclassing means `isinstance(x, PixelateItem)` stays true for blur items, which gives the editor's grip wiring (Task 9) corner handles for free.

**Files:**
- Modify: `wondershot/items.py` (PixelateItem `_regen` ~line 638; new class after it; `item_from_dict` ~line 669)
- Test: `tests/test_items_serialize.py`

- [x] **Step 1: Write the failing tests** — append to `tests/test_items_serialize.py`:

```python
def test_blur_roundtrip_uses_base_provider(qapp):
    from PySide6.QtGui import QImage
    from wondershot.items import GaussianBlurItem, PixelateItem
    base = QImage(200, 150, QImage.Format_ARGB32_Premultiplied)
    base.fill(QColor("orange"))
    item = GaussianBlurItem(lambda: base, QRectF(10.0, 12.0, 80.0, 40.0),
                            radius=7)
    assert isinstance(item, PixelateItem)   # editor grips ride on this
    d = item.to_dict()
    assert d["type"] == "blur"
    assert d["radius"] == 7
    out = roundtrip(item, base_provider=lambda: base)
    assert isinstance(out, GaussianBlurItem)
    assert out.rect() == QRectF(10.0, 12.0, 80.0, 40.0)
    assert out._radius == 7
    assert out._patch is not None, "patch must regenerate from the provider"


def test_blur_without_provider_is_skipped(qapp):
    from wondershot.items import item_from_dict
    d = {"type": "blur", "rect": [0, 0, 10, 10], "radius": 12,
         "pos": [0, 0], "rotation": 0.0, "origin": [0, 0]}
    assert item_from_dict(d) is None
```

- [x] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_items_serialize.py -v -k blur`
Expected: FAIL — `ImportError: cannot import name 'GaussianBlurItem'`

- [x] **Step 3: Refactor PixelateItem._regen** — replace it with:

```python
    def _regen(self) -> None:
        base = self._base_provider()
        if base is None or base.isNull():
            self._patch = None
            return
        scene_rect = self.mapRectToScene(self._rect.normalized()).toRect()
        patch = self._patch_for(base, scene_rect)
        self._patch = None if patch is None or patch.isNull() else patch

    def _patch_for(self, base, scene_rect):
        """Render the region patch — subclasses swap the filter."""
        from . import imageops
        return imageops.pixelated_patch(base, scene_rect, self._block)
```

- [x] **Step 4: Add GaussianBlurItem** — after `PixelateItem`:

```python
class GaussianBlurItem(PixelateItem):
    """Live gaussian blur of the base image under it — the soft variant
    of PixelateItem; identical move/resize/serialize behavior."""

    # Class-attribute default: PySide forbids touching self before the
    # base __init__, and super().__init__ already runs _regen -> needs
    # _radius readable. Non-default radii regenerate once more below.
    _radius = 12

    def __init__(self, base_provider, rect: QRectF, radius: int = 12):
        super().__init__(base_provider, rect)
        if int(radius) != self._radius:
            self._radius = int(radius)
            self._regen()
            self.update()

    def _patch_for(self, base, scene_rect):
        from . import imageops
        return imageops.blurred_patch(base, scene_rect, self._radius)

    def to_dict(self) -> dict:
        r = self._rect
        return {"type": "blur",
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "radius": self._radius, **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict, base_provider) -> "GaussianBlurItem":
        r = d["rect"]
        item = cls(base_provider, QRectF(r[0], r[1], r[2], r[3]),
                   radius=int(d.get("radius", 12)))
        _apply_transform(item, d)
        return item
```

- [x] **Step 5: Dispatch "blur" in item_from_dict** — replace the pixelate branch:

```python
    t = d.get("type")
    if t in ("pixelate", "blur"):
        if base_provider is None:
            return None
        cls = PixelateItem if t == "pixelate" else GaussianBlurItem
        return cls.from_dict(d, base_provider)
```

- [x] **Step 6: Run to verify pass** (whole serialize file: pixelate refactor must not regress)

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_items_serialize.py tests/test_editor_sidecar.py -v`
Expected: ALL PASS

- [x] **Step 7: Commit**

```bash
git add wondershot/items.py tests/test_items_serialize.py
git commit -m "feat(items): GaussianBlurItem — serializable gaussian sibling of PixelateItem"
```

---

### Task 9: Blur tool in the editor toolbar

`Tool.BLUR` drives the same drag-a-rectangle overlay flow as pixelate; corner grips come free via the `isinstance(t, PixelateItem)` branch in `_handle_positions`.

**Files:**
- Modify: `wondershot/editor.py` (Tool enum ~line 72; items import ~line 39; toolbar `tools` list ~line 548; `set_tool` hints ~line 1015; `begin_draw`/`end_draw` overlay branches ~lines 1075/1115; new `_apply_blur` next to `_apply_pixelate` ~line 1330)
- Test: `tests/test_editor_backlog.py`

- [x] **Step 1: Write the failing tests** — append to `tests/test_editor_backlog.py`:

```python
def test_blur_tool_draws_a_blur_item(qapp):
    from wondershot.editor import Tool
    from wondershot.items import GaussianBlurItem
    ed = make_editor(qapp)
    ed.set_tool(Tool.BLUR)
    ed.begin_draw(QPointF(20, 20))
    ed.update_draw(QPointF(120, 90))
    ed.end_draw(QPointF(120, 90))
    blurs = [i for i in ed.scene.items() if isinstance(i, GaussianBlurItem)]
    assert len(blurs) == 1
    assert blurs[0].rect() == QRectF(20, 20, 100, 70)
    ed.undo_stack.undo()
    assert [i for i in ed.scene.items()
            if isinstance(i, GaussianBlurItem)] == []


def test_blur_tool_on_toolbar_with_shortcut(qapp):
    from wondershot.editor import Tool
    ed = make_editor(qapp)
    act = ed._tool_actions[Tool.BLUR]
    assert act.text() == "Blur"
    assert act.shortcut().toString() == "B"


def test_blur_item_gets_corner_grips(qapp):
    from wondershot.items import GaussianBlurItem
    ed = make_editor(qapp)
    item = GaussianBlurItem(lambda: ed.base_image, QRectF(10, 10, 60, 40))
    ed.scene.addItem(item)
    item.setSelected(True)
    roles = {h.role for h in ed._handles}
    assert roles == {"tl", "tr", "bl", "br"}
```

- [x] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_backlog.py -v -k blur`
Expected: FAIL — `AttributeError: BLUR` on the Tool enum

- [x] **Step 3: Implement** — in `wondershot/editor.py`:

(a) Tool enum, after `PIXELATE`:

```python
    BLUR = "blur"
```

(b) Add `GaussianBlurItem` to the `from .items import (...)` block.

(c) Toolbar `tools` list, after the Pixelate row:

```python
            (Tool.BLUR, "Blur", "blurfx", "B"),
```

(d) `set_tool` hints dict:

```python
            Tool.BLUR: "Drag a rectangle to blur",
```

(e) `begin_draw`: extend the overlay branch tuple to
`(Tool.TEXT, Tool.PIXELATE, Tool.BLUR, Tool.CROP, Tool.CUTOUT_V, Tool.CUTOUT_H)`.

(f) `end_draw`: extend the same tuple in the second branch, and change the dispatch to:

```python
            if t == Tool.PIXELATE:
                self._apply_pixelate(rect)
            elif t == Tool.BLUR:
                self._apply_blur(rect)
            elif t == Tool.CROP:
                self._apply_crop(rect)
            else:
                self._apply_cutout(t, rect)
```

(g) New method after `_apply_pixelate`:

```python
    def _apply_blur(self, rect: QRect) -> None:
        img = self.base_image
        clamped = rect.intersected(QRect(0, 0, img.width(), img.height()))
        if clamped.width() < 4 or clamped.height() < 4:
            return
        item = GaussianBlurItem(lambda: self.base_image, QRectF(clamped))
        self.undo_stack.push(AddItemCommand(self, item, "blur"))
        self._select_only(item)
```

(No `_handle_positions` change needed — `GaussianBlurItem` is a `PixelateItem`; the third test proves it.)

- [x] **Step 4: Run to verify pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_backlog.py tests/test_editor.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add wondershot/editor.py tests/test_editor_backlog.py
git commit -m "feat(editor): Blur tool — live gaussian region blur alongside Pixelate"
```

---

### Task 10: Step renumbering — drag one badge onto another to swap

`StepItem` is a plain movable item with no custom drag code; the swap gesture is detected in the editor, not the item. `CanvasView` records the pressed item's start position on mouse-press and asks the editor to resolve the gesture on release: if a `StepItem` was dragged onto another `StepItem`, push a `SwapStepNumbersCommand` that swaps the two numbers and snaps the dragged badge back to its start (the drop is a renumber gesture, not a move). The editor-side hooks (`note_step_press`/`finish_step_drag`) are headless-testable; only the two one-line view calls are GUI glue.

**Files:**
- Modify: `wondershot/editor.py` (new command after `StyleCommand`; hooks on `EditorWindow`; two calls in `CanvasView.mousePressEvent`/`mouseReleaseEvent` ~lines 269-303; `self._step_drag = None` in `EditorWindow.__init__` near `self._adjusting = False`)
- Test: `tests/test_editor_backlog.py`

- [x] **Step 1: Write the failing tests** — append to `tests/test_editor_backlog.py`:

```python
def _two_steps(ed):
    from wondershot.items import StepItem
    a = StepItem(QPointF(50, 50), 1, QColor("#e3242b"))
    b = StepItem(QPointF(200, 200), 2, QColor("#e3242b"))
    ed.scene.addItem(a)
    ed.scene.addItem(b)
    return a, b


def test_dropping_step_on_step_swaps_numbers_and_snaps_back(qapp):
    ed = make_editor(qapp)
    a, b = _two_steps(ed)
    ed.note_step_press(a)
    a.setPos(b.pos())                    # simulate the drag
    ed.finish_step_drag()
    assert (a.number, b.number) == (2, 1)
    assert a.pos() == QPointF(50, 50)    # dragged badge snapped back
    assert b.pos() == QPointF(200, 200)
    ed.undo_stack.undo()
    assert (a.number, b.number) == (1, 2)
    assert a.pos() == QPointF(50, 50)
    ed.undo_stack.redo()
    assert (a.number, b.number) == (2, 1)


def test_step_drag_to_empty_space_is_a_plain_move(qapp):
    ed = make_editor(qapp)
    a, b = _two_steps(ed)
    n = ed.undo_stack.count()
    ed.note_step_press(a)
    a.setPos(QPointF(120, 30))           # nowhere near b
    ed.finish_step_drag()
    assert (a.number, b.number) == (1, 2)
    assert a.pos() == QPointF(120, 30)   # the move sticks
    assert ed.undo_stack.count() == n    # no swap command pushed


def test_non_step_press_is_ignored(qapp):
    from wondershot.items import RectItem
    ed = make_editor(qapp)
    r = RectItem(QRectF(0, 0, 30, 30), QColor("red"), 2)
    ed.scene.addItem(r)
    ed.note_step_press(r)                # not a StepItem -> no-op
    ed.note_step_press(None)
    ed.finish_step_drag()                # must not raise
```

- [x] **Step 2: Run to verify failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_backlog.py -v -k step`
Expected: FAIL — `AttributeError: 'EditorWindow' object has no attribute 'note_step_press'`

- [x] **Step 3: Implement** — in `wondershot/editor.py`:

(a) New command after `StyleCommand`:

```python
class SwapStepNumbersCommand(QUndoCommand):
    """Drop one step badge onto another: the two numbers swap and the
    dragged badge snaps back to where it started — the gesture is a
    renumber, not a move (otherwise two badges would overlap)."""

    def __init__(self, editor: "EditorWindow", dragged, target,
                 dragged_start: QPointF):
        super().__init__("swap step numbers")
        self.editor = editor
        self.a, self.b = dragged, target
        self.a_start = QPointF(dragged_start)

    def redo(self):
        self.a.number, self.b.number = self.b.number, self.a.number
        self.a.setPos(self.a_start)
        self.a.update()
        self.b.update()

    def undo(self):
        self.a.number, self.b.number = self.b.number, self.a.number
        self.a.setPos(self.a_start)
        self.a.update()
        self.b.update()
```

(b) In `EditorWindow.__init__`, next to `self._adjusting = False`:

```python
        self._step_drag = None  # (StepItem, press pos) during a badge drag
```

(c) New methods on `EditorWindow` (put them after `delete_selected`):

```python
    def note_step_press(self, item) -> None:
        """Called by the view on mouse-press with the item under the
        cursor; remembers a StepItem's start position for the
        drop-to-swap gesture."""
        self._step_drag = ((item, QPointF(item.pos()))
                           if isinstance(item, StepItem) else None)

    def finish_step_drag(self) -> None:
        """Called by the view on mouse-release: if the pressed badge
        moved onto another badge, swap their numbers (undoable)."""
        drag, self._step_drag = self._step_drag, None
        if drag is None:
            return
        item, start = drag
        if item.scene() is not self.scene or item.pos() == start:
            return
        targets = [i for i in item.collidingItems()
                   if isinstance(i, StepItem)]
        if not targets:
            return
        target = min(targets, key=lambda t: (t.scenePos()
                                             - item.scenePos()
                                             ).manhattanLength())
        self.undo_stack.push(
            SwapStepNumbersCommand(self, item, target, start))
```

(d) GUI glue in `CanvasView` — **no failing-test step for these two lines** (justification: they only forward real mouse events to the two methods tested above; synthesizing QGraphicsView mouse events offscreen is flaky and adds no coverage beyond the direct-call tests):

In `mousePressEvent`, as the FIRST statement of the method:

```python
        if ev.button() == Qt.LeftButton:
            self.editor.note_step_press(
                self.itemAt(ev.position().toPoint()))
```

In `mouseReleaseEvent`, add `self.editor.finish_step_drag()` immediately after the `super().mouseReleaseEvent(ev)` call in BOTH early-return branches (the `_passthrough` branch and the `SELECT`/non-left branch) — drawing-tool releases never drag an existing badge, so the third path needs nothing:

```python
    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self._passthrough:
            self._passthrough = False
            super().mouseReleaseEvent(ev)
            self.editor.finish_step_drag()
            return
        if self.editor.tool == Tool.SELECT or ev.button() != Qt.LeftButton:
            super().mouseReleaseEvent(ev)
            self.editor.finish_step_drag()
            return
        if self.editor.drawing:
            self.editor.end_draw(self.mapToScene(ev.position().toPoint()))
        ev.accept()
```

- [x] **Step 4: Run to verify pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_editor_backlog.py tests/test_editor.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add wondershot/editor.py tests/test_editor_backlog.py
git commit -m "feat(editor): drag a step badge onto another to swap their numbers (undoable)"
```

---

### Task 11: Suite-wide verification + shared-stub landmine check

GUI-glue/verification task — no new failing test (justification: it adds no behavior; it proves nothing regressed and that the batch-3 settings-stub landmine cannot fire).

**Files:**
- Modify: `ROADMAP.md` (one appended backlog line — shared file, append-only)
- Test stubs only if the grep below finds a problem — then fix per the landmine rule.

- [ ] **Step 1: Confirm no new settings keys are read during widget construction.** Duplicated duck-typed `_Settings`/`_FakeSettings` stubs live in ELEVEN files (verified on main): `tests/test_capture_crop.py`, `tests/test_capture_window_mode.py`, `tests/test_countdown.py`, `tests/test_editor_sidecar.py`, `tests/test_gallery_sidecar.py`, `tests/test_gallery_trash.py`, `tests/test_hide_for_capture.py`, `tests/test_quickbar.py`, `tests/test_record_sync.py`, `tests/test_tray_tooltip.py`, `tests/test_settings_dialog_ai.py`. The grep below is authoritative — if it finds stubs in files not listed here, those count too. Run:

```bash
grep -rln "class _Settings\|class _FakeSettings" tests/
git diff main -- wondershot/ | grep -n "settings\." || true
```

Expected: the only `settings.` reads added by this branch are `s.ai_endpoint`, `s.ai_api_key`, `s.ai_model` inside `ai_simplify` — read *after* a click, behind the `ai_configured` `getattr` guard, never during construction. **If anything else shows up, extend every listed stub before proceeding.**

- [ ] **Step 2: Record the edge-snapping deferral in ROADMAP.md** (shared file — APPEND-ONLY: add one line to the backlog section, never reorder/edit existing lines, so the parallel track 4b can also append without conflict):

```
- Editor: text-box edge snapping (spec batch-4 Track 4a item) — deferred from the simplifier/editor-backlog track; needs a design call on what snaps to what.
```

- [ ] **Step 3: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ -q`
Expected: 277 pre-existing tests + ~25 new ones, ALL PASS, zero skips introduced by this branch.

- [ ] **Step 4: Commit anything outstanding** (the ROADMAP line; plus stub edits if Step 1 forced any):

```bash
git status --short
git add ROADMAP.md && git commit -m "docs(roadmap): note text-box edge-snapping deferral"
# only if the stub check forced edits:
git add tests/ && git commit -m "test: extend settings stubs for new editor keys"
```

---

## Self-Review (performed at write time)

- **Spec coverage:** simplifier (Tasks 2-4: vision LLM → typed regions → editable filled RectItems, single macro, non-destructive, redact-pattern AIJob+dialog ✓); text alignment serialized + panel + undoable (Task 6 ✓); style-change undo (Task 5 ✓); blur variant of pixelate, serializable + toolbar (Tasks 7-9 ✓); step renumbering by badge drop (Task 10 ✓); rotate-cursor polish — already shipped, explicitly no-op ✓; test_items_serialize.py extended in Tasks 1, 6, 8 ✓; shared-stub landmine handled in Task 11 (all 11 stub files listed; grep authoritative) ✓; edge snapping IS in the track 4a brief but is deliberately deferred pending a design call — recorded via a mandatory append-only ROADMAP.md backlog line in Task 11 and flagged for the orchestrator ✓; cross-track boundary (4b's files untouched; shared files append-only) stated in scope notes ✓.
- **Type consistency:** `Region(rect: QRect, kind: str)` used identically in simplify.py, editor, and tests; `apply_style`'s `align` kwarg matches `get_style`'s `"align"` key; `GaussianBlurItem(base_provider, rect, radius)` matches dispatcher and tests; `RectItem(..., fill=...)` keyword used consistently.
- **Placeholder scan:** no TBDs; every code step carries the actual code; the two GUI-glue exemptions (Task 10 step 3d, Task 11) carry explicit justifications.
