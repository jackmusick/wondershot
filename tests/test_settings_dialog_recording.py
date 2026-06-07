import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_apply_writes_record_countdown(qapp, tmp_path):
    from wondershot.settings_dialog import SettingsDialog
    s = make_settings(tmp_path)
    s.library_dir = str(tmp_path)  # keep the dialog off the real library
    dlg = SettingsDialog(s)
    assert dlg.countdown_spin.value() == 0
    assert dlg.countdown_spin.minimum() == 0
    assert dlg.countdown_spin.maximum() == 10
    dlg.countdown_spin.setValue(5)
    dlg.apply()
    assert s.record_countdown == 5
