import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from wondershot import imageops


@pytest.fixture(scope="session", autouse=True)
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def checkerboard(w=100, h=80, cell=10) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    for y in range(h):
        for x in range(w):
            on = ((x // cell) + (y // cell)) % 2 == 0
            img.setPixelColor(x, y, QColor("white") if on else QColor("black"))
    return img


def solid(w, h, color) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return img


def test_crop_basic():
    img = solid(100, 80, "red")
    out = imageops.crop(img, QRect(10, 10, 30, 20))
    assert out.width() == 30 and out.height() == 20
    assert out.pixelColor(0, 0) == QColor("red")


def test_crop_clamps_to_bounds():
    img = solid(100, 80, "blue")
    out = imageops.crop(img, QRect(90, 70, 50, 50))
    assert out.width() == 10 and out.height() == 10


def test_crop_empty_rect_returns_copy():
    img = solid(50, 50, "green")
    out = imageops.crop(img, QRect(200, 200, 10, 10))
    assert out.size() == img.size()


def test_pixelate_changes_region_only():
    img = checkerboard()
    rect = QRect(20, 20, 42, 30)
    # block=14 misaligns with the 10px checker cells so blocks average to gray
    out = imageops.pixelate(img, rect, block=14)
    assert out.size() == img.size()
    # outside the rect: unchanged
    assert out.pixelColor(5, 5) == img.pixelColor(5, 5)
    assert out.pixelColor(80, 70) == img.pixelColor(80, 70)
    # inside: checkerboard averaged to gray-ish, not pure black/white
    center = out.pixelColor(40, 35)
    assert center != QColor("white") and center != QColor("black")


def test_pixelated_patch_size():
    img = checkerboard()
    patch = imageops.pixelated_patch(img, QRect(10, 10, 30, 20))
    assert patch.width() == 30 and patch.height() == 20


def test_cut_out_horizontal_band():
    # rows 20..40 removed -> height shrinks by 20
    img = QImage(60, 100, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    for y in range(20, 40):
        for x in range(60):
            img.setPixelColor(x, y, QColor("blue"))
    out = imageops.cut_out(img, 20, 40, horizontal=True)
    assert out.height() == 80 and out.width() == 60
    # no blue rows survive
    for y in range(out.height()):
        assert out.pixelColor(30, y) == QColor("red")


def test_cut_out_vertical_band():
    img = QImage(100, 60, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    for x in range(30, 50):
        for y in range(60):
            img.setPixelColor(x, y, QColor("blue"))
    out = imageops.cut_out(img, 30, 50, horizontal=False)
    assert out.width() == 80 and out.height() == 60
    for x in range(out.width()):
        assert out.pixelColor(x, 30) == QColor("red")


def test_cut_out_swapped_args():
    img = solid(100, 100, "red")
    out = imageops.cut_out(img, 60, 40, horizontal=True)
    assert out.height() == 80


def test_cut_out_empty_band():
    img = solid(50, 50, "red")
    out = imageops.cut_out(img, 30, 30, horizontal=False)
    assert out.size() == img.size()


def test_rounded_corners_clears_corner_pixels():
    from wondershot.imageops import rounded_corners
    img = QImage(100, 80, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    out = rounded_corners(img, 20)
    assert out.pixelColor(0, 0).alpha() == 0, "corner must be transparent"
    assert out.pixelColor(50, 40).alpha() == 255, "center must be opaque"
    assert out.pixelColor(50, 0).alpha() == 255, "edge midpoint stays opaque"


def test_bottom_fade_gradient():
    from wondershot.imageops import bottom_fade
    img = QImage(60, 100, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("blue"))
    out = bottom_fade(img, 40)
    assert out.pixelColor(30, 10).alpha() == 255, "top untouched"
    assert out.pixelColor(30, 99).alpha() < 20, "bottom row ~transparent"
    mid = out.pixelColor(30, 80).alpha()
    assert 50 < mid < 220, f"midway through fade should be partial: {mid}"


def _require_widgets_app():
    # blurred_patch needs a full QApplication; in subset runs another
    # file may have created a bare QGuiApplication first.
    from PySide6.QtWidgets import QApplication
    if not isinstance(QApplication.instance(), QApplication):
        pytest.skip("a QGuiApplication-only test file ran first")


def _half_and_half(w=120, h=80):
    from PySide6.QtGui import QPainter
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("black"))
    p = QPainter(img)
    p.fillRect(w // 2, 0, w // 2, h, QColor("white"))
    p.end()
    return img


def test_blurred_patch_softens_the_boundary(qapp):
    from wondershot.imageops import blurred_patch
    _require_widgets_app()
    img = _half_and_half()
    r = QRect(30, 10, 60, 60)            # straddles the black/white edge
    patch = blurred_patch(img, r, radius=10)
    assert patch.size() == r.size()
    edge = patch.pixelColor(30, 30)      # on the boundary (x=60 in image)
    assert 40 < edge.red() < 215         # blended, neither pure b nor w
    far = patch.pixelColor(2, 30)        # deep in the black half
    assert far.red() < 40                # interior barely affected


def test_blurred_patch_clamps_and_empty(qapp):
    from wondershot.imageops import blurred_patch
    _require_widgets_app()
    img = _half_and_half()
    assert blurred_patch(img, QRect(500, 500, 10, 10)).isNull()
    patch = blurred_patch(img, QRect(110, 70, 50, 50), radius=6)
    assert patch.size() == QRect(110, 70, 50, 50).intersected(
        img.rect()).size()


def test_blurred_patch_never_segfaults_without_widgets_app():
    # Regression: under a bare QGuiApplication (e.g. a pytest subset run
    # where test_ocr.py is collected first), QGraphicsScene used to
    # segfault the interpreter. blurred_patch must return null instead.
    import subprocess
    import sys
    code = (
        "import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
        "from PySide6.QtCore import QRect\n"
        "from PySide6.QtGui import QColor, QGuiApplication, QImage\n"
        "app = QGuiApplication([])\n"
        "from wondershot.imageops import blurred_patch\n"
        "img = QImage(50, 50, QImage.Format_ARGB32_Premultiplied)\n"
        "img.fill(QColor('red'))\n"
        "print(blurred_patch(img, QRect(5, 5, 20, 20)).isNull())\n"
    )
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "True"
