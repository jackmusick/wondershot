"""Either record control (tray menu / gallery toolbar) must stop a
recording, and BOTH must reset — recorder signals drive all stop UI.

Regression for: tray Stop did nothing after a toolbar-initiated stop —
the toolbar path never touched the tray action (stale enabled 'Stop
recording'), and the second stop() was a silent no-op (record.py)."""
import itertools
import os
import subprocess
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="drives POSIX subprocesses")

_counter = itertools.count()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []

    def __getattr__(self, k):
        if k in ("stroke_width", "font_size", "capture_delay",
                 "share_expiry_days", "quick_bar_timeout"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick", "capture_cursor",
                                      "record")) else ""


def make_app(qapp, tmp_path, monkeypatch):
    import wondershot.app as appmod
    from wondershot.hotkey import NullHotkeyBackend
    # NEVER touch the real single-instance socket or real QSettings.
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-test-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings",
                        lambda: _Settings(str(tmp_path)))
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    return appmod.GrabbitApp(qapp)


def fake_recording(a, tmp_path):
    """Put the real recorder into an in-flight state around a live proc."""
    proc = subprocess.Popen(["sleep", "30"])
    rec = a.recorder
    rec._proc = proc
    rec.recording = True
    d = tmp_path / ".rendering"
    d.mkdir(exist_ok=True)
    rec._tmp = str(d / "r.mp4")
    rec._out = str(tmp_path / "r.mp4")
    (d / "r.mp4").write_bytes(b"x")
    a._on_recording_started()  # what recorder.started would have done
    return proc


def wait_until(qapp, cond, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_toolbar_stop_resets_tray_action(qapp, tmp_path, monkeypatch):
    """Jack's bug: after a TOOLBAR stop, the tray item stayed enabled and
    stale; clicking it did nothing."""
    a = make_app(qapp, tmp_path, monkeypatch)
    proc = fake_recording(a, tmp_path)
    try:
        a.gallery._toggle_record()  # toolbar Stop
        # the TRAY action must immediately show the stop is in flight
        assert not a.record_action.isEnabled()
        assert a.record_action.text() == "Stopping…"
        assert not a.gallery.record_action.isEnabled()
        # sleep exits on SIGINT (rc != 0) -> failed path; BOTH reset
        assert wait_until(qapp, lambda: a.record_action.isEnabled(), 8)
        assert a.record_action.text() == "Record screen…"
        assert a.gallery.record_action.isEnabled()
        assert a.gallery.record_action.text() == "Record"
    finally:
        proc.poll() is not None or (proc.kill(), proc.wait())


def test_tray_stop_resets_toolbar_action(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    proc = fake_recording(a, tmp_path)
    try:
        a.toggle_recording()  # tray Stop
        assert not a.gallery.record_action.isEnabled()
        assert a.gallery.record_action.text() == "Stopping…"
        assert not a.record_action.isEnabled()
        assert wait_until(qapp, lambda: a.record_action.isEnabled(), 8)
        assert a.gallery.record_action.text() == "Record"
        assert a.record_action.text() == "Record screen…"
    finally:
        proc.poll() is not None or (proc.kill(), proc.wait())


def test_toolbar_record_start_routes_through_app(qapp, tmp_path,
                                                 monkeypatch):
    """Starts funnel through the app coordinator (where the countdown
    gate will live), from every entry point."""
    a = make_app(qapp, tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a.gallery._toggle_record()       # toolbar Record while idle
    assert started == [1]
    a.toggle_recording()             # tray Record while idle
    assert started == [1, 1]
