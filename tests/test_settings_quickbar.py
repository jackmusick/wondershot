import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_quick_bar_defaults(tmp_path):
    s = make_settings(tmp_path)
    assert s.quick_bar_enabled is True
    assert s.quick_bar_timeout == 8


def test_quick_bar_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.quick_bar_enabled = False
    s.quick_bar_timeout = 15
    assert s.quick_bar_enabled is False
    assert s.quick_bar_timeout == 15
