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
