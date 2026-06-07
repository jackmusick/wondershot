import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    """A Settings whose backing store is a throwaway ini file.

    Settings.__init__ opens the real user config (and runs a migration),
    so bypass it and inject a temp QSettings instead.
    """
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_ai_settings_default_empty(tmp_path):
    s = make_settings(tmp_path)
    assert s.ai_endpoint == ""
    assert s.ai_api_key == ""
    assert s.ai_model == ""


def test_ai_settings_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.ai_endpoint = "http://localhost:11434"
    s.ai_api_key = "sk-test"
    s.ai_model = "llava"
    assert s.ai_endpoint == "http://localhost:11434"
    assert s.ai_api_key == "sk-test"
    assert s.ai_model == "llava"
