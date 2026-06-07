"""Round-trip tests for annotation item serialization (sidecar format).

Pure: items in/out of dicts through real JSON, no scene or editor needed.
"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def roundtrip(item, base_provider=None):
    """Serialize through REAL json (catches non-JSON-safe values)."""
    from wondershot.items import item_from_dict
    d = json.loads(json.dumps(item.to_dict()))
    out = item_from_dict(d, base_provider=base_provider)
    assert out is not None, f"dispatcher returned None for {d.get('type')}"
    return out


def test_arrow_roundtrip(qapp):
    from wondershot.items import ArrowItem
    item = ArrowItem(QPointF(10.5, 20.25), QPointF(110.0, 80.75),
                     QColor("#e3242b"), 7)
    out = roundtrip(item)
    assert isinstance(out, ArrowItem)
    assert out.endpoints() == (QPointF(10.5, 20.25), QPointF(110.0, 80.75))
    assert out._color == QColor("#e3242b")
    assert out._width == 7
    assert out.pen().width() == 7


def test_line_roundtrip(qapp):
    from wondershot.items import LineItem
    item = LineItem(QPointF(1.0, 2.0), QPointF(3.5, -4.5),
                    QColor("#00ff00"), 3)
    out = roundtrip(item)
    assert isinstance(out, LineItem)
    assert out.endpoints() == (QPointF(1.0, 2.0), QPointF(3.5, -4.5))
    assert out.pen().color() == QColor("#00ff00")
    assert out.pen().width() == 3


def test_rect_and_ellipse_roundtrip(qapp):
    from wondershot.items import EllipseItem, RectItem
    for cls in (RectItem, EllipseItem):
        item = cls(QRectF(5.25, 6.5, 100.0, 50.75), QColor("#3daee9"), 4)
        out = roundtrip(item)
        assert isinstance(out, cls)
        assert out.rect() == QRectF(5.25, 6.5, 100.0, 50.75)
        assert out.pen().color() == QColor("#3daee9")
        assert out.pen().width() == 4


def test_highlight_roundtrip_keeps_translucency(qapp):
    from wondershot.items import HighlightItem
    item = HighlightItem(QRectF(0, 0, 60, 20), QColor("#ffe000"))
    out = roundtrip(item)
    assert isinstance(out, HighlightItem)
    assert out.rect() == QRectF(0, 0, 60, 20)
    # constructor re-applies the marker alpha — must come back as 90
    assert out.brush().color().alpha() == 90
    c = out.brush().color()
    assert (c.red(), c.green(), c.blue()) == (255, 224, 0)


def test_freehand_roundtrip_preserves_every_point(qapp):
    from wondershot.items import FreehandItem
    item = FreehandItem(QPointF(1.5, 2.5), QColor("#ff00ff"), 5)
    pts = [QPointF(3.25, 4.0), QPointF(10.0, -2.75), QPointF(11.125, 9.5)]
    for p in pts:
        item.add_point(p)
    out = roundtrip(item)
    assert isinstance(out, FreehandItem)
    path_in, path_out = item.path(), out.path()
    assert path_out.elementCount() == path_in.elementCount() == 4
    for i in range(path_in.elementCount()):
        assert path_out.elementAt(i).x == path_in.elementAt(i).x
        assert path_out.elementAt(i).y == path_in.elementAt(i).y
    assert out.pen().width() == 5


def test_roundtripped_items_are_annotations(qapp):
    """Restored items must be selectable/movable/flattenable like drawn ones."""
    from wondershot.items import ArrowItem, is_annotation
    from PySide6.QtWidgets import QGraphicsItem
    out = roundtrip(ArrowItem(QPointF(0, 0), QPointF(9, 9),
                              QColor("red"), 2))
    assert is_annotation(out)
    assert out.flags() & QGraphicsItem.ItemIsSelectable
    assert out.flags() & QGraphicsItem.ItemIsMovable


def test_dispatcher_unknown_type_returns_none(qapp):
    from wondershot.items import item_from_dict
    assert item_from_dict({"type": "hologram"}) is None
    assert item_from_dict({}) is None
