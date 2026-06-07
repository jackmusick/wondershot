import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage


@pytest.fixture(scope="session", autouse=True)
def qapp():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def make_rgb(height=60, width=40, seed=7) -> np.ndarray:
    """Deterministic noise image: every row is unique."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def to_gray_noise(height, width, seed):
    from wondershot.stitch import to_gray
    return to_gray(make_rgb(height, width, seed))


def test_rgb_qimage_roundtrip_exact():
    from wondershot.stitch import qimage_to_rgb, rgb_to_qimage
    arr = make_rgb()
    img = rgb_to_qimage(arr)
    assert img.width() == 40 and img.height() == 60
    assert img.format() == QImage.Format_RGB888
    back = qimage_to_rgb(img)
    assert np.array_equal(arr, back)


def test_qimage_to_rgb_handles_other_formats():
    """Real frames arrive as RGB32/ARGB32 from the appsink; conversion
    must normalize any input format to (H, W, 3) RGB."""
    from wondershot.stitch import qimage_to_rgb
    img = QImage(10, 8, QImage.Format_ARGB32_Premultiplied)
    img.fill(0xFF336699)  # opaque RGB(0x33, 0x66, 0x99)
    arr = qimage_to_rgb(img)
    assert arr.shape == (8, 10, 3)
    assert tuple(arr[0, 0]) == (0x33, 0x66, 0x99)


def test_to_gray_shape_and_range():
    from wondershot.stitch import to_gray
    arr = make_rgb()
    g = to_gray(arr)
    assert g.shape == (60, 40)
    assert g.dtype == np.float32
    assert 0.0 <= g.min() and g.max() <= 255.0


def test_detect_offset_finds_scroll():
    """cur is prev scrolled up by d rows: cur[y] == prev[y + d]."""
    from wondershot.stitch import detect_offset, to_gray
    tall = make_rgb(height=300, width=40, seed=1)
    prev = to_gray(tall[0:200])
    for d in (1, 17, 60, 130):
        cur = to_gray(tall[d:200 + d])
        got, conf = detect_offset(prev, cur)
        assert got == d
        assert conf >= 0.5


def test_detect_offset_identical_frames_is_zero():
    from wondershot.stitch import detect_offset, to_gray
    g = to_gray(make_rgb(height=200, width=40, seed=2))
    got, conf = detect_offset(g, g)
    assert got == 0
    assert conf >= 0.5


def test_detect_offset_unrelated_frames_is_none():
    """A scene change (different window content) must not stitch."""
    from wondershot.stitch import detect_offset, to_gray
    a = to_gray(make_rgb(height=200, width=40, seed=3))
    b = to_gray(make_rgb(height=200, width=40, seed=4))
    assert detect_offset(a, b) == (None, 0.0)


def test_textured_xs_skips_flat_bands():
    """Band x-positions must come from textured columns only."""
    from wondershot.stitch import textured_xs
    strip = np.zeros((64, 300), dtype=np.float32)   # flat everywhere
    strip[:, 100:148] = make_rgb(64, 48, seed=20).mean(axis=2)
    xs = textured_xs(strip, band_w=48, n=5, var_min=100.0)
    # linspace(0, 252, 5) -> [0, 63, 126, 189, 252]; x=126 sits inside
    # the textured block and x=63 overlaps it by 11 columns (mixture
    # variance ~3000, still >= var_min) — both may survive; x=0, 189,
    # 252 are fully flat and must not.
    assert xs
    assert all(60 <= x <= 148 for x in xs)


def test_textured_xs_narrow_image_uses_single_band():
    from wondershot.stitch import textured_xs
    strip = to_gray_noise(64, 40, seed=21)
    assert textured_xs(strip, band_w=48, n=5, var_min=100.0) == [0]


def test_detect_offset_blank_frame_is_low_confidence():
    """A featureless frame must not produce a confident offset.
    (v1's documented limitation was uniform-band false matches; v2
    must refuse outright: no textured bands survive var_min, and the
    full-overlap fallback against a noise prev can't beat threshold/2.)"""
    from wondershot.stitch import detect_offset, to_gray
    prev = to_gray(make_rgb(height=200, width=120, seed=22))
    blank = np.full((200, 120), 255.0, dtype=np.float32)
    d, conf = detect_offset(prev, blank)
    assert d is None
    assert conf == 0.0


def test_detect_offset_wide_frame_multiband_consensus():
    """Wide noise: all 5 bands textured, all agree -> confidence 1.0."""
    from wondershot.stitch import detect_offset, to_gray
    tall = make_rgb(height=400, width=300, seed=23)
    prev = to_gray(tall[0:250])
    cur = to_gray(tall[37:287])
    assert detect_offset(prev, cur) == (37, 1.0)


def _frame_with_chrome(content: np.ndarray, header: np.ndarray,
                       footer: np.ndarray) -> np.ndarray:
    return np.vstack([header, content, footer])


def test_static_bands_detects_header_and_footer():
    from wondershot.stitch import static_bands, to_gray
    tall = make_rgb(height=400, width=40, seed=5)
    header = make_rgb(height=15, width=40, seed=6)
    footer = make_rgb(height=25, width=40, seed=7)
    prev = to_gray(_frame_with_chrome(tall[0:200], header, footer))
    cur = to_gray(_frame_with_chrome(tall[50:250], header, footer))
    assert static_bands(prev, cur) == (15, 25)


def test_static_bands_none_when_everything_scrolls():
    from wondershot.stitch import static_bands, to_gray
    tall = make_rgb(height=400, width=40, seed=8)
    prev = to_gray(tall[0:200])
    cur = to_gray(tall[50:250])
    assert static_bands(prev, cur) == (0, 0)


def test_static_bands_identical_frames_returns_zero():
    """Whole frame 'static' is meaningless — refuse, don't crop all."""
    from wondershot.stitch import static_bands, to_gray
    g = to_gray(make_rgb(height=200, width=40, seed=9))
    assert static_bands(g, g) == (0, 0)


def _window_frames(tall: np.ndarray, viewport: int, offsets):
    """Simulate a user scrolling: viewport-sized windows of a tall page."""
    from wondershot.stitch import rgb_to_qimage
    return [rgb_to_qimage(tall[o:o + viewport]) for o in offsets]


def test_stitcher_reconstructs_tall_image():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb
    tall = make_rgb(height=900, width=120, seed=10)
    offsets = [0, 30, 60, 95, 140, 200, 260, 300]
    st = ScrollStitcher()
    for f in _window_frames(tall, viewport=200, offsets=offsets):
        st.add_frame(f)
    out = qimage_to_rgb(st.result())
    expected = tall[0:offsets[-1] + 200]   # rows 0..500
    assert out.shape == expected.shape
    assert np.array_equal(out, expected)
    assert st.frames_used == len(offsets)


def test_stitcher_drops_no_motion_frames():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb
    tall = make_rgb(height=600, width=80, seed=11)
    frames = _window_frames(tall, 200, [0, 0, 40, 40, 40, 80])
    st = ScrollStitcher()
    for f in frames:
        st.add_frame(f)
    out = qimage_to_rgb(st.result())
    assert np.array_equal(out, tall[0:280])
    assert st.frames_dropped == 3


def test_stitcher_strips_fixed_header_and_footer():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    tall = make_rgb(height=700, width=100, seed=12)
    header = make_rgb(height=18, width=100, seed=13)
    footer = make_rgb(height=22, width=100, seed=14)
    st = ScrollStitcher()
    for o in [0, 35, 70, 110]:
        st.add_frame(rgb_to_qimage(
            _frame_with_chrome(tall[o:o + 160], header, footer)))
    out = qimage_to_rgb(st.result())
    assert np.array_equal(out, tall[0:110 + 160])


def test_stitcher_single_frame_passthrough():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    arr = make_rgb(height=150, width=60, seed=15)
    st = ScrollStitcher()
    st.add_frame(rgb_to_qimage(arr))
    assert np.array_equal(qimage_to_rgb(st.result()), arr)


def test_stitcher_empty_result_is_null_image():
    from wondershot.stitch import ScrollStitcher
    assert ScrollStitcher().result().isNull()


def test_stitcher_scene_change_does_not_append_garbage():
    """detect_offset -> None must not vstack unrelated content."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    a = make_rgb(height=200, width=60, seed=16)
    b = make_rgb(height=200, width=60, seed=17)
    st = ScrollStitcher()
    st.add_frame(rgb_to_qimage(a))
    st.add_frame(rgb_to_qimage(b))
    assert np.array_equal(qimage_to_rgb(st.result()), a)
    assert st.frames_dropped == 1
