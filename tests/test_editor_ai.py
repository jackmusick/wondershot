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
