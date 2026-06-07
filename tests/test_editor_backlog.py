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
