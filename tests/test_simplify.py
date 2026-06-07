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
