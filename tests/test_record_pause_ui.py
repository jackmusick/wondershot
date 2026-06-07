"""Pause/resume wiring across tray + toolbar (PURE, offscreen Qt).

Both controls relabel off recorder.paused_changed (single source of
truth, same discipline as 'stopping')."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.test_record_sync import make_app, fake_recording


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_pause_controls_disabled_when_idle(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    assert not a.pause_action.isEnabled()
    assert not a.gallery.pause_action.isEnabled()


def test_toolbar_pause_relabels_both_controls(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    fake_recording(a, tmp_path)
    # both pause controls live once recording starts
    assert a.pause_action.isEnabled()
    assert a.gallery.pause_action.isEnabled()
    a.gallery._toggle_pause()  # toolbar Pause
    assert a.recorder.paused is True
    assert "Resume" in a.pause_action.text()
    assert "Resume" in a.gallery.pause_action.text()


def test_tray_resume_relabels_both_controls(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    fake_recording(a, tmp_path)
    a.gallery._toggle_pause()      # pause first
    assert a.recorder.paused is True
    a.toggle_pause()               # tray Resume
    assert a.recorder.paused is False
    assert "Pause" in a.pause_action.text()
    assert "Pause" in a.gallery.pause_action.text()


def test_pause_controls_reset_on_finish(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    fake_recording(a, tmp_path)
    a.gallery._toggle_pause()
    a.recorder.finished.emit("/x.mp4")  # simulate finalize
    assert not a.pause_action.isEnabled()
    assert not a.gallery.pause_action.isEnabled()
