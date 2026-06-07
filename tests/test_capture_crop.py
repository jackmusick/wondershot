import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    backend = "spectacle"
    capture_cursor = False
    capture_delay = 0

    def __init__(self, library_dir):
        self.library_dir = library_dir


def _manager(tmp_path):
    from wondershot.capture import CaptureManager
    return CaptureManager(_Settings(str(tmp_path)))


def _png(tmp_path, w=200, h=100):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(Qt.blue)
    p = str(tmp_path / "full.png")
    img.save(p)
    return p


def test_finish_passthrough_without_pending_crop(qapp, tmp_path):
    m = _manager(tmp_path)
    p = _png(tmp_path)
    got = []
    m.captured.connect(got.append)
    m._finish(p)
    assert got == [p]
    assert QImage(p).width() == 200  # untouched


def test_finish_crops_and_clears_pending(qapp, tmp_path):
    m = _manager(tmp_path)
    p = _png(tmp_path)
    got = []
    m.captured.connect(got.append)
    m._pending_crop = QRect(10, 20, 50, 40)
    m._crop_virtual = QRect(0, 0, 200, 100)  # test seam: explicit virtual
    m._finish(p)
    assert got == [p]
    out = QImage(p)
    assert (out.width(), out.height()) == (50, 40)
    assert m._pending_crop is None  # one-shot


def test_finish_emits_uncropped_when_rect_unusable(qapp, tmp_path):
    m = _manager(tmp_path)
    p = _png(tmp_path)
    got = []
    m.captured.connect(got.append)
    m._pending_crop = QRect(9999, 9999, 10, 10)  # off-virtual
    m._crop_virtual = QRect(0, 0, 200, 100)
    m._finish(p)
    assert got == [p]  # degrade to the full shot, never fail the capture
    assert QImage(p).width() == 200


def test_public_capture_modes_clear_pending_crop(qapp, tmp_path, monkeypatch):
    m = _manager(tmp_path)
    m._pending_crop = QRect(0, 0, 10, 10)
    monkeypatch.setattr(m, "_capture", lambda mode: None)
    m.capture_region()
    assert m._pending_crop is None
