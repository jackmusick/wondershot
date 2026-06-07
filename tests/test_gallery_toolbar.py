"""Toolbar diet (Jack, 2026-06-07): Trash/Folder/Pin/Open-in-window left
the main toolbar — pin floats on the carousel, the rest live in the card
context menu, Ctrl+Del still works."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tests.test_gallery_trash import make_gallery


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _toolbar_texts(g):
    return [a.text() for a in g.main_toolbar.actions() if a.text()]


def test_toolbar_has_no_trash_folder_pin_or_open_in_window(qapp, tmp_path):
    texts = _toolbar_texts(make_gallery(qapp, tmp_path))
    for gone in ("Trash", "Folder", "Pin", "Open in window"):
        assert gone not in texts, f"{gone} should have left the toolbar"


def test_ctrl_del_shortcut_survives_toolbar_removal(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    shortcuts = [s.toString() for a in g.actions() for s in a.shortcuts()]
    assert "Ctrl+Del" in shortcuts


def test_pin_button_floats_on_carousel_and_toggles_on_top(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    assert g.pin_btn.parent() is g.strip
    assert g.pin_btn.pos().x() < 10 and g.pin_btn.pos().y() < 10  # top-left
    assert not g.pin_btn.isChecked()
    g.pin_btn.setChecked(True)
    assert g.settings.pin_on_top is True
    assert bool(g.windowFlags() & Qt.WindowStaysOnTopHint)
    g.pin_btn.setChecked(False)
    assert g.settings.pin_on_top is False
    assert not (g.windowFlags() & Qt.WindowStaysOnTopHint)
