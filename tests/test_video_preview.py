import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QSize, QSettings
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def edge_image(w=64, h=64):
    """Left half black, right half white — a hard vertical edge at x=w/2."""
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("black"))
    p = QPainter(img)
    p.fillRect(w // 2, 0, w // 2, h, QColor("white"))
    p.end()
    return img


def test_preview_blur_preserves_size(qapp):
    from wondershot.video import preview_blur
    img = QImage(64, 48, QImage.Format_RGB32)
    img.fill(QColor("red"))
    out = preview_blur(img, 14)
    assert out.size() == QSize(64, 48)


def test_preview_blur_softens_hard_edge(qapp):
    from wondershot.video import preview_blur
    out = preview_blur(edge_image(), 14)
    edge = out.pixelColor(32, 32)
    assert 10 < edge.red() < 245   # intermediate gray, not pure black/white


def test_preview_blur_keeps_flat_color_flat(qapp):
    from wondershot.video import preview_blur
    img = QImage(40, 40, QImage.Format_RGB32)
    img.fill(QColor(200, 60, 30))
    out = preview_blur(img, 20)
    c = out.pixelColor(20, 20)
    assert abs(c.red() - 200) <= 2
    assert abs(c.green() - 60) <= 2
    assert abs(c.blue() - 30) <= 2


def test_preview_blur_radius_zero_is_identity(qapp):
    from wondershot.video import preview_blur
    img = QImage(16, 16, QImage.Format_RGB32)
    img.fill(QColor("blue"))
    assert preview_blur(img, 0) is img


def test_preview_blur_tiny_image_is_identity(qapp):
    from wondershot.video import preview_blur
    img = QImage(1, 1, QImage.Format_RGB32)
    img.fill(QColor("blue"))
    assert preview_blur(img, 14) is img


def test_overlay_paints_blurred_region(qapp, tmp_path):
    """Integration: the frost rect actually shows blurred frame pixels."""
    import wondershot.video as video
    from wondershot.settings import Settings
    settings = Settings.__new__(Settings)
    settings._s = QSettings(str(tmp_path / "t.ini"), QSettings.IniFormat)
    settings.library_dir = str(tmp_path / "lib")
    pane = video.VideoPane(settings)

    frame = edge_image(64, 64)
    pane.frozen_mode = lambda: True              # instance overrides:
    pane.last_frame_image = lambda: frame        # bypass the real player
    # A standalone overlay (not glued inside VideoStack): render() delivers
    # the never-shown ancestors' deferred resize events mid-render, and
    # VideoStack.resizeEvent would snap pane.overlay back to the stack rect.
    overlay = video.RedactOverlay(None, pane)
    overlay._video_size = lambda: QSize(64, 64)
    overlay.resize(64, 64)
    # span includes t=0 (player position is 0 with no media)
    pane.redactions.append(
        video.Redaction(QRect(8, 8, 48, 48), 0.0, 5.0))

    target = QImage(64, 64, QImage.Format_RGB32)
    target.fill(QColor("green"))
    overlay.render(target)

    # Inside the redaction at the black/white edge: blurred gray.
    inside = target.pixelColor(32, 32)
    assert 10 < inside.red() < 245
    # Outside the redaction the raw frame shows through: pure-ish white.
    outside = target.pixelColor(60, 4)
    assert outside.red() > 245
