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


def make_editor(qapp, w=400, h=300):
    from wondershot.editor import EditorWindow
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    return EditorWindow(image=img)


def test_apply_redact_regions_adds_pixelate_items(qapp):
    from wondershot.items import PixelateItem
    ed = make_editor(qapp)
    n = ed.apply_redact_regions([QRect(10, 10, 100, 20),
                                 QRect(50, 100, 80, 16)])
    assert n == 2
    patches = [i for i in ed.scene.items() if isinstance(i, PixelateItem)]
    assert len(patches) == 2
    # non-destructive: base image untouched, single undo removes them all
    assert ed.base_image.pixelColor(15, 15) == QColor("white")
    ed.undo_stack.undo()
    patches = [i for i in ed.scene.items() if isinstance(i, PixelateItem)]
    assert patches == []


def test_apply_redact_regions_clamps_and_skips_tiny(qapp):
    from wondershot.items import PixelateItem
    ed = make_editor(qapp, 400, 300)
    n = ed.apply_redact_regions([
        QRect(390, 290, 100, 100),   # mostly off-canvas -> clamped, kept
        QRect(0, 0, 2, 2),           # degenerate -> skipped
        QRect(500, 500, 50, 50),     # fully off-canvas -> skipped
    ])
    assert n == 1
    patches = [i for i in ed.scene.items() if isinstance(i, PixelateItem)]
    assert len(patches) == 1
    assert patches[0].rect().right() <= 400


def test_redact_action_exists_on_toolbar(qapp):
    ed = make_editor(qapp)
    assert ed.redact_action.text() == "AI Redact"


def test_set_base_image_command_swaps_and_keeps_annotations(qapp):
    from PySide6.QtCore import QRectF
    from wondershot.editor import SetBaseImageCommand
    from wondershot.items import RectItem
    ed = make_editor(qapp, 400, 300)
    note = RectItem(QRectF(10, 10, 50, 50), QColor("red"), 4)
    ed.scene.addItem(note)
    new = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
    new.fill(QColor(0, 0, 0, 0))  # fully transparent (alpha preserved)
    ed.undo_stack.push(SetBaseImageCommand(ed, new, "remove background"))
    assert ed.base_image.pixelColor(5, 5).alpha() == 0
    assert note.scene() is ed.scene          # annotations survive (≠ Flatten)
    ed.undo_stack.undo()
    assert ed.base_image.pixelColor(5, 5) == QColor("white")
    assert note.scene() is ed.scene


def test_remove_bg_action_disabled_without_rembg(qapp, monkeypatch):
    import wondershot.bgremove as bgremove
    monkeypatch.setattr(bgremove, "available", lambda: False)
    ed = make_editor(qapp)
    assert not ed.bg_action.isEnabled()
    assert "ai-local" in ed.bg_action.toolTip()


def test_remove_bg_action_enabled_with_rembg(qapp, monkeypatch):
    import wondershot.bgremove as bgremove
    monkeypatch.setattr(bgremove, "available", lambda: True)
    ed = make_editor(qapp)
    assert ed.bg_action.isEnabled()


def test_bg_done_pushes_undoable_swap(qapp):
    ed = make_editor(qapp, 400, 300)
    new = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
    new.fill(QColor(0, 255, 0, 255))
    ed._bg_done(new, "")
    assert ed.base_image.pixelColor(5, 5) == QColor(0, 255, 0)
    ed.undo_stack.undo()
    assert ed.base_image.pixelColor(5, 5) == QColor("white")
