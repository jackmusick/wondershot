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
