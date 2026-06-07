import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_video_tool_defaults(tmp_path):
    s = make_settings(tmp_path)
    assert s.video_blur_strength == 14
    assert s.gif_fps == 12
    assert s.gif_max_width == 720


def test_video_tool_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.video_blur_strength = 30
    s.gif_fps = 20
    s.gif_max_width = 480
    assert s.video_blur_strength == 30
    assert s.gif_fps == 20
    assert s.gif_max_width == 480


def test_video_tool_values_survive_string_storage(tmp_path):
    # QSettings round-trips ints as strings; the properties must coerce.
    s = make_settings(tmp_path)
    s._s.setValue("video_blur_strength", "25")
    s._s.setValue("gif_fps", "8")
    s._s.setValue("gif_max_width", "1280")
    assert s.video_blur_strength == 25
    assert s.gif_fps == 8
    assert s.gif_max_width == 1280
