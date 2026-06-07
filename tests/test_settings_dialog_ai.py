import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    """Plain attribute bag covering everything SettingsDialog reads."""

    def __init__(self, tmp):
        self.library_dir = str(tmp)
        self.extra_dirs = []
        self.backend = "auto"
        self.camera_device = ""
        self.mic_device = ""
        self.mic_enabled = True
        self.noise_suppression = True
        self.copy_after_capture = True
        self.show_gallery_after_capture = True
        self.quick_bar_enabled = True
        self.quick_bar_timeout = 8
        self.share_provider = ""
        self.share_expiry_days = 7
        self.s3_endpoint = self.s3_region = self.s3_bucket = ""
        self.s3_access_key = self.s3_secret_key = ""
        self.azure_account = self.azure_container = self.azure_key = ""
        self.graph_client_id = ""
        self.graph_drive_id = ""
        self.graph_drive_label = ""
        self.ai_endpoint = "http://localhost:11434"
        self.ai_api_key = ""
        self.ai_model = "llava"


def test_ai_tab_fields_and_apply(qapp, tmp_path, monkeypatch):
    # keep msgraph token lookups away from the real home dir
    monkeypatch.setenv("WONDERSHOT_DATA_DIR", str(tmp_path))
    from wondershot.settings_dialog import SettingsDialog
    s = _FakeSettings(tmp_path)
    dlg = SettingsDialog(s)
    assert dlg.ai_endpoint.text() == "http://localhost:11434"
    assert dlg.ai_model.text() == "llava"
    dlg.ai_endpoint.setText("https://api.openai.com ")
    dlg.ai_api_key.setText(" sk-new ")
    dlg.ai_model.setText("gpt-4o-mini")
    dlg.apply()
    assert s.ai_endpoint == "https://api.openai.com"
    assert s.ai_api_key == "sk-new"
    assert s.ai_model == "gpt-4o-mini"


def test_ai_test_button_requires_endpoint_and_model(qapp, tmp_path,
                                                    monkeypatch):
    monkeypatch.setenv("WONDERSHOT_DATA_DIR", str(tmp_path))
    from wondershot.settings_dialog import SettingsDialog
    s = _FakeSettings(tmp_path)
    s.ai_endpoint = ""
    s.ai_model = ""
    dlg = SettingsDialog(s)
    dlg._ai_test()  # must not start a job / touch the network
    assert "endpoint" in dlg.ai_test_status.text()
