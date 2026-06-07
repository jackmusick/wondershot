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


def test_gif_mode_creates_full_range_span(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.gif_fps_spin.isHidden()
    pane.gif_btn.setChecked(True)
    assert pane.gif_range is not None
    assert pane.gif_range.start == 0.0
    assert pane.gif_range.end >= 0.1
    assert pane.spans() == [pane.gif_range]
    assert pane.single_span() is pane.gif_range
    assert not pane.gif_fps_spin.isHidden()
    assert not pane.gif_width_spin.isHidden()
    assert not pane.gif_apply_btn.isHidden()
    pane.gif_btn.setChecked(False)
    assert pane.gif_range is None
    assert pane.gif_fps_spin.isHidden()


def test_single_span_prefers_trim_and_preserves_trim_behavior(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.single_span() is None
    pane.trim_btn.setChecked(True)
    assert pane.single_span() is pane.trim
    assert pane.spans() == [pane.trim]          # shipped trim contract
    assert pane.active_redaction() is pane.trim


def test_gif_and_trim_modes_are_mutually_exclusive(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    pane.gif_btn.setChecked(True)
    pane.trim_btn.setChecked(True)
    assert pane.gif_range is None and pane.trim is not None
    assert not pane.gif_btn.isChecked()
    pane.gif_btn.setChecked(True)
    assert pane.trim is None and pane.gif_range is not None
    assert not pane.trim_btn.isChecked()


def test_gif_mode_blocked_by_pending_blurs(qapp, tmp_path):
    import wondershot.video as video
    pane, _ = make_pane(qapp, tmp_path)
    pane.redactions.append(video.Redaction(QRect(0, 0, 50, 50), 0.0, 2.0))
    pane.gif_btn.setChecked(True)
    assert pane.gif_range is None
    assert not pane.gif_btn.isChecked()


def test_gif_option_spins_default_and_persist(qapp, tmp_path):
    pane, settings = make_pane(qapp, tmp_path, gif_fps=18, gif_max_width=960)
    assert pane.gif_fps_spin.value() == 18
    assert pane.gif_width_spin.value() == 960
    pane.gif_fps_spin.setValue(15)
    pane.gif_width_spin.setValue(640)
    assert settings.gif_fps == 15
    assert settings.gif_max_width == 640


def test_convert_gif_uses_options_and_range(qapp, tmp_path, monkeypatch):
    patch_proc(monkeypatch)
    pane, _ = make_pane(qapp, tmp_path)
    pane.path = "/tmp/fake.mp4"
    pane.gif_btn.setChecked(True)
    pane.gif_fps_spin.setValue(20)
    pane.gif_width_spin.setValue(480)
    pane.gif_range.start, pane.gif_range.end = 1.0, 3.5
    pane._convert_gif()
    prog, args = FakeProc.last
    assert prog == "/usr/bin/ffmpeg"            # via ffmpegutil seam
    assert args[args.index("-ss") + 1] == "1.000"
    assert args[args.index("-to") + 1] == "3.500"
    vf = args[args.index("-vf") + 1]
    assert "fps=20," in vf and "min(480,iw)" in vf


def test_convert_gif_full_range_omits_seek(qapp, tmp_path, monkeypatch):
    patch_proc(monkeypatch)
    pane, _ = make_pane(qapp, tmp_path)
    pane.path = "/tmp/fake.mp4"
    pane.gif_btn.setChecked(True)   # untouched span == whole video
    pane._convert_gif()
    _, args = FakeProc.last
    assert "-ss" not in args and "-to" not in args
