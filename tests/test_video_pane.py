import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    s.library_dir = str(tmp_path / "lib")
    return s


def make_pane(qapp, tmp_path, **prefs):
    settings = make_settings(tmp_path)
    for key, val in prefs.items():
        setattr(settings, key, val)
    from wondershot.video import VideoPane
    return VideoPane(settings), settings


class FakeSignal:
    def connect(self, *_):
        pass


class FakeProc:
    """Stands in for QProcess so no ffmpeg is ever spawned."""
    last = None

    def __init__(self, parent=None):
        self.finished = FakeSignal()

    def start(self, prog, args):
        FakeProc.last = (prog, list(args))


def patch_proc(monkeypatch):
    import wondershot.video as video
    FakeProc.last = None
    monkeypatch.setattr(video, "QProcess", FakeProc)
    monkeypatch.setattr(video.ffmpegutil, "ffmpeg_path",
                        lambda: "/usr/bin/ffmpeg")
    # _apply_blurs calls pick_encoder(), which probes via
    # ffmpegutil.run_ffmpeg (a real subprocess.run) — stub it so tests
    # never execute ffmpeg.
    monkeypatch.setattr(video, "pick_encoder", lambda: "libx264")
    return video


def test_blur_strength_spin_defaults(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.blur_strength_spin.value() == 14


def test_blur_strength_spin_reads_saved_default(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path, video_blur_strength=22)
    assert pane.blur_strength_spin.value() == 22


def test_blur_strength_spin_persists(qapp, tmp_path):
    pane, settings = make_pane(qapp, tmp_path)
    pane.blur_strength_spin.setValue(30)
    assert settings.video_blur_strength == 30


def test_blur_strength_controls_track_apply_visibility(qapp, tmp_path):
    import wondershot.video as video
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.blur_strength_spin.isHidden()
    pane.redactions.append(video.Redaction(QRect(0, 0, 50, 50), 0.0, 2.0))
    pane._rebuild_rows()
    assert not pane.blur_strength_spin.isHidden()
    pane.redactions.clear()
    pane._rebuild_rows()
    assert pane.blur_strength_spin.isHidden()


def test_apply_blurs_passes_strength_to_filter(qapp, tmp_path, monkeypatch):
    video = patch_proc(monkeypatch)
    pane, _ = make_pane(qapp, tmp_path)
    pane.path = "/tmp/fake.mp4"
    pane.redactions.append(video.Redaction(QRect(0, 0, 100, 100), 0.0, 2.0))
    pane.blur_strength_spin.setValue(27)
    captured = {}

    def fake_filter(reds, blur=14, video_w=0, video_h=0):
        captured["blur"] = blur
        return "[0:v]null[vout]", "vout"

    monkeypatch.setattr(video, "build_blur_filter", fake_filter)
    pane._apply_blurs()
    assert captured["blur"] == 27
    assert FakeProc.last is not None          # render was started
    assert FakeProc.last[0] == "/usr/bin/ffmpeg"  # via ffmpegutil seam
