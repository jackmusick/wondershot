import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_editor(qapp, w=400, h=300, color="white"):
    from grabbit.editor import EditorWindow
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return EditorWindow(image=img)


def test_flatten_includes_annotations(qapp):
    from grabbit.items import RectItem
    from PySide6.QtCore import QRectF
    ed = make_editor(qapp)
    ed.scene.addItem(RectItem(QRectF(50, 50, 100, 80), QColor("red"), 4))
    flat = ed.flattened()
    assert flat.size() == ed.base_image.size()
    # a pixel on the rect border should be red-ish
    c = flat.pixelColor(50, 90)
    assert c.red() > 150 and c.green() < 100


def test_crop_undo_restores(qapp):
    ed = make_editor(qapp, 400, 300)
    ed._apply_crop(QRect(100, 100, 150, 100))
    assert ed.base_image.width() == 150
    assert ed.base_image.height() == 100
    ed.undo_stack.undo()
    assert ed.base_image.width() == 400
    assert ed.base_image.height() == 300


def test_cutout_via_drags(qapp):
    ed = make_editor(qapp, 400, 300)
    from grabbit.editor import Tool
    ed.set_tool(Tool.CUTOUT_V)
    # vertical band removed -> narrower
    ed.begin_draw(QPointF(100, 150))
    ed.update_draw(QPointF(200, 160))
    ed.end_draw(QPointF(200, 160))
    assert ed.base_image.width() == 300
    assert ed.base_image.height() == 300

    ed2 = make_editor(qapp, 400, 300)
    ed2.set_tool(Tool.CUTOUT_H)
    ed2.begin_draw(QPointF(100, 100))
    ed2.end_draw(QPointF(150, 180))
    assert ed2.base_image.height() == 220
    assert ed2.base_image.width() == 400


def test_pixelate_item_resizes_like_shapes(qapp):
    from grabbit.items import PixelateItem
    ed = make_editor(qapp)
    ed._apply_pixelate(QRect(50, 50, 100, 80))
    item = [i for i in ed.scene.items() if isinstance(i, PixelateItem)][0]
    assert item.isSelected()          # newly drawn objects come selected
    assert len(ed._handles) == 4      # corner grips like rects
    from PySide6.QtCore import QPointF as P
    ed._handle_moved(item, "br", P(220, 200), {})
    assert item.rect().bottomRight() == P(220, 200)


def test_text_box_drag_sets_width(qapp):
    from grabbit.editor import Tool
    from grabbit.items import TextItem
    ed = make_editor(qapp)
    ed.set_tool(Tool.TEXT)
    ed.begin_draw(QPointF(40, 40))
    ed.update_draw(QPointF(240, 120))
    ed.end_draw(QPointF(240, 120))
    item = [i for i in ed.scene.items() if isinstance(i, TextItem)][0]
    assert item.textWidth() == 200
    # click (no drag) keeps auto-size
    ed.begin_draw(QPointF(300, 200))
    ed.end_draw(QPointF(301, 201))
    items = [i for i in ed.scene.items() if isinstance(i, TextItem)]
    assert any(t.textWidth() == -1 for t in items)


def test_step_counter_with_undo(qapp):
    from grabbit.editor import Tool
    ed = make_editor(qapp)
    ed.set_tool(Tool.STEP)
    ed.begin_draw(QPointF(50, 50))
    ed.begin_draw(QPointF(100, 50))
    assert ed.step_counter == 3
    ed.undo_stack.undo()
    assert ed.step_counter == 2


def test_arrow_drag_creates_undoable_item(qapp):
    from grabbit.editor import Tool
    from grabbit.items import is_annotation
    ed = make_editor(qapp)
    ed.set_tool(Tool.ARROW)
    ed.begin_draw(QPointF(20, 20))
    ed.update_draw(QPointF(200, 150))
    ed.end_draw(QPointF(200, 150))
    annotations = [i for i in ed.scene.items() if is_annotation(i)]
    assert len(annotations) == 1
    ed.undo_stack.undo()
    annotations = [i for i in ed.scene.items() if is_annotation(i)]
    assert len(annotations) == 0


def test_pixelate_adds_patch_item(qapp):
    from grabbit.editor import Tool
    from grabbit.items import PixelateItem
    ed = make_editor(qapp)
    ed._apply_pixelate(QRect(50, 50, 100, 80))
    patches = [i for i in ed.scene.items() if isinstance(i, PixelateItem)]
    assert len(patches) == 1


def test_resize_handles_lifecycle(qapp):
    from grabbit.items import RectItem, HandleItem
    from PySide6.QtCore import QRectF, QPointF
    ed = make_editor(qapp)
    rect = RectItem(QRectF(50, 50, 100, 80), QColor("red"), 4)
    ed.scene.addItem(rect)
    rect.setSelected(True)
    assert len(ed._handles) == 5  # 4 corners + rotate
    # drag the bottom-right grip outward
    ed._handle_moved(rect, "br", QPointF(200, 200), {})
    assert rect.rect().bottomRight() == QPointF(200, 200)
    assert not ed.undo_stack.isClean()
    rect.setSelected(False)
    assert len(ed._handles) == 0


def test_arrow_endpoint_resize(qapp):
    from grabbit.items import ArrowItem
    from PySide6.QtCore import QPointF
    ed = make_editor(qapp)
    arrow = ArrowItem(QPointF(10, 10), QPointF(100, 100), QColor("red"), 6)
    ed.scene.addItem(arrow)
    arrow.setSelected(True)
    assert len(ed._handles) == 2
    ed._handle_moved(arrow, "p2", QPointF(300, 50), {})
    p1, p2 = arrow.endpoints()
    assert p2 == QPointF(300, 50)
    assert p1 == QPointF(10, 10)


def test_text_font_resize(qapp):
    from grabbit.items import TextItem
    from PySide6.QtCore import QPointF
    ed = make_editor(qapp)
    t = TextItem(QPointF(20, 20), QColor("white"), 18)
    t.setPlainText("hello")
    ed.scene.addItem(t)
    h0 = t.boundingRect().height()
    ed._handle_moved(t, "font", QPointF(0, h0 * 2), {"font0": 18.0, "h0": h0})
    assert t.font().pointSize() == 36


def test_rotation_handle(qapp):
    from grabbit.items import RectItem
    from PySide6.QtCore import QRectF, QPointF
    ed = make_editor(qapp)
    rect = RectItem(QRectF(100, 100, 100, 60), QColor("red"), 4)
    ed.scene.addItem(rect)
    rect.setSelected(True)
    roles = {h.role for h in ed._handles}
    assert "rotate" in roles
    # drag the rotate grip to the right of center -> ~90 degrees
    c = rect.rect().center()
    ed._handle_moved(rect, "rotate", QPointF(c.x() + 50, c.y()), {})
    assert abs(rect.rotation() - 90) < 1


def test_save_emits_signal(qapp, tmp_path):
    ed = make_editor(qapp)
    target = str(tmp_path / "out.png")
    ed.path = target
    got = []
    ed.saved.connect(got.append)
    ed.save()
    assert os.path.exists(target)
    assert got == [target]
    assert ed.undo_stack.isClean()
