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


def test_apply_writes_quick_bar_settings(qapp, tmp_path):
    from wondershot.settings_dialog import SettingsDialog
    s = make_settings(tmp_path)
    s.library_dir = str(tmp_path)  # keep the dialog off the real library
    dlg = SettingsDialog(s)
    assert dlg.quickbar_check.isChecked() is True
    assert dlg.quickbar_timeout.value() == 8
    dlg.quickbar_check.setChecked(False)
    dlg.quickbar_timeout.setValue(20)
    dlg.apply()
    assert s.quick_bar_enabled is False
    assert s.quick_bar_timeout == 20
