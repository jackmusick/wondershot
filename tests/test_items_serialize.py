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


def test_text_roundtrip_fonts_and_width(qapp):
    from wondershot.items import TextItem
    from PySide6.QtCore import Qt
    item = TextItem(QPointF(40.0, 30.0), QColor("#112233"), point_size=21)
    f = item.font()
    f.setFamily("DejaVu Sans")
    f.setBold(False)          # non-default: constructor forces bold
    item.setFont(f)
    item.setPlainText("hello\nworld")
    item.setTextWidth(123.5)
    out = roundtrip(item)
    assert isinstance(out, TextItem)
    assert out.toPlainText() == "hello\nworld"
    assert out.defaultTextColor() == QColor("#112233")
    assert out.font().pointSize() == 21
    assert out.font().family() == "DejaVu Sans"
    assert out.font().bold() is False
    assert out.textWidth() == 123.5
    assert out.pos() == QPointF(40.0, 30.0)
    # a freshly loaded text item is NOT in editing mode
    assert out.textInteractionFlags() == Qt.NoTextInteraction


def test_text_default_width_stays_auto(qapp):
    from wondershot.items import TextItem
    item = TextItem(QPointF(0, 0), QColor("red"))
    assert item.textWidth() == -1.0
    out = roundtrip(item)
    assert out.textWidth() == -1.0


def test_step_roundtrip(qapp):
    from wondershot.items import StepItem
    item = StepItem(QPointF(77.0, 88.0), 12, QColor("#aa00aa"), radius=22.5)
    out = roundtrip(item)
    assert isinstance(out, StepItem)
    assert out.number == 12
    assert out.radius == 22.5
    assert out._color == QColor("#aa00aa")
    assert out.pos() == QPointF(77.0, 88.0)


def test_pixelate_roundtrip_uses_base_provider(qapp):
    from PySide6.QtGui import QImage
    from wondershot.items import PixelateItem
    base = QImage(200, 150, QImage.Format_ARGB32_Premultiplied)
    base.fill(QColor("orange"))
    item = PixelateItem(lambda: base, QRectF(10.0, 12.0, 80.0, 40.0),
                        block=9)
    out = roundtrip(item, base_provider=lambda: base)
    assert isinstance(out, PixelateItem)
    assert out.rect() == QRectF(10.0, 12.0, 80.0, 40.0)
    assert out._block == 9
    assert out._patch is not None, "patch must regenerate from the provider"


def test_pixelate_without_provider_is_skipped(qapp):
    from wondershot.items import item_from_dict
    d = {"type": "pixelate", "rect": [0, 0, 10, 10], "block": 14,
         "pos": [0, 0], "rotation": 0.0, "origin": [0, 0]}
    assert item_from_dict(d) is None  # no provider -> can't rebuild


def test_rotation_and_geometry_roundtrip_exactly(qapp):
    """Jack's bar: revisit an image and nothing has shifted. Doubles must
    survive JSON bit-for-bit (Python json round-trips floats exactly)."""
    from wondershot.items import RectItem
    item = RectItem(QRectF(3.1, 4.7, 99.9, 33.3), QColor("red"), 2)
    item.setTransformOriginPoint(QPointF(53.05, 21.35))
    item.setRotation(33.7)
    item.setPos(QPointF(-12.625, 7.0625))
    out = roundtrip(item)
    assert out.rotation() == 33.7
    assert out.pos() == QPointF(-12.625, 7.0625)
    assert out.transformOriginPoint() == QPointF(53.05, 21.35)
    assert out.rect() == QRectF(3.1, 4.7, 99.9, 33.3)
    # scene-space corner identical => no visible shift on revisit
    assert out.mapToScene(out.rect().topLeft()) \
        == item.mapToScene(item.rect().topLeft())


def test_arrow_rotation_roundtrip_exactly(qapp):
    from wondershot.items import ArrowItem
    item = ArrowItem(QPointF(5, 5), QPointF(120, 60), QColor("red"), 6)
    item.setTransformOriginPoint(QPointF(62.5, 32.5))
    item.setRotation(287.123456789)
    out = roundtrip(item)
    assert out.rotation() == 287.123456789
    assert out.mapToScene(out.endpoints()[1]) \
        == item.mapToScene(item.endpoints()[1])


def test_rect_fill_roundtrip(qapp):
    from PySide6.QtCore import Qt
    from wondershot.items import RectItem
    item = RectItem(QRectF(1, 2, 30, 20), QColor("#202020"), 1,
                    fill=QColor("#c8c8c8"))
    assert item.brush().style() != Qt.NoBrush
    out = roundtrip(item)
    assert out.brush().color() == QColor("#c8c8c8")
    assert out.brush().style() != Qt.NoBrush
    assert out.pen().color() == QColor("#202020")


def test_rect_without_fill_stays_hollow(qapp):
    from PySide6.QtCore import Qt
    from wondershot.items import RectItem
    item = RectItem(QRectF(0, 0, 10, 10), QColor("red"), 3)
    d = item.to_dict()
    assert "fill" not in d              # old sidecars stay byte-identical
    out = roundtrip(item)
    assert out.brush().style() == Qt.NoBrush


def test_text_alignment_roundtrip(qapp):
    from wondershot.items import TextItem
    from PySide6.QtCore import Qt
    item = TextItem(QPointF(0, 0), QColor("red"))
    item.setPlainText("centered")
    item.setTextWidth(200.0)
    item.set_alignment("center")
    d = item.to_dict()
    assert d["align"] == "center"
    out = roundtrip(item)
    assert out.alignment() == "center"
    assert out.document().defaultTextOption().alignment() \
        & Qt.AlignHCenter


def test_text_alignment_defaults_left_for_old_sidecars(qapp):
    from wondershot.items import TextItem, item_from_dict
    item = TextItem(QPointF(0, 0), QColor("red"))
    assert item.alignment() == "left"
    d = item.to_dict()
    del d["align"]                       # sidecar written by an older build
    out = item_from_dict(d)
    assert out.alignment() == "left"
