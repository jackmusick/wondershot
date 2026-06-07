"""Windows follows the OS light/dark scheme (theme.py); elsewhere no-op."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from wondershot import theme


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_dark_palette_is_actually_dark():
    p = theme.dark_palette()
    assert p.color(QPalette.Window).lightness() < 100
    assert p.color(QPalette.WindowText).lightness() > 150
    # disabled text must differ from normal (icons + labels gray out)
    assert (p.color(QPalette.Disabled, QPalette.ButtonText)
            != p.color(QPalette.Normal, QPalette.ButtonText))


def test_apply_is_noop_off_windows(qapp):
    before = qapp.style().objectName()
    theme.apply_system_theme(qapp, platform="linux")
    assert qapp.style().objectName() == before


def test_apply_on_windows_switches_to_fusion(qapp):
    theme.apply_system_theme(qapp, platform="win32")
    assert qapp.style().objectName().lower() == "fusion"


def test_dark_palette_secondary_text_is_readable():
    """Jack 2026-06-07: disabled/mid labels were unreadable in dark mode.
    Both must keep real contrast against the dark window."""
    p = theme.dark_palette()
    window_l = p.color(QPalette.Window).lightness()
    assert p.color(QPalette.Mid).lightness() - window_l > 80
    assert (p.color(QPalette.Disabled, QPalette.ButtonText).lightness()
            - window_l > 80)
