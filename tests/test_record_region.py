"""Region-pick -> crop wiring (PURE, offscreen Qt, fake overlay).

The overlay + fullscreen grab are seams so the flow is testable without a
live desktop: a fake overlay emits selected(QRect)/cancelled()."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from tests.test_record_sync import make_app


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeOverlay(QObject):
    selected = Signal(QRect)
    cancelled = Signal()

    def show_on_desktop(self):
        pass


def _wire(a, monkeypatch, img):
    ov = FakeOverlay()
    monkeypatch.setattr(a, "_region_grab",
                        lambda: (img, QRect(0, 0, img.width(), img.height())))
    monkeypatch.setattr(a, "_region_overlay", lambda image: ov)
    started = []
    monkeypatch.setattr(a, "_begin_recording", lambda: started.append(1))
    return ov, started


def test_region_selected_sets_crop_and_starts(qapp, tmp_path, monkeypatch):
    from wondershot.record import crop_props
    a = make_app(qapp, tmp_path, monkeypatch)
    img = QImage(800, 600, QImage.Format_RGB32)
    ov, started = _wire(a, monkeypatch, img)
    a.record_region()
    ov.selected.emit(QRect(100, 100, 200, 200))
    assert a.recorder._crop == crop_props((100, 100, 200, 200), 800, 600)
    assert started == [1]


def test_region_cancel_leaves_crop_none_and_no_start(qapp, tmp_path,
                                                     monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    img = QImage(800, 600, QImage.Format_RGB32)
    ov, started = _wire(a, monkeypatch, img)
    a.record_region()
    ov.cancelled.emit()
    assert a.recorder._crop is None
    assert started == []


def test_region_empty_rect_is_treated_as_cancel(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    img = QImage(800, 600, QImage.Format_RGB32)
    ov, started = _wire(a, monkeypatch, img)
    a.record_region()
    ov.selected.emit(QRect())  # degenerate
    assert a.recorder._crop is None
    assert started == []


def test_gallery_region_action_routes_to_app(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(a, "record_region", lambda: calls.append(1))
    a.gallery.record_region_requested.emit()
    assert calls == [1]
