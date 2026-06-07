import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect

from wondershot.video import Redaction, build_blur_filter


def test_single_redaction_graph():
    graph, out = build_blur_filter(
        [Redaction(QRect(100, 50, 200, 120), 2.0, 6.5)],
        video_w=640, video_h=360)
    assert out == "v0"
    assert "split=2[base][c0]" in graph
    assert "crop=200:120:100:50" in graph
    assert "boxblur=14" in graph
    assert "enable='between(t,2.000,6.500)'" in graph
    assert "overlay=100:50" in graph


def test_multiple_redactions_chain():
    reds = [
        Redaction(QRect(0, 0, 100, 100), 0.0, 3.0),
        Redaction(QRect(300, 200, 50, 50), 5.0, 9.0),
    ]
    graph, out = build_blur_filter(reds, video_w=640, video_h=360)
    assert out == "v1"
    assert "split=3[base][c0][c1]" in graph
    assert "[base][b0]overlay" in graph
    assert "[v0][b1]overlay" in graph


def test_odd_dimensions_rounded_even():
    graph, _ = build_blur_filter(
        [Redaction(QRect(11, 7, 101, 51), 0, 1)], video_w=640, video_h=360)
    # x,y floored to even; w,h floored to even
    assert "crop=100:50:10:6" in graph


def test_rect_clamped_to_frame():
    graph, _ = build_blur_filter(
        [Redaction(QRect(600, 340, 200, 100), 0, 1)],
        video_w=640, video_h=360)
    assert "crop=40:20:600:340" in graph

def test_pick_encoder_falls_back_when_ffmpeg_missing(monkeypatch):
    import wondershot.video as video
    from wondershot import ffmpegutil

    monkeypatch.setattr(video, "_encoder_cache", None)

    def boom(args, timeout=60):
        raise ffmpegutil.FfmpegMissing()

    monkeypatch.setattr(ffmpegutil, "run_ffmpeg", boom)
    assert video.pick_encoder() == "mpeg4"

def test_frame_grab_args():
    from wondershot.video import build_frame_grab_args
    args = build_frame_grab_args(
        "/lib/Recording.mp4", 12.3456, "/lib/.rendering/Recording-frame.png")
    assert args == ["-y", "-ss", "12.346", "-i", "/lib/Recording.mp4",
                    "-frames:v", "1", "/lib/.rendering/Recording-frame.png"]


def test_frame_grab_at_zero():
    from wondershot.video import build_frame_grab_args
    args = build_frame_grab_args("/lib/a.webm", 0.0, "/lib/a-frame.png")
    assert args[1:3] == ["-ss", "0.000"]


def test_frame_output_name():
    from wondershot.video import frame_output_name
    assert frame_output_name("Recording_20260606_1.mp4") == \
        "Recording_20260606_1-frame.png"
    assert frame_output_name("clip.webm") == "clip-frame.png"
