import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_record_countdown_default_off(tmp_path):
    s = make_settings(tmp_path)
    assert s.record_countdown == 0


def test_record_countdown_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.record_countdown = 3
    assert s.record_countdown == 3


def test_record_cursor_halo_default_off(tmp_path):
    s = make_settings(tmp_path)
    assert s.record_cursor_halo is False


def test_record_cursor_halo_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.record_cursor_halo = True
    assert s.record_cursor_halo is True
