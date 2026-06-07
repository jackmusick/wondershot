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
