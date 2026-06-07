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
