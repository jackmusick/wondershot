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

def test_trim_output_name_keeps_container_on_copy():
    from wondershot.video import trim_output_name
    assert trim_output_name("Rec.webm", reencode=False) == "Rec-trimmed.webm"
    assert trim_output_name("Rec.mp4", reencode=False) == "Rec-trimmed.mp4"


def test_trim_output_name_reencode_is_mp4():
    from wondershot.video import trim_output_name
    assert trim_output_name("Rec.webm", reencode=True) == "Rec-trimmed.mp4"
    assert trim_output_name("Rec.mkv", reencode=True) == "Rec-trimmed.mp4"


def test_trim_args_stream_copy():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.mp4", 1.0, 8.5,
                           "/l/.rendering/in-trimmed.mp4", reencode=False)
    i = args.index("-i")
    # -ss AND -to as input options (before -i): both absolute timestamps
    assert args[:i] == ["-y", "-ss", "1.000", "-to", "8.500"]
    assert args[i + 1] == "/l/in.mp4"
    c = args.index("-c")
    assert args[c + 1] == "copy"
    assert "-movflags" in args  # mp4 output gets +faststart
    assert args[-1] == "/l/.rendering/in-trimmed.mp4"


def test_trim_args_copy_to_webm_has_no_movflags():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.webm", 0.0, 2.0,
                           "/l/.rendering/in-trimmed.webm", reencode=False)
    assert "-movflags" not in args


def test_trim_args_reencode_x264():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.webm", 0.5, 3.25,
                           "/l/.rendering/in-trimmed.mp4",
                           reencode=True, encoder="libx264")
    v = args.index("-c:v")
    assert args[v + 1] == "libx264"
    assert "-crf" in args and "-preset" in args
    a = args.index("-c:a")
    assert args[a + 1] == "aac"
    assert "-movflags" in args


def test_trim_args_reencode_fallback_encoder():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.mp4", 0.0, 1.0,
                           "/l/.rendering/in-trimmed.mp4",
                           reencode=True, encoder="mpeg4")
    assert "-q:v" in args and "-crf" not in args


def test_blur_strength_parameter():
    graph, _ = build_blur_filter(
        [Redaction(QRect(0, 0, 100, 100), 0.0, 1.0)],
        blur=30, video_w=640, video_h=360)
    assert "boxblur=30" in graph
    assert "boxblur=14" not in graph


def test_gif_args_defaults():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/.rendering/in.gif")
    assert args[:3] == ["-y", "-i", "/l/in.mp4"]
    vf = args[args.index("-vf") + 1]
    assert vf.startswith("fps=12,scale='min(720,iw)':-1:flags=lanczos")
    assert "palettegen" in vf and "paletteuse" in vf
    assert args[-1] == "/l/.rendering/in.gif"


def test_gif_args_custom_fps_and_width():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/o.gif", fps=24, max_width=480)
    vf = args[args.index("-vf") + 1]
    assert "fps=24," in vf
    assert "min(480,iw)" in vf


def test_gif_args_range_is_input_seek():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/o.gif", start_s=1.5, end_s=4.0)
    i = args.index("-i")
    # -ss AND -to before -i: absolute source timestamps, same contract
    # as build_trim_args
    assert args[:i] == ["-y", "-ss", "1.500", "-to", "4.000"]


def test_gif_args_no_partial_range():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/o.gif", start_s=1.0, end_s=None)
    assert "-ss" not in args and "-to" not in args
