import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect

from grabbit.video import Redaction, build_blur_filter


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
