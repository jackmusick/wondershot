# Sidecar Persistence (Track 3b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Library images become fully revisitable documents with zero save prompts. The library file stays the flattened, share-ready PNG (drag-out/share unchanged). A per-image sidecar under `<library>/.wondershot/` stores the serialized annotation objects plus a base-image stack, so reopening an image puts every arrow/text/pixelate back on the canvas as a live, editable object — and destructive ops (crop, cut-out, background removal) are undoable on revisit by popping the base stack. Autosave fires silently on editor close, image switch, and app quit for library files; the "Save changes?" prompt survives only for files opened outside the library (`wondershot -e /random/path`). Trash and undo-delete carry the sidecar files along. Images only — video sidecars get a ROADMAP note.

**Architecture:**

- **New `wondershot/sidecar.py`** — pure file plumbing, no widgets. Path helpers (`sidecar_dir`, `sidecar_path`, `base_path`), `is_library_file(path, settings)`, atomic JSON `load`/`save` with a `version` field (unknown versions → `None` → editor falls back to today's flat open), `related_files` (for trash), `rename_files` (for rename).
- **Sidecar layout** (name = full image filename, so `shot.png` and `shot.jpg` never collide):
  - `<dir>/.wondershot/<name>.json` — `{"version": 1, "bases": N, "items": [...], "effects": {...}}`
  - `<dir>/.wondershot/<name>.base.<K>.png` for K in `0..N-1`. **K=0 is the original capture; top of stack (N-1) is the current working base.** Bases are always PNG (lossless, alpha) regardless of the library file's extension.
  - `effects` is a **write-only record** of the effect settings at save time ({rounded, corner_radius, fade, fade_height}) — effects remain settings-driven and are re-rendered from current settings on open, exactly as today. Recorded for future format use only.
- **`items.py`** — every annotation class gets `to_dict()` / `from_dict()` (pure, headless-testable; this is the bulk of the TDD surface) plus a module-level `item_from_dict(d, base_provider=None)` dispatcher. `PixelateItem.from_dict` takes the `base_provider` callable (the editor passes `lambda: self.base_image`, same as live drawing). Geometry/rotation round-trips exactly: Qt qreals are doubles, Python `json` round-trips doubles exactly.
- **Editor open** (`EditorWindow.load` + `__init__`-from-path): sidecar present → load top-of-stack base instead of the flattened library PNG, reconstruct items in stacking order, restore `step_counter`, then push one `HistoryBaseCommand` per stack transition (first-`redo` is a no-op, GripCommand pattern) so Ctrl+Z walks the base stack back to the original. No sidecar → exactly today's behavior; sidecar appears on first save (migration story).
- **Autosave:** `maybe_save()` short-circuits for library files — silently `save()` instead of prompting. `save()` writes the flattened PNG (unchanged) **and** the sidecar. App quit: `GalleryWindow.really_quit` now closes standalone editor windows first (their `closeEvent → maybe_save` autosaves them).
- **Destructive ops push pre-op bases:** `_apply_crop`/`_apply_cutout` record the pre-op **flattened** image (so annotations folded by the crop aren't visually lost on revisit-undo); `_bg_done` records the pre-op **base** (annotations stay live through bg-removal, as today). Pushes are recorded with the undo-stack index at push time; at save, pushes that were undone in-session are dropped. At save, if the current base equals an *earlier* stack entry (user revisit-undid), the stack truncates above it and orphan base files are deleted.
- **Gallery:** trash stages sidecar files in the same undo batch; undo-delete recreates `.wondershot/` and restores them; rename moves them. The library scan needs **no change** — `os.listdir` is non-recursive and `.wondershot` itself has no image extension — but a regression test pins that.

**Tech Stack:** Python 3.11+, PySide6 (Qt 6), pytest, stdlib `json`/`glob`/`shutil`. All tests run with `QT_QPA_PLATFORM=offscreen`.

**Execution environment:** Work in a git worktree branched from `main`:

```bash
git -C /home/jack/GitHub/grabbit worktree add /home/jack/GitHub/grabbit-wt/sidecar -b feat/sidecar-persistence main
cd /home/jack/GitHub/grabbit-wt/sidecar
python -m venv .venv
.venv/bin/pip install -e ".[spike]" pytest   # spike extra pulls numpy — needed for test collection
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q   # 186 green before you start
```

All test commands below assume cwd `/home/jack/GitHub/grabbit-wt/sidecar` and the `QT_QPA_PLATFORM=offscreen` env var.

**Cross-track file safety (batch 3 runs in parallel worktrees):** this track owns `items.py`, `editor.py`, `gallery.py`, and the new `sidecar.py`. It must NOT touch `record.py`, `app.py`, or `capture_window.py` (track 3a) nor `video.py` (track 3c), and it touches neither `settings.py` nor `settings_dialog.py` (both shared files that 3a/3c may edit). The one shared file this track edits is `ROADMAP.md` (Task 7): track 3a also writes ROADMAP notes (pause/resume findings, region-recording note). Confine Task 7's edits to the two new bullets shown (Editor list + Video list in "Working today"), append-only — expect a trivial merge conflict there and resolve by keeping both tracks' bullets. Note for 3a's merger: `GalleryWindow.really_quit` (called from `app.py`) keeps its signature and external behavior — it just closes standalone editor windows first.

---

## File Structure

```
wondershot/
  items.py                    # MODIFIED: to_dict/from_dict on every item class + item_from_dict dispatcher
  sidecar.py                  # NEW: sidecar paths, JSON I/O, related_files, rename_files, is_library_file
  editor.py                   # MODIFIED: HistoryBaseCommand, sidecar-aware load/save, autosave maybe_save,
                              #           _record_base_push hooks in crop/cutout/bg-remove
  gallery.py                  # MODIFIED: _trash_paths/_undo_delete/_rename_selected carry sidecar files,
                              #           really_quit closes standalone editors
tests/
  test_items_serialize.py     # NEW: pure round-trip tests (most of the TDD surface)
  test_sidecar.py             # NEW: path/JSON/version/related/rename tests
  test_editor_sidecar.py      # NEW: editor open/save/autosave/base-stack integration
  test_gallery_sidecar.py     # NEW: trash/undo/rename/scan/quit integration
ROADMAP.md                    # MODIFIED: video-sidecar note
```

Key existing anchors (verified on main):

- `wondershot/items.py` — classes `ArrowItem` (`_p1/_p2/_color/_width`), `LineItem` (`_p1/_p2`, style on `pen()`), `RectItem`/`EllipseItem` (style on `pen()`), `HighlightItem` (color on `brush()` with alpha 90), `FreehandItem` (path of MoveTo+LineTo elements), `TextItem`, `StepItem` (`number`, `radius`, `_color`), `PixelateItem` (`_base_provider`, `_rect`, `_block`), helpers `_mark`, `is_annotation`, `get_style`/`apply_style` at module level.
- `wondershot/editor.py:128` `FlattenCommand`, `:152` `SetBaseImageCommand`, `:172` `GripCommand` (the `self._first = True` first-redo-no-op pattern), `:332` `load()`, `:361` `maybe_save()`, `:383` `set_base_image()`, `:1227` `_apply_crop`, `:1231` `_apply_cutout`, `:663` `_bg_done`, `:1255` `save()`, `:1289` `closeEvent`.
- `wondershot/gallery.py:483` `_list_library` (non-recursive `os.listdir`, extension-filtered), `:771` `open_editor` (standalone windows, tracked in `self._windows`), `:813` `_trash_paths`, `:855` `_undo_delete`, `:884` `_rename_selected`, `:1009` `really_quit`, `:1014` `closeEvent`.

Gotchas to keep in mind throughout:

- **`PixelateItem` constructor calls `_regen()` immediately** — `from_dict` must receive a working `base_provider`, and the editor must call `set_base_image()` *before* reconstructing items.
- **`TextItem.__init__` forces bold and grabs focus-able interaction flags** — `from_dict` must restore family/size/bold explicitly and set `Qt.NoTextInteraction` (a freshly loaded item is not being edited).
- **Stacking order** = scene insertion order (all annotations share zValue 0). Serialize via `scene.items(Qt.AscendingOrder)` filtered by `is_annotation`, re-add in that order.
- **QImage equality across a PNG round-trip**: compare after `convertToFormat(QImage.Format_ARGB32)` on both sides — in-memory images are `ARGB32_Premultiplied`, loaded PNGs are not. A false negative only costs a redundant base file, never data loss.
- **`apply_snapshot` order is origin → rotation → pos** — `_apply_transform` must use the same order or rotated items shift.
- **Tests must never touch `QMessageBox.question` for library files** — monkeypatch it to `pytest.fail` to prove the no-prompt bar.

---

## Task 1: Shape-item serialization in items.py

**Files:**
- `tests/test_items_serialize.py` (new)
- `wondershot/items.py` (modify)

`to_dict`/`from_dict` for `ArrowItem`, `LineItem`, `RectItem`, `EllipseItem`, `HighlightItem`, `FreehandItem`, plus the shared transform helpers and the `item_from_dict` dispatcher (which Task 2 extends).

- [x] **Step 1.1 — failing tests.** Create `tests/test_items_serialize.py`:

```python
"""Round-trip tests for annotation item serialization (sidecar format).

Pure: items in/out of dicts through real JSON, no scene or editor needed.
"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def roundtrip(item, base_provider=None):
    """Serialize through REAL json (catches non-JSON-safe values)."""
    from wondershot.items import item_from_dict
    d = json.loads(json.dumps(item.to_dict()))
    out = item_from_dict(d, base_provider=base_provider)
    assert out is not None, f"dispatcher returned None for {d.get('type')}"
    return out


def test_arrow_roundtrip(qapp):
    from wondershot.items import ArrowItem
    item = ArrowItem(QPointF(10.5, 20.25), QPointF(110.0, 80.75),
                     QColor("#e3242b"), 7)
    out = roundtrip(item)
    assert isinstance(out, ArrowItem)
    assert out.endpoints() == (QPointF(10.5, 20.25), QPointF(110.0, 80.75))
    assert out._color == QColor("#e3242b")
    assert out._width == 7
    assert out.pen().width() == 7


def test_line_roundtrip(qapp):
    from wondershot.items import LineItem
    item = LineItem(QPointF(1.0, 2.0), QPointF(3.5, -4.5),
                    QColor("#00ff00"), 3)
    out = roundtrip(item)
    assert isinstance(out, LineItem)
    assert out.endpoints() == (QPointF(1.0, 2.0), QPointF(3.5, -4.5))
    assert out.pen().color() == QColor("#00ff00")
    assert out.pen().width() == 3


def test_rect_and_ellipse_roundtrip(qapp):
    from wondershot.items import EllipseItem, RectItem
    for cls in (RectItem, EllipseItem):
        item = cls(QRectF(5.25, 6.5, 100.0, 50.75), QColor("#3daee9"), 4)
        out = roundtrip(item)
        assert isinstance(out, cls)
        assert out.rect() == QRectF(5.25, 6.5, 100.0, 50.75)
        assert out.pen().color() == QColor("#3daee9")
        assert out.pen().width() == 4


def test_highlight_roundtrip_keeps_translucency(qapp):
    from wondershot.items import HighlightItem
    item = HighlightItem(QRectF(0, 0, 60, 20), QColor("#ffe000"))
    out = roundtrip(item)
    assert isinstance(out, HighlightItem)
    assert out.rect() == QRectF(0, 0, 60, 20)
    # constructor re-applies the marker alpha — must come back as 90
    assert out.brush().color().alpha() == 90
    c = out.brush().color()
    assert (c.red(), c.green(), c.blue()) == (255, 224, 0)


def test_freehand_roundtrip_preserves_every_point(qapp):
    from wondershot.items import FreehandItem
    item = FreehandItem(QPointF(1.5, 2.5), QColor("#ff00ff"), 5)
    pts = [QPointF(3.25, 4.0), QPointF(10.0, -2.75), QPointF(11.125, 9.5)]
    for p in pts:
        item.add_point(p)
    out = roundtrip(item)
    assert isinstance(out, FreehandItem)
    path_in, path_out = item.path(), out.path()
    assert path_out.elementCount() == path_in.elementCount() == 4
    for i in range(path_in.elementCount()):
        assert path_out.elementAt(i).x == path_in.elementAt(i).x
        assert path_out.elementAt(i).y == path_in.elementAt(i).y
    assert out.pen().width() == 5


def test_roundtripped_items_are_annotations(qapp):
    """Restored items must be selectable/movable/flattenable like drawn ones."""
    from wondershot.items import ArrowItem, is_annotation
    from PySide6.QtWidgets import QGraphicsItem
    out = roundtrip(ArrowItem(QPointF(0, 0), QPointF(9, 9),
                              QColor("red"), 2))
    assert is_annotation(out)
    assert out.flags() & QGraphicsItem.ItemIsSelectable
    assert out.flags() & QGraphicsItem.ItemIsMovable


def test_dispatcher_unknown_type_returns_none(qapp):
    from wondershot.items import item_from_dict
    assert item_from_dict({"type": "hologram"}) is None
    assert item_from_dict({}) is None
```

- [x] **Step 1.2 — run, expect failure:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_items_serialize.py -x -q
```

Expected: `ImportError: cannot import name 'item_from_dict' from 'wondershot.items'` (or `AttributeError: 'ArrowItem' object has no attribute 'to_dict'`).

- [x] **Step 1.3 — implement.** In `wondershot/items.py`:

(a) After the existing `is_annotation` function (line ~50), add the shared helpers:

```python
def _color_str(c: QColor) -> str:
    return QColor(c).name(QColor.HexArgb)


def _transform_dict(item) -> dict:
    """Common geometry every serialized item carries."""
    p, o = item.pos(), item.transformOriginPoint()
    return {"pos": [p.x(), p.y()], "rotation": item.rotation(),
            "origin": [o.x(), o.y()]}


def _apply_transform(item, d: dict) -> None:
    # Same order as EditorWindow.apply_snapshot: origin, rotation, pos —
    # any other order shifts rotated items.
    o = d.get("origin", [0.0, 0.0])
    item.setTransformOriginPoint(QPointF(o[0], o[1]))
    item.setRotation(d.get("rotation", 0.0))
    p = d.get("pos", [0.0, 0.0])
    item.setPos(QPointF(p[0], p[1]))
```

(b) Add methods to `ArrowItem` (after its `set_style` method):

```python
    def to_dict(self) -> dict:
        return {"type": "arrow",
                "p1": [self._p1.x(), self._p1.y()],
                "p2": [self._p2.x(), self._p2.y()],
                "color": _color_str(self._color), "width": self._width,
                **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "ArrowItem":
        item = cls(QPointF(*d["p1"]), QPointF(*d["p2"]),
                   QColor(d["color"]), int(d["width"]))
        _apply_transform(item, d)
        return item
```

(c) `LineItem` (style lives on the pen):

```python
    def to_dict(self) -> dict:
        return {"type": "line",
                "p1": [self._p1.x(), self._p1.y()],
                "p2": [self._p2.x(), self._p2.y()],
                "color": _color_str(self.pen().color()),
                "width": self.pen().width(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "LineItem":
        item = cls(QPointF(*d["p1"]), QPointF(*d["p2"]),
                   QColor(d["color"]), int(d["width"]))
        _apply_transform(item, d)
        return item
```

(d) `RectItem` and `EllipseItem` — identical bodies apart from the type tag (`"rect"` / `"ellipse"`); shown for `RectItem`:

```python
    def to_dict(self) -> dict:
        r = self.rect()
        return {"type": "rect",
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "color": _color_str(self.pen().color()),
                "width": self.pen().width(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "RectItem":
        r = d["rect"]
        item = cls(QRectF(r[0], r[1], r[2], r[3]),
                   QColor(d["color"]), int(d["width"]))
        _apply_transform(item, d)
        return item
```

(e) `HighlightItem` — serialize the color with alpha forced opaque (the constructor re-applies the 90 alpha, mirroring `get_style`):

```python
    def to_dict(self) -> dict:
        r = self.rect()
        c = QColor(self.brush().color())
        c.setAlpha(255)
        return {"type": "highlight",
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "color": c.name(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "HighlightItem":
        r = d["rect"]
        item = cls(QRectF(r[0], r[1], r[2], r[3]), QColor(d["color"]))
        _apply_transform(item, d)
        return item
```

(f) `FreehandItem` — the path is MoveTo + LineTos only, so element coords round-trip it exactly:

```python
    def to_dict(self) -> dict:
        path = self.path()
        pts = [[path.elementAt(i).x, path.elementAt(i).y]
               for i in range(path.elementCount())]
        return {"type": "freehand", "points": pts,
                "color": _color_str(self.pen().color()),
                "width": self.pen().width(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "FreehandItem":
        pts = d["points"]
        item = cls(QPointF(pts[0][0], pts[0][1]),
                   QColor(d["color"]), int(d["width"]))
        for x, y in pts[1:]:
            item.add_point(QPointF(x, y))
        _apply_transform(item, d)
        return item
```

(g) At the very bottom of `items.py` (after `PixelateItem`), add the dispatcher. Task 2 fills in the remaining three types; until then they simply aren't in the table:

```python
def item_from_dict(d: dict, base_provider=None):
    """Rebuild a live annotation item from its serialized dict.

    Returns None for unknown/future types (the editor skips them rather
    than crashing on a newer sidecar). PixelateItem needs the editor's
    base_provider callable to regenerate its patch.
    """
    t = d.get("type")
    if t == "pixelate":
        if base_provider is None:
            return None
        return PixelateItem.from_dict(d, base_provider)
    cls = _ITEM_TYPES.get(t)
    return cls.from_dict(d) if cls is not None else None


_ITEM_TYPES = {
    "arrow": ArrowItem, "line": LineItem, "rect": RectItem,
    "ellipse": EllipseItem, "highlight": HighlightItem,
    "freehand": FreehandItem,
}
```

(Note: `"pixelate"` is special-cased above the table; `PixelateItem.from_dict`, `TextItem`, `StepItem` arrive in Task 2 — the `pixelate` branch will raise AttributeError if hit before then, which no Task-1 test does.)

- [x] **Step 1.4 — run, expect pass:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_items_serialize.py -x -q
```

- [x] **Step 1.5 — commit:**

```bash
git add wondershot/items.py tests/test_items_serialize.py
git commit -m "items: to_dict/from_dict for shape annotations + dispatcher

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Text/Step/Pixelate serialization + exact transform round-trip

**Files:**
- `tests/test_items_serialize.py` (extend)
- `wondershot/items.py` (modify)

- [x] **Step 2.1 — failing tests.** Append to `tests/test_items_serialize.py`:

```python
def test_text_roundtrip_fonts_and_width(qapp):
    from wondershot.items import TextItem
    from PySide6.QtCore import Qt
    item = TextItem(QPointF(40.0, 30.0), QColor("#112233"), point_size=21)
    f = item.font()
    f.setFamily("DejaVu Sans")
    f.setBold(False)          # non-default: constructor forces bold
    item.setFont(f)
    item.setPlainText("hello\nworld")
    item.setTextWidth(123.5)
    out = roundtrip(item)
    assert isinstance(out, TextItem)
    assert out.toPlainText() == "hello\nworld"
    assert out.defaultTextColor() == QColor("#112233")
    assert out.font().pointSize() == 21
    assert out.font().family() == "DejaVu Sans"
    assert out.font().bold() is False
    assert out.textWidth() == 123.5
    assert out.pos() == QPointF(40.0, 30.0)
    # a freshly loaded text item is NOT in editing mode
    assert out.textInteractionFlags() == Qt.NoTextInteraction


def test_text_default_width_stays_auto(qapp):
    from wondershot.items import TextItem
    item = TextItem(QPointF(0, 0), QColor("red"))
    assert item.textWidth() == -1.0
    out = roundtrip(item)
    assert out.textWidth() == -1.0


def test_step_roundtrip(qapp):
    from wondershot.items import StepItem
    item = StepItem(QPointF(77.0, 88.0), 12, QColor("#aa00aa"), radius=22.5)
    out = roundtrip(item)
    assert isinstance(out, StepItem)
    assert out.number == 12
    assert out.radius == 22.5
    assert out._color == QColor("#aa00aa")
    assert out.pos() == QPointF(77.0, 88.0)


def test_pixelate_roundtrip_uses_base_provider(qapp):
    from PySide6.QtGui import QImage
    from wondershot.items import PixelateItem
    base = QImage(200, 150, QImage.Format_ARGB32_Premultiplied)
    base.fill(QColor("orange"))
    item = PixelateItem(lambda: base, QRectF(10.0, 12.0, 80.0, 40.0),
                        block=9)
    out = roundtrip(item, base_provider=lambda: base)
    assert isinstance(out, PixelateItem)
    assert out.rect() == QRectF(10.0, 12.0, 80.0, 40.0)
    assert out._block == 9
    assert out._patch is not None, "patch must regenerate from the provider"


def test_pixelate_without_provider_is_skipped(qapp):
    from wondershot.items import item_from_dict
    d = {"type": "pixelate", "rect": [0, 0, 10, 10], "block": 14,
         "pos": [0, 0], "rotation": 0.0, "origin": [0, 0]}
    assert item_from_dict(d) is None  # no provider -> can't rebuild


def test_rotation_and_geometry_roundtrip_exactly(qapp):
    """Jack's bar: revisit an image and nothing has shifted. Doubles must
    survive JSON bit-for-bit (Python json round-trips floats exactly)."""
    from wondershot.items import RectItem
    item = RectItem(QRectF(3.1, 4.7, 99.9, 33.3), QColor("red"), 2)
    item.setTransformOriginPoint(QPointF(53.05, 21.35))
    item.setRotation(33.7)
    item.setPos(QPointF(-12.625, 7.0625))
    out = roundtrip(item)
    assert out.rotation() == 33.7
    assert out.pos() == QPointF(-12.625, 7.0625)
    assert out.transformOriginPoint() == QPointF(53.05, 21.35)
    assert out.rect() == QRectF(3.1, 4.7, 99.9, 33.3)
    # scene-space corner identical => no visible shift on revisit
    assert out.mapToScene(out.rect().topLeft()) \
        == item.mapToScene(item.rect().topLeft())


def test_arrow_rotation_roundtrip_exactly(qapp):
    from wondershot.items import ArrowItem
    item = ArrowItem(QPointF(5, 5), QPointF(120, 60), QColor("red"), 6)
    item.setTransformOriginPoint(QPointF(62.5, 32.5))
    item.setRotation(287.123456789)
    out = roundtrip(item)
    assert out.rotation() == 287.123456789
    assert out.mapToScene(out.endpoints()[1]) \
        == item.mapToScene(item.endpoints()[1])
```

- [x] **Step 2.2 — run, expect failure:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_items_serialize.py -x -q
```

Expected: `AttributeError: 'TextItem' object has no attribute 'to_dict'`.

- [x] **Step 2.3 — implement.** In `wondershot/items.py`:

(a) `TextItem` (after `mouseDoubleClickEvent`):

```python
    def to_dict(self) -> dict:
        f = self.font()
        return {"type": "text", "text": self.toPlainText(),
                "color": _color_str(self.defaultTextColor()),
                "family": f.family(), "point_size": f.pointSize(),
                "bold": f.bold(), "text_width": self.textWidth(),
                **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "TextItem":
        item = cls(QPointF(0, 0), QColor(d["color"]),
                   int(d.get("point_size", 18)))
        f = item.font()
        if d.get("family"):
            f.setFamily(d["family"])
        f.setBold(bool(d.get("bold", True)))
        item.setFont(f)
        item.setPlainText(d.get("text", ""))
        tw = d.get("text_width", -1.0)
        if tw is not None and tw > 0:
            item.setTextWidth(tw)
        # restored items are not mid-edit; double-click re-enables editing
        item.setTextInteractionFlags(Qt.NoTextInteraction)
        _apply_transform(item, d)
        return item
```

(b) `StepItem` (after `set_radius`):

```python
    def to_dict(self) -> dict:
        return {"type": "step", "number": self.number,
                "color": _color_str(self._color), "radius": self.radius,
                **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "StepItem":
        item = cls(QPointF(0, 0), int(d["number"]), QColor(d["color"]),
                   radius=float(d.get("radius", 16.0)))
        _apply_transform(item, d)
        return item
```

(c) `PixelateItem` (after `setRect`):

```python
    def to_dict(self) -> dict:
        r = self._rect
        return {"type": "pixelate",
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "block": self._block, **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict, base_provider) -> "PixelateItem":
        r = d["rect"]
        item = cls(base_provider, QRectF(r[0], r[1], r[2], r[3]),
                   block=int(d.get("block", 14)))
        _apply_transform(item, d)
        return item
```

(d) Extend the `_ITEM_TYPES` table at the bottom:

```python
_ITEM_TYPES = {
    "arrow": ArrowItem, "line": LineItem, "rect": RectItem,
    "ellipse": EllipseItem, "highlight": HighlightItem,
    "freehand": FreehandItem, "text": TextItem, "step": StepItem,
}
```

- [x] **Step 2.4 — run, expect pass** (same command). Also run the full suite to catch regressions:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

- [x] **Step 2.5 — commit:**

```bash
git add wondershot/items.py tests/test_items_serialize.py
git commit -m "items: text/step/pixelate serialization, exact geometry round-trip

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: sidecar.py module

**Files:**
- `tests/test_sidecar.py` (new)
- `wondershot/sidecar.py` (new)

- [x] **Step 3.1 — failing tests.** Create `tests/test_sidecar.py`:

```python
"""Sidecar file plumbing: paths, atomic JSON, versioning, related files."""
import json
import os

import pytest


def test_paths(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    assert sidecar.sidecar_dir(img) == str(tmp_path / ".wondershot")
    assert sidecar.sidecar_path(img) == str(
        tmp_path / ".wondershot" / "shot.png.json")
    assert sidecar.base_path(img, 0) == str(
        tmp_path / ".wondershot" / "shot.png.base.0.png")
    assert sidecar.base_path(img, 12) == str(
        tmp_path / ".wondershot" / "shot.png.base.12.png")


def test_name_includes_extension_no_stem_collisions(tmp_path):
    from wondershot import sidecar
    a = sidecar.sidecar_path(str(tmp_path / "shot.png"))
    b = sidecar.sidecar_path(str(tmp_path / "shot.jpg"))
    assert a != b


def test_save_load_roundtrip(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    data = {"version": 1, "bases": 2, "items": [{"type": "rect"}],
            "effects": {}}
    assert sidecar.save(img, data) is True
    assert sidecar.load(img) == data
    # atomic write: no .tmp left behind
    assert not os.path.exists(sidecar.sidecar_path(img) + ".tmp")


def test_load_missing_returns_none(tmp_path):
    from wondershot import sidecar
    assert sidecar.load(str(tmp_path / "nope.png")) is None


def test_load_corrupt_returns_none(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    os.makedirs(sidecar.sidecar_dir(img))
    with open(sidecar.sidecar_path(img), "w") as f:
        f.write("{not json")
    assert sidecar.load(img) is None


def test_future_version_returns_none(tmp_path):
    """Unknown format -> editor must fall back to today's flat open."""
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    sidecar.save(img, {"version": 1, "bases": 1, "items": []})
    raw = json.load(open(sidecar.sidecar_path(img)))
    raw["version"] = 99
    with open(sidecar.sidecar_path(img), "w") as f:
        json.dump(raw, f)
    assert sidecar.load(img) is None


def test_is_library_file(tmp_path):
    from wondershot import sidecar

    class S:
        library_dir = str(tmp_path / "lib")
        extra_dirs = [str(tmp_path / "extra")]

    os.makedirs(S.library_dir)
    os.makedirs(S.extra_dirs[0])
    assert sidecar.is_library_file(str(tmp_path / "lib" / "a.png"), S())
    assert sidecar.is_library_file(str(tmp_path / "extra" / "b.png"), S())
    assert not sidecar.is_library_file(str(tmp_path / "other.png"), S())
    assert not sidecar.is_library_file("", S())
    assert not sidecar.is_library_file(None, S())
    assert not sidecar.is_library_file(str(tmp_path / "lib" / "a.png"),
                                       None)


def test_related_files(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    assert sidecar.related_files(img) == []
    sidecar.save(img, {"version": 1, "bases": 2, "items": []})
    for n in (0, 1):
        with open(sidecar.base_path(img, n), "wb") as f:
            f.write(b"png")
    # a neighbor's files must NOT be picked up
    sidecar.save(str(tmp_path / "other.png"), {"version": 1, "bases": 1,
                                               "items": []})
    rel = sidecar.related_files(img)
    assert sidecar.sidecar_path(img) in rel
    assert sidecar.base_path(img, 0) in rel
    assert sidecar.base_path(img, 1) in rel
    assert len(rel) == 3


def test_rename_files(tmp_path):
    from wondershot import sidecar
    old = str(tmp_path / "old.png")
    new = str(tmp_path / "new name.png")  # spaces must survive globbing
    sidecar.save(old, {"version": 1, "bases": 1, "items": []})
    with open(sidecar.base_path(old, 0), "wb") as f:
        f.write(b"png")
    sidecar.rename_files(old, new)
    assert sidecar.related_files(old) == []
    assert os.path.exists(sidecar.sidecar_path(new))
    assert os.path.exists(sidecar.base_path(new, 0))


def test_rename_files_noop_without_sidecar(tmp_path):
    from wondershot import sidecar
    sidecar.rename_files(str(tmp_path / "a.png"), str(tmp_path / "b.png"))
    # must not raise, must not create the dir
    assert not os.path.isdir(sidecar.sidecar_dir(str(tmp_path / "a.png")))
```

- [x] **Step 3.2 — run, expect failure:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_sidecar.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'wondershot.sidecar'`.

- [x] **Step 3.3 — implement.** Create `wondershot/sidecar.py`:

```python
"""Sidecar persistence for library images — pure file plumbing, no widgets.

Layout, per image `<dir>/<name>` (name keeps its extension so shot.png
and shot.jpg never collide):

    <dir>/.wondershot/<name>.json          format-versioned document
    <dir>/.wondershot/<name>.base.<N>.png  base-image stack, N=0 = original
                                           capture, highest N = current base

The JSON document: {"version": 1, "bases": N, "items": [...],
"effects": {...}}. `items` are the serialized annotation objects
(items.item_from_dict rebuilds them); `effects` is a write-only record
of the output-effect settings at save time. Unknown versions load as
None so older builds fall back to opening the flattened PNG.
"""

from __future__ import annotations

import glob as _glob
import json
import os

FORMAT_VERSION = 1
SIDECAR_DIRNAME = ".wondershot"


def sidecar_dir(image_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(image_path)),
                        SIDECAR_DIRNAME)


def sidecar_path(image_path: str) -> str:
    return os.path.join(sidecar_dir(image_path),
                        os.path.basename(image_path) + ".json")


def base_path(image_path: str, n: int) -> str:
    return os.path.join(sidecar_dir(image_path),
                        f"{os.path.basename(image_path)}.base.{n}.png")


def is_library_file(path: str | None, settings) -> bool:
    """True when `path` sits directly in a watched library folder.

    Library files autosave with no prompts and get sidecars; anything
    else (e.g. `wondershot -e /random/file.png`) keeps the save prompt.
    """
    if not path or settings is None:
        return False
    dirs = [getattr(settings, "library_dir", "") or ""]
    dirs += list(getattr(settings, "extra_dirs", []) or [])
    parent = os.path.dirname(os.path.abspath(path))
    return any(d and os.path.abspath(d) == parent for d in dirs)


def load(image_path: str) -> dict | None:
    """Parsed sidecar document, or None (missing / corrupt / future
    version) — None means 'open the flattened PNG as before'."""
    try:
        with open(sidecar_path(image_path), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != FORMAT_VERSION:
        return None
    return data


def save(image_path: str, data: dict) -> bool:
    """Atomic JSON write (tmp + replace): a crash mid-save never leaves a
    truncated sidecar next to a good flattened PNG."""
    target = sidecar_path(image_path)
    try:
        os.makedirs(sidecar_dir(image_path), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def _base_glob(image_path: str) -> str:
    return os.path.join(
        sidecar_dir(image_path),
        _glob.escape(os.path.basename(image_path)) + ".base.*.png")


def related_files(image_path: str) -> list[str]:
    """Every sidecar file that belongs to image_path (JSON + bases) —
    what trash/rename must carry along with the image."""
    out = []
    sp = sidecar_path(image_path)
    if os.path.exists(sp):
        out.append(sp)
    out.extend(sorted(_glob.glob(_base_glob(image_path))))
    return out


def rename_files(old_image: str, new_image: str) -> None:
    """Follow an image rename: move the JSON and re-number-free base files
    to the new name. No-op when there is nothing to move."""
    if not related_files(old_image):
        return
    os.makedirs(sidecar_dir(new_image), exist_ok=True)
    old_sp = sidecar_path(old_image)
    if os.path.exists(old_sp):
        os.replace(old_sp, sidecar_path(new_image))
    for f in _glob.glob(_base_glob(old_image)):
        n = int(f.rsplit(".base.", 1)[1][:-len(".png")])
        os.replace(f, base_path(new_image, n))
```

- [x] **Step 3.4 — run, expect pass:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_sidecar.py -x -q
```

- [x] **Step 3.5 — commit:**

```bash
git add wondershot/sidecar.py tests/test_sidecar.py
git commit -m "sidecar: path scheme, versioned atomic JSON, related-file helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Editor write side — autosave, sidecar save, base-stack push

**Files:**
- `tests/test_editor_sidecar.py` (new)
- `wondershot/editor.py` (modify)

What lands here: state attributes, `_is_library_file`, `_images_equal`, `_record_base_push` hooks in `_apply_crop`/`_apply_cutout`/`_bg_done`, `_write_sidecar` (including truncate-on-revisit-undo, fully exercised in Task 5), the no-prompt `maybe_save`, and `save()` writing the sidecar.

- [x] **Step 4.1 — failing tests.** Create `tests/test_editor_sidecar.py`:

```python
"""Editor <-> sidecar integration: autosave, base stack, reconstruction."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    """Library-aware stub mirroring tests/test_gallery_trash.py."""

    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []
        self.tool_color = "#e3242b"
        self.stroke_width = 10
        self.font_size = 24

    def __getattr__(self, k):
        return ""


def write_image(path, w=200, h=150, color="white"):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    assert img.save(path)
    return img


def make_library_editor(qapp, tmp_path, name="shot.png", w=200, h=150):
    from wondershot.editor import EditorWindow
    path = os.path.join(str(tmp_path), name)
    write_image(path, w, h)
    return EditorWindow(path, settings=_Settings(str(tmp_path)))


def read_sidecar(path):
    from wondershot import sidecar
    with open(sidecar.sidecar_path(path)) as f:
        return json.load(f)


def add_rect(ed, rect=QRectF(10, 10, 50, 40)):
    from wondershot.editor import AddItemCommand
    from wondershot.items import RectItem
    item = RectItem(rect, QColor("red"), 4)
    ed.undo_stack.push(AddItemCommand(ed, item))
    return item


def test_save_writes_flat_png_plus_sidecar_and_base0(qapp, tmp_path):
    from wondershot import sidecar
    ed = make_library_editor(qapp, tmp_path)
    add_rect(ed)
    ed.save()
    assert ed.undo_stack.isClean()
    data = read_sidecar(ed.path)
    assert data["version"] == 1
    assert data["bases"] == 1
    assert len(data["items"]) == 1 and data["items"][0]["type"] == "rect"
    assert "effects" in data
    # base.0 = clean original (annotation NOT baked in)
    base0 = QImage(sidecar.base_path(ed.path, 0))
    assert base0.pixelColor(12, 10) == QColor("white")
    # library PNG = flattened (annotation IS baked in)
    flat = QImage(ed.path)
    c = flat.pixelColor(12, 10)
    assert c.red() > 150 and c.green() < 100


def test_maybe_save_autosaves_library_file_without_prompting(
        qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from wondershot import sidecar
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: pytest.fail(
            "library files must never prompt")))
    ed = make_library_editor(qapp, tmp_path)
    add_rect(ed)
    assert ed.maybe_save() is True
    assert ed.undo_stack.isClean()
    assert os.path.exists(sidecar.sidecar_path(ed.path))


def test_non_library_file_still_prompts(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from wondershot import sidecar
    from wondershot.editor import EditorWindow
    lib = tmp_path / "lib"
    lib.mkdir()
    outside = os.path.join(str(tmp_path), "elsewhere.png")
    write_image(outside)
    calls = []
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: calls.append(1)
                     or QMessageBox.Discard))
    ed = EditorWindow(outside, settings=_Settings(str(lib)))
    add_rect(ed)
    assert ed.maybe_save() is True
    assert calls, "non-library files keep the save prompt"
    assert not os.path.exists(sidecar.sidecar_path(outside))


def test_save_without_settings_writes_no_sidecar(qapp, tmp_path):
    """EditorWindow with settings=None (legacy callers/tests) keeps the
    plain flatten-and-save behavior."""
    from wondershot import sidecar
    from wondershot.editor import EditorWindow
    path = os.path.join(str(tmp_path), "shot.png")
    write_image(path)
    ed = EditorWindow(path)
    add_rect(ed)
    ed.save()
    assert not os.path.exists(sidecar.sidecar_path(path))


def test_crop_pushes_pre_op_base(qapp, tmp_path):
    from wondershot import sidecar
    ed = make_library_editor(qapp, tmp_path, w=200, h=150)
    ed._apply_crop(QRect(0, 0, 100, 75))
    assert ed.base_image.width() == 100
    ed.save()
    data = read_sidecar(ed.path)
    assert data["bases"] == 2
    assert QImage(sidecar.base_path(ed.path, 0)).width() == 200
    assert QImage(sidecar.base_path(ed.path, 1)).width() == 100


def test_bg_remove_pushes_pre_op_base(qapp, tmp_path):
    from wondershot import sidecar
    ed = make_library_editor(qapp, tmp_path)
    cut = QImage(200, 150, QImage.Format_ARGB32_Premultiplied)
    cut.fill(Qt.transparent)
    ed._bg_done(cut, "")          # SetBaseImageCommand path (bg remove)
    ed.save()
    data = read_sidecar(ed.path)
    assert data["bases"] == 2
    assert QImage(sidecar.base_path(ed.path, 0)) \
        .pixelColor(5, 5) == QColor("white")
    assert QImage(sidecar.base_path(ed.path, 1)) \
        .pixelColor(5, 5).alpha() == 0


def test_undone_crop_is_not_persisted(qapp, tmp_path):
    ed = make_library_editor(qapp, tmp_path)
    add_rect(ed)                   # something dirty so save() runs fully
    ed._apply_crop(QRect(0, 0, 100, 75))
    ed.undo_stack.undo()           # user changed their mind in-session
    assert ed.base_image.width() == 200
    ed.save()
    assert read_sidecar(ed.path)["bases"] == 1


def test_two_destructive_ops_push_two_bases(qapp, tmp_path):
    ed = make_library_editor(qapp, tmp_path, w=200, h=150)
    ed._apply_crop(QRect(0, 0, 150, 150))
    ed._apply_crop(QRect(0, 0, 100, 100))
    ed.save()
    data = read_sidecar(ed.path)
    # original + intermediate (150w) + current (100w)
    assert data["bases"] == 3


def test_resave_without_changes_does_not_grow_stack(qapp, tmp_path):
    ed = make_library_editor(qapp, tmp_path)
    add_rect(ed)
    ed.save()
    ed.undo_stack.resetClean()     # mark dirty without touching the base
    ed.save()
    assert read_sidecar(ed.path)["bases"] == 1
```

- [x] **Step 4.2 — run, expect failure:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_editor_sidecar.py -x -q
```

Expected: first test fails — `FileNotFoundError` reading the sidecar (save() doesn't write one yet), and the prompt test fails with the `pytest.fail` message.

- [x] **Step 4.3 — implement.** All edits in `wondershot/editor.py`:

(a) Add the import. After the existing `from . import imageops` (line 37):

```python
from . import imageops
from . import sidecar
```

(b) Module-level helper, after the `Tool` enum / before `_EDIT_KEYS`:

```python
def _images_equal(a: QImage, b: QImage) -> bool:
    """Pixel equality across a PNG round-trip: in-memory images are
    premultiplied, loaded PNGs aren't — normalize before comparing."""
    if a.isNull() or b.isNull() or a.size() != b.size():
        return False
    return (a.convertToFormat(QImage.Format_ARGB32)
            == b.convertToFormat(QImage.Format_ARGB32))
```

(c) State attributes. In `__init__`, immediately after `self.base_image = QImage()` / `self.set_base_image(image)` (lines 296–297), add:

```python
        # -- sidecar persistence state (library files only) ------------
        self._loaded_original = image.copy()   # base.0 on first save
        self._base_stack_count = 0             # bases already on disk
        # (undo_index_after_push, pre-op image) — written at save time
        self._pending_base_pushes: list[tuple[int, QImage]] = []
```

(d) Reset on image switch. In `load()` (line 332), after `self.step_counter = 1` and before `self.set_base_image(image)`, add:

```python
        self._loaded_original = image.copy()
        self._base_stack_count = 0
        self._pending_base_pushes = []
```

(Task 5 rewrites the top of `load()` for the read side; these reset lines stay.)

(e) Library check + push recorder. Add after `maybe_save()`:

```python
    def _is_library_file(self) -> bool:
        return (not self.preview_only
                and sidecar.is_library_file(self.path, self.settings))

    def _record_base_push(self, image: QImage) -> None:
        """Remember a pre-destructive-op image for the on-disk base stack.

        Call IMMEDIATELY BEFORE pushing the destructive QUndoCommand: the
        recorded undo index (current + 1) is where that command will sit,
        so at save time pushes whose command was undone are dropped.
        """
        if self._is_library_file():
            self._pending_base_pushes.append(
                (self.undo_stack.index() + 1, image.copy()))
```

(f) No-prompt `maybe_save`. Replace the body of `maybe_save()` (line 361):

```python
    def maybe_save(self) -> bool:
        """Save pending changes. Library files autosave silently (Jack's
        bar: no prompts, ever); only files opened from outside the
        library still ask. False means the user cancelled a prompt."""
        if self.undo_stack.isClean():
            return True
        if self._is_library_file():
            self.save()
            return True  # even on disk error: the warning already showed
        ret = QMessageBox.question(
            self, "Wondershot", "Save changes to this image?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if ret == QMessageBox.Save:
            self.save()
            return self.undo_stack.isClean()
        return ret == QMessageBox.Discard
```

(g) Hook the destructive ops. Replace `_apply_crop` (line 1227):

```python
    def _apply_crop(self, rect: QRect) -> None:
        flat = self.flattened()
        # pre-op FLATTENED image: a crop folds annotations into the base,
        # so revisit-undo must restore what was visible, not just pixels
        self._record_base_push(flat)
        new_image = imageops.crop(flat, rect)
        self.undo_stack.push(FlattenCommand(self, new_image, "crop"))
```

Replace `_apply_cutout` (line 1231):

```python
    def _apply_cutout(self, tool: Tool, r: QRect) -> None:
        flat = self.flattened()
        if r.isEmpty():
            return
        self._record_base_push(flat)
        # note: QRect.right()/bottom() are x+w-1, not the true edge
        if tool == Tool.CUTOUT_V:
            new_image = imageops.cut_out(flat, r.x(), r.x() + r.width(),
                                         horizontal=False)
        else:
            new_image = imageops.cut_out(flat, r.y(), r.y() + r.height(),
                                         horizontal=True)
        self.undo_stack.push(FlattenCommand(self, new_image, "cut out"))
```

In `_bg_done` (line 663), insert the record call before the push:

```python
    def _bg_done(self, image, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Wondershot",
                                f"Remove Background failed: {error}")
            return
        self._record_base_push(self.base_image)
        self.undo_stack.push(
            SetBaseImageCommand(self, image, "remove background"))
        self.statusBar().showMessage(
            "Background removed — save as PNG to keep transparency", 8000)
```

(h) Sidecar write. In `save()` (line 1255), insert the sidecar write after a successful flat save:

```python
    def save(self) -> None:
        if not self.path or self.preview_only:
            self.save_as()
            return
        self._cleanup_empty_text()
        if self.flattened().save(self.path):
            if self._is_library_file():
                self._write_sidecar()
            self.undo_stack.setClean()
            self.saved.emit(self.path)
            self.statusBar().showMessage("Saved", 2000)
        else:
            QMessageBox.warning(self, "Wondershot", f"Could not save {self.path}")
```

And add the new method after `save()`:

```python
    def _ordered_annotations(self) -> list:
        """Annotations bottom-to-top — re-adding in this order reproduces
        the stacking (all annotations share zValue 0; order = insertion)."""
        return [i for i in self.scene.items(Qt.AscendingOrder)
                if is_annotation(i)]

    def _write_sidecar(self) -> None:
        """Persist the editable document: base stack + live items.

        Stack discipline (N=0 = original capture, top = current base):
        1. first save ever writes base.0 from the originally-loaded image
        2. surviving (not-undone) pre-destructive-op snapshots append
        3. if the current base matches an EARLIER entry, the user
           revisit-undid — truncate above it and delete orphan files;
           otherwise, a changed current base becomes the new top
        """
        path = self.path
        os.makedirs(sidecar.sidecar_dir(path), exist_ok=True)
        count = self._base_stack_count
        if count == 0:
            self._loaded_original.save(sidecar.base_path(path, 0))
            count = 1
        for idx, img in self._pending_base_pushes:
            if self.undo_stack.index() < idx:
                continue  # the op was undone in-session
            if _images_equal(img, QImage(sidecar.base_path(path,
                                                           count - 1))):
                continue  # already the top (e.g. first op after open)
            img.save(sidecar.base_path(path, count))
            count += 1
        self._pending_base_pushes = []
        if not _images_equal(self.base_image,
                             QImage(sidecar.base_path(path, count - 1))):
            matched = -1
            for k in range(count - 2, -1, -1):
                if _images_equal(self.base_image,
                                 QImage(sidecar.base_path(path, k))):
                    matched = k
                    break
            if matched >= 0:  # revisit-undo landed on an earlier base
                for j in range(matched + 1, count):
                    try:
                        os.remove(sidecar.base_path(path, j))
                    except OSError:
                        pass
                count = matched + 1
            else:
                self.base_image.save(sidecar.base_path(path, count))
                count += 1
        self._base_stack_count = count
        s = self.settings
        effects = {
            "rounded": bool(getattr(s, "effect_rounded", False)),
            "corner_radius": int(getattr(s, "effect_corner_radius", 0)
                                 or 0),
            "fade": bool(getattr(s, "effect_fade", False)),
            "fade_height": int(getattr(s, "effect_fade_height", 0) or 0),
        }
        sidecar.save(path, {
            "version": sidecar.FORMAT_VERSION,
            "bases": count,
            "items": [it.to_dict() for it in self._ordered_annotations()],
            "effects": effects,
        })
```

(Gotcha: `getattr(stub, "effect_rounded")` returns `""` with the test stub — `bool("")`/`int("" or 0)` handle it; never call `int(...)` on the raw value.)

- [x] **Step 4.4 — run, expect pass**, then the full suite (existing `test_editor.py` exercises `save`/crop paths with `settings=None` — `_is_library_file()` is False there, so behavior is unchanged):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_editor_sidecar.py -x -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

- [x] **Step 4.5 — commit:**

```bash
git add wondershot/editor.py tests/test_editor_sidecar.py
git commit -m "editor: autosave library files, write sidecar + base stack on save

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Editor read side — reconstruct from sidecar, revisit-undo

**Files:**
- `tests/test_editor_sidecar.py` (extend)
- `wondershot/editor.py` (modify)

- [x] **Step 5.1 — failing tests.** Append to `tests/test_editor_sidecar.py`:

```python
def reopen(ed, tmp_path):
    from wondershot.editor import EditorWindow
    return EditorWindow(ed.path, settings=_Settings(str(tmp_path)))


def test_reopen_restores_live_items(qapp, tmp_path):
    from wondershot.items import RectItem, StepItem, is_annotation
    ed = make_library_editor(qapp, tmp_path)
    add_rect(ed)
    # stamp two steps via the real tool path (numbers 1 and 2)
    from wondershot.editor import Tool
    ed.set_tool(Tool.STEP)
    ed.begin_draw(QPointF(30, 30))
    ed.begin_draw(QPointF(60, 60))
    ed.save()
    ed2 = reopen(ed, tmp_path)
    live = [i for i in ed2.scene.items() if is_annotation(i)]
    assert len(live) == 3
    assert len([i for i in live if isinstance(i, RectItem)]) == 1
    steps = sorted(i.number for i in live if isinstance(i, StepItem))
    assert steps == [1, 2]
    assert ed2.step_counter == 3, "next stamp continues the numbering"
    # the canvas shows the CLEAN base — annotations are objects, not pixels
    assert ed2.base_image.pixelColor(12, 10) == QColor("white")
    # nothing dirty right after open
    assert ed2.undo_stack.isClean()


def test_reopen_without_sidecar_behaves_like_today(qapp, tmp_path):
    """Migration: pre-sidecar library images open flat, no errors; the
    sidecar appears on their first save."""
    from wondershot import sidecar
    from wondershot.editor import EditorWindow
    path = os.path.join(str(tmp_path), "legacy.png")
    write_image(path)
    ed = EditorWindow(path, settings=_Settings(str(tmp_path)))
    assert not os.path.exists(sidecar.sidecar_path(path))
    assert ed.base_image.width() == 200
    add_rect(ed)
    ed.save()
    assert os.path.exists(sidecar.sidecar_path(path))


def test_reopen_pixelate_is_live(qapp, tmp_path):
    from wondershot.items import PixelateItem
    ed = make_library_editor(qapp, tmp_path)
    ed._apply_pixelate(QRect(20, 20, 60, 40))
    ed.save()
    ed2 = reopen(ed, tmp_path)
    items = [i for i in ed2.scene.items() if isinstance(i, PixelateItem)]
    assert len(items) == 1
    item = items[0]
    assert item._patch is not None, "provider wired to the live base"
    item.setRect(QRectF(20, 20, 80, 50))   # still resizable like new
    assert item.rect().width() == 80


def test_crop_is_undoable_on_revisit(qapp, tmp_path):
    """Jack's bar: destructive ops undo across sessions via the stack."""
    ed = make_library_editor(qapp, tmp_path, w=200, h=150)
    ed._apply_crop(QRect(0, 0, 100, 75))
    ed.save()
    ed2 = reopen(ed, tmp_path)
    assert ed2.base_image.width() == 100      # top of stack
    assert ed2.undo_stack.canUndo()
    ed2.undo_stack.undo()
    assert ed2.base_image.width() == 200      # original capture is back
    ed2.undo_stack.redo()
    assert ed2.base_image.width() == 100


def test_revisit_undo_then_save_truncates_stack(qapp, tmp_path):
    from wondershot import sidecar
    ed = make_library_editor(qapp, tmp_path, w=200, h=150)
    ed._apply_crop(QRect(0, 0, 100, 75))
    ed.save()
    ed2 = reopen(ed, tmp_path)
    ed2.undo_stack.undo()
    ed2.save()
    data = read_sidecar(ed2.path)
    assert data["bases"] == 1
    assert not os.path.exists(sidecar.base_path(ed2.path, 1))
    # and the flattened library PNG reflects the un-cropped state
    assert QImage(ed2.path).width() == 200


def test_full_cycle_annotations_and_crop(qapp, tmp_path):
    """Annotate -> crop -> autosave-close -> reopen -> items live, crop
    undoable, then redo + new annotation persists again."""
    from wondershot.items import RectItem, is_annotation
    ed = make_library_editor(qapp, tmp_path, w=200, h=150)
    ed._apply_crop(QRect(0, 0, 120, 100))
    add_rect(ed, QRectF(5, 5, 30, 20))     # drawn AFTER the crop
    assert ed.maybe_save() is True          # the autosave close path
    ed2 = reopen(ed, tmp_path)
    live = [i for i in ed2.scene.items() if is_annotation(i)]
    assert len(live) == 1 and isinstance(live[0], RectItem)
    assert ed2.base_image.width() == 120
    ed2.undo_stack.undo()                   # revisit-undo the crop
    assert ed2.base_image.width() == 200
    # the post-crop rect is still on the scene (live object, untouched)
    assert [i for i in ed2.scene.items() if is_annotation(i)]


def test_corrupt_sidecar_falls_back_to_flat_open(qapp, tmp_path):
    from wondershot import sidecar
    ed = make_library_editor(qapp, tmp_path)
    add_rect(ed)
    ed.save()
    with open(sidecar.sidecar_path(ed.path), "w") as f:
        f.write("{broken")
    ed2 = reopen(ed, tmp_path)
    # opens the flattened PNG; no live items, but no crash either
    from wondershot.items import is_annotation
    assert not [i for i in ed2.scene.items() if is_annotation(i)]
    assert ed2.base_image.width() == 200
```

- [x] **Step 5.2 — run, expect failure:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_editor_sidecar.py -x -q
```

Expected: `test_reopen_restores_live_items` fails — reopened editor has 0 live annotations (it opened the flattened PNG).

- [x] **Step 5.3 — implement.** All edits in `wondershot/editor.py`:

(a) `HistoryBaseCommand`, placed directly after `SetBaseImageCommand` (line ~170):

```python
class HistoryBaseCommand(QUndoCommand):
    """Revisit-undo for a persisted destructive op (sidecar base stack).

    Pushed at load time, one per stack transition; the first redo is a
    no-op because the editor already shows the post-op base (same
    pattern as GripCommand). Ctrl+Z then walks the base stack down to
    the original capture; redo walks it back up.
    """

    def __init__(self, editor: "EditorWindow", old_image: QImage,
                 new_image: QImage):
        super().__init__("destructive edit (previous session)")
        self.editor = editor
        self.old_image = old_image
        self.new_image = new_image
        self._first = True

    def redo(self):
        if self._first:
            self._first = False
            return
        self.editor.set_base_image(self.new_image)

    def undo(self):
        self.editor.set_base_image(self.old_image)
```

(b) Rewrite `load()` (line 332; keep the Task-4 reset lines, reorder as shown). The full replacement:

```python
    def load(self, path: str | None, image: QImage | None = None) -> bool:
        """Swap the editor to a different image, dropping edit history.

        When `path` has a sidecar, the top-of-stack base is loaded and
        the annotations come back as live objects; otherwise the file
        opens flat exactly as before (pre-sidecar migration path)."""
        data = None
        if image is None and path:
            data = sidecar.load(path)
            if data and data.get("bases"):
                image = QImage(sidecar.base_path(path,
                                                 int(data["bases"]) - 1))
                if image.isNull():  # bases missing/deleted: fall back
                    image, data = QImage(path), None
            else:
                data = None
                image = QImage(path)
        if image is None or image.isNull():
            return False
        self.scene.clearSelection()
        for it in list(self.scene.items()):
            if is_annotation(it):
                self.scene.removeItem(it)
        self.path = path
        self.preview_only = False
        self.undo_stack.clear()
        self.step_counter = 1
        self._loaded_original = image.copy()
        self._base_stack_count = int(data["bases"]) if data else 0
        self._pending_base_pushes = []
        self.set_base_image(image)
        if data:
            self._restore_items(data)
            self._push_base_history(path, int(data["bases"]))
            self.undo_stack.setClean()
        self._fit_if_large()  # fit-to-window by default
        self._update_title()
        return True
```

(c) The two helpers, after `load_preview()`:

```python
    def _restore_items(self, data: dict) -> None:
        """Reconstruct serialized annotations as live scene objects.

        Items come back in bottom-to-top order (how they were saved), so
        plain addItem reproduces the stacking. Unknown future item types
        deserialize to None and are skipped, never crash."""
        from .items import item_from_dict
        for d in data.get("items", []):
            it = item_from_dict(d, base_provider=lambda: self.base_image)
            if it is None:
                continue
            self.scene.addItem(it)
            if isinstance(it, StepItem):
                self.step_counter = max(self.step_counter, it.number + 1)

    def _push_base_history(self, path: str, count: int) -> None:
        """Arm revisit-undo: one no-op-first command per stack step."""
        for k in range(1, count):
            old = QImage(sidecar.base_path(path, k - 1))
            new = QImage(sidecar.base_path(path, k))
            if old.isNull() or new.isNull():
                continue
            self.undo_stack.push(HistoryBaseCommand(self, old, new))
```

(d) Constructor-from-path (standalone editors: `EditorWindow(path, settings=...)` never goes through `load()`). In `__init__`, the current image resolution is:

```python
        self.path = path
        self.settings = settings
        if image is None and path:
            image = QImage(path)
```

Replace with:

```python
        self.path = path
        self.settings = settings
        self._sidecar_boot = image is None and bool(path) \
            and sidecar.load(path) is not None
        if image is None and path:
            image = QImage(path)
```

Then at the very end of `__init__`, after `self._fit_if_large()`:

```python
        if self._sidecar_boot:
            self.load(path)  # reconstruct items + arm revisit-undo
```

(The double `QImage(path)` read only happens when a sidecar exists, and `load()` immediately replaces it with the stack base — cheap and keeps one canonical code path.)

- [x] **Step 5.4 — run, expect pass**, then full suite:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_editor_sidecar.py -x -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Watch for: `tests/test_editor.py` and `test_editor_ai.py` construct editors with `settings=None` or raw images — those must stay green untouched.

- [x] **Step 5.5 — commit:**

```bash
git add wondershot/editor.py tests/test_editor_sidecar.py
git commit -m "editor: reconstruct live annotations from sidecar, revisit-undo via base stack

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Gallery — trash/undo/rename carry sidecars, quit closes standalone editors

**Files:**
- `tests/test_gallery_sidecar.py` (new)
- `wondershot/gallery.py` (modify)

- [x] **Step 6.1 — failing tests.** Create `tests/test_gallery_sidecar.py`:

```python
"""Gallery <-> sidecar integration: trash, undo-delete, rename, scan, quit."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []

    def __getattr__(self, k):
        if k in ("stroke_width", "font_size", "capture_delay",
                 "share_expiry_days"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic",
                                      "noise", "copy")) else ""


class _Capture:
    def __getattr__(self, k):
        return lambda *a, **kw: None


def make_gallery(qapp, tmp_path):
    from wondershot.gallery import GalleryWindow
    return GalleryWindow(_Settings(str(tmp_path)), _Capture())


def seed_image_with_sidecar(tmp_path, name="shot.png"):
    from wondershot import sidecar
    path = os.path.join(str(tmp_path), name)
    img = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    img.save(path)
    sidecar.save(path, {"version": 1, "bases": 1, "items": [],
                        "effects": {}})
    img.save(sidecar.base_path(path, 0))
    return path


def test_trash_takes_sidecar_files_along(qapp, tmp_path):
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g._trash_paths([path], confirm=False)
    assert not os.path.exists(path)
    assert not os.path.exists(sidecar.sidecar_path(path))
    assert not os.path.exists(sidecar.base_path(path, 0))


def test_undo_delete_restores_sidecar_files(qapp, tmp_path):
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g._trash_paths([path], confirm=False)
    g._undo_delete()
    assert os.path.exists(path)
    assert os.path.exists(sidecar.sidecar_path(path))
    assert os.path.exists(sidecar.base_path(path, 0))
    data = json.load(open(sidecar.sidecar_path(path)))
    assert data["version"] == 1


def test_undo_delete_recreates_wondershot_dir(qapp, tmp_path):
    """Trashing the LAST image may leave .wondershot empty/removed; the
    restore must recreate the directory before moving files back."""
    import shutil
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g._trash_paths([path], confirm=False)
    shutil.rmtree(sidecar.sidecar_dir(path), ignore_errors=True)
    g._undo_delete()
    assert os.path.exists(sidecar.sidecar_path(path))


def test_wondershot_dir_never_appears_in_strip(qapp, tmp_path):
    """Regression pin: base PNGs live under .wondershot/ and must not be
    scanned into the carousel."""
    seed_image_with_sidecar(tmp_path)
    g = make_gallery(qapp, tmp_path)
    g.rescan()
    from wondershot.gallery import PATH_ROLE
    names = [os.path.basename(g.model.item(r).data(PATH_ROLE))
             for r in range(g.model.rowCount())]
    assert names == ["shot.png"]


def test_rename_moves_sidecar_files(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g.rescan()
    g._select_silently(path)
    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("renamed.png", True)))
    g._rename_selected()
    new = os.path.join(str(tmp_path), "renamed.png")
    assert os.path.exists(new)
    assert os.path.exists(sidecar.sidecar_path(new))
    assert os.path.exists(sidecar.base_path(new, 0))
    assert sidecar.related_files(path) == []


def test_really_quit_autosaves_standalone_editor(qapp, tmp_path,
                                                 monkeypatch):
    """App quit: open standalone editors close (and autosave) silently."""
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QMessageBox
    from wondershot import sidecar
    from wondershot.editor import AddItemCommand
    from wondershot.items import RectItem
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: pytest.fail("quit must not prompt")))
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g.open_editor(path)
    win = g._windows[0]
    win.undo_stack.push(
        AddItemCommand(win, RectItem(QRectF(1, 1, 10, 10),
                                     QColor("red"), 2)))
    g.really_quit()
    data = json.load(open(sidecar.sidecar_path(path)))
    assert len(data["items"]) == 1, "standalone window autosaved on quit"
```

- [x] **Step 6.2 — run, expect failure:**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_gallery_sidecar.py -x -q
```

Expected: `test_trash_takes_sidecar_files_along` fails — the sidecar JSON/base remain after trashing.

- [x] **Step 6.3 — implement.** All edits in `wondershot/gallery.py`:

(a) Trash carries sidecar files. In `_trash_paths` (line 813), replace the staging loop block:

```python
        import shutil
        import time
        batch = []
        stage = self._staging_dir()
        for p in paths:
            staged = os.path.join(
                stage, f"{time.monotonic_ns()}-{os.path.basename(p)}")
            try:
                shutil.move(p, staged)
            except OSError:
                continue
            batch.append((staged, p))
```

with:

```python
        import shutil
        import time
        from . import sidecar
        batch = []
        primary = []
        stage = self._staging_dir()
        for p in paths:
            staged = os.path.join(
                stage, f"{time.monotonic_ns()}-{os.path.basename(p)}")
            try:
                shutil.move(p, staged)
            except OSError:
                continue
            batch.append((staged, p))
            primary.append(p)
            # sidecar JSON + base stack ride along in the same undo batch
            for extra in sidecar.related_files(p):
                staged_extra = os.path.join(
                    stage,
                    f"{time.monotonic_ns()}-{os.path.basename(extra)}")
                try:
                    shutil.move(extra, staged_extra)
                except OSError:
                    continue
                batch.append((staged_extra, extra))
```

and in the `if batch:` block below it, replace

```python
            n = len(batch)
            what = (os.path.basename(batch[0][1]) if n == 1
                    else f"{n} files")
```

with

```python
            n = len(primary)
            what = (os.path.basename(primary[0]) if n == 1
                    else f"{n} files")
```

(b) Undo-delete recreates `.wondershot/` and reports the image, not a sidecar. Replace the body of `_undo_delete` (line 855):

```python
    def _undo_delete(self) -> None:
        import shutil
        if not self._trash_undo:
            return
        restored = []
        for staged, original in self._trash_undo.pop():
            if os.path.exists(staged):
                try:
                    # sidecar files live under .wondershot/, which may be
                    # gone after the delete — recreate before restoring
                    os.makedirs(os.path.dirname(original), exist_ok=True)
                    shutil.move(staged, original)
                    restored.append(original)
                except OSError:
                    pass
        self.rescan()
        from .sidecar import SIDECAR_DIRNAME
        images = [r for r in restored
                  if os.path.basename(os.path.dirname(r))
                  != SIDECAR_DIRNAME]
        if images:
            self.select_path(images[0])
            self.editor.statusBar().showMessage(
                f"Restored {os.path.basename(images[0])}", 4000)
```

(c) Rename moves sidecars. In `_rename_selected` (line 884), inside the `try:` after `os.rename(old, new)`:

```python
        try:
            os.rename(old, new)
            from . import sidecar
            sidecar.rename_files(old, new)
            if self.editor.path == old:
                self.editor.path = new
        except OSError as e:
            QMessageBox.warning(self, "Wondershot", str(e))
```

(d) Quit closes standalone editors. Replace `really_quit` (line 1009):

```python
    def really_quit(self) -> None:
        # Standalone editors autosave library files in their closeEvent;
        # only a non-library file with a cancelled prompt can stop quit.
        for w in list(self._windows):
            if not w.close():
                return
        self.flush_trash()
        self._really_quit = True
        self.close()
```

- [x] **Step 6.4 — run, expect pass**, then full suite (especially `tests/test_gallery_trash.py` — its message-count behavior must be unchanged for plain images):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_gallery_sidecar.py tests/test_gallery_trash.py -x -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

- [x] **Step 6.5 — commit:**

```bash
git add wondershot/gallery.py tests/test_gallery_sidecar.py
git commit -m "gallery: trash/undo/rename carry sidecar files; quit closes standalone editors

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: ROADMAP note + final verification

**Files:**
- `ROADMAP.md` (modify)

GUI-only/doc-only glue — no failing-test step (nothing executable changes).

- [ ] **Step 7.1 — ROADMAP updates.** In `ROADMAP.md`:

(a) Under the `**Editor**` bullet list in "Working today", append:

```markdown
- Sidecar persistence: library images reopen with annotations as live
  objects (`<library>/.wondershot/<name>.json` + `<name>.base.<N>.png`
  stack, N=0 = original); destructive ops (crop/cut-out/bg-remove) are
  undoable on revisit; autosave on close/switch/quit — no save prompts
  for library files (kept for files opened from outside the library)
```

(b) Add a note where video work is tracked (after the `**Video**` list in "Working today"):

```markdown
- Video sidecars: not yet — videos have no annotation objects (range
  blur renders to a new file). Sidecars for video arrive together with
  video annotation objects.
```

- [ ] **Step 7.2 — full suite, twice (second run catches sidecar leakage between tests):**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Expected: all green — 186 pre-existing + the new serialization/sidecar/editor/gallery tests, 0 failures.

- [ ] **Step 7.3 — commit:**

```bash
git add ROADMAP.md
git commit -m "roadmap: sidecar persistence shipped; video sidecars wait on video objects

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Manual verification notes (for the consolidated desktop checklist)

Not part of this plan's execution; hand these up to the orchestrator's end-of-batch checklist:

1. Annotate a capture in the embedded editor, click another thumbnail, click back — annotations are selectable objects again; no prompt appeared at any point.
2. Crop + Remove BG an image, quit the app from the tray, relaunch, open the image, Ctrl+Z twice — bg-removal then the crop unwind.
3. Drag the image out of the carousel into a chat app — the flattened PNG (with annotations baked in) is what lands.
4. Trash an annotated image, Ctrl+Z over the strip — image AND its edit history are back.
5. `wondershot -e ~/Downloads/random.png`, scribble, close — the save prompt still appears (non-library path).
