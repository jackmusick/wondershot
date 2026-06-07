"""Scroll sessions must request a fresh portal pick (ignore the
recorder's persisted ScreenCast restore token) and must never
overwrite that token with the scroll session's grant — Jack's first
run captured the wrong window because the spike inherited both."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


class FakeSettings:
    def __init__(self):
        self.library_dir = "/tmp"
        self.mic_enabled = False
        self.mic_device = ""
        self.noise_suppression = True
        self.screencast_token = "recorder-grant"


def test_scroll_source_requests_fresh_pick(qapp):
    from wondershot.scrollsource import ScreenCastFrameSource
    source = ScreenCastFrameSource(FakeSettings())
    assert source._restore_token() == ""


def test_scroll_source_never_persists_its_grant(qapp):
    from wondershot.scrollsource import ScreenCastFrameSource
    settings = FakeSettings()
    source = ScreenCastFrameSource(settings)
    source._save_restore_token("scroll-grant")
    assert settings.screencast_token == "recorder-grant"
