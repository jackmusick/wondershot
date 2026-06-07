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
    from wondershot.stitch import qimage_to_rgb, to_gray
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
        assert detect_offset(prev, cur) == d


def test_detect_offset_identical_frames_is_zero():
    from wondershot.stitch import detect_offset, to_gray
    g = to_gray(make_rgb(height=200, width=40, seed=2))
    assert detect_offset(g, g) == 0


def test_detect_offset_unrelated_frames_is_none():
    """A scene change (different window content) must not stitch."""
    from wondershot.stitch import detect_offset, to_gray
    a = to_gray(make_rgb(height=200, width=40, seed=3))
    b = to_gray(make_rgb(height=200, width=40, seed=4))
    assert detect_offset(a, b) is None


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
