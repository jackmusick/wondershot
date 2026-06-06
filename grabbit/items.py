"""Annotation graphics items for the markup editor."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
)

# Marker attribute: anything with .is_annotation == True gets flattened/undone.
ANNOTATION_FLAG = "is_annotation"


def _mark(item: QGraphicsItem) -> None:
    item.is_annotation = True
    item.setFlag(QGraphicsItem.ItemIsSelectable, True)
    item.setFlag(QGraphicsItem.ItemIsMovable, True)


def is_annotation(item: QGraphicsItem) -> bool:
    return getattr(item, ANNOTATION_FLAG, False)


class ArrowItem(QGraphicsPathItem):
    """Line with a filled arrowhead at the end point."""

    def __init__(self, p1: QPointF, p2: QPointF, color: QColor, width: int):
        super().__init__()
        _mark(self)
        self._color = QColor(color)
        self._width = width
        self._p1 = QPointF(p1)
        self._p2 = QPointF(p2)
        pen = QPen(self._color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.setPen(pen)
        self.setBrush(QBrush(self._color))
        self._rebuild()

    def set_end(self, p2: QPointF) -> None:
        self._p2 = QPointF(p2)
        self._rebuild()

    def set_start(self, p1: QPointF) -> None:
        self._p1 = QPointF(p1)
        self._rebuild()

    def endpoints(self) -> tuple[QPointF, QPointF]:
        return QPointF(self._p1), QPointF(self._p2)

    def set_style(self, color: QColor | None = None, width: int | None = None):
        if color is not None:
            self._color = QColor(color)
        if width is not None:
            self._width = width
        pen = QPen(self._color, self._width, Qt.SolidLine, Qt.RoundCap,
                   Qt.RoundJoin)
        self.setPen(pen)
        self.setBrush(QBrush(self._color))
        self._rebuild()

    def _rebuild(self) -> None:
        p1, p2 = self._p1, self._p2
        path = QPainterPath()
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = math.hypot(dx, dy)
        head_len = max(18.0, self._width * 4.2)
        head_w = head_len * 0.85
        if length < 1:
            self.setPath(path)
            return
        ux, uy = dx / length, dy / length
        # Shaft stops where the head begins so the tip stays sharp.
        shaft_end = QPointF(p2.x() - ux * head_len, p2.y() - uy * head_len)
        path.moveTo(p1)
        path.lineTo(shaft_end)
        # Arrowhead polygon (closed subpath -> filled by brush).
        nx, ny = -uy, ux
        base_l = QPointF(shaft_end.x() + nx * head_w / 2, shaft_end.y() + ny * head_w / 2)
        base_r = QPointF(shaft_end.x() - nx * head_w / 2, shaft_end.y() - ny * head_w / 2)
        head = QPolygonF([p2, base_l, base_r])
        path.addPolygon(head)
        path.closeSubpath()
        self.setPath(path)


class LineItem(QGraphicsPathItem):
    def __init__(self, p1: QPointF, p2: QPointF, color: QColor, width: int):
        super().__init__()
        _mark(self)
        self._p1 = QPointF(p1)
        self._p2 = QPointF(p2)
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(Qt.NoBrush)
        self.set_end(p2)

    def set_end(self, p2: QPointF) -> None:
        self._p2 = QPointF(p2)
        self._rebuild()

    def set_start(self, p1: QPointF) -> None:
        self._p1 = QPointF(p1)
        self._rebuild()

    def endpoints(self) -> tuple[QPointF, QPointF]:
        return QPointF(self._p1), QPointF(self._p2)

    def _rebuild(self) -> None:
        path = QPainterPath()
        path.moveTo(self._p1)
        path.lineTo(self._p2)
        self.setPath(path)


class RectItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, color: QColor, width: int):
        super().__init__(rect)
        _mark(self)
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(Qt.NoBrush)


class EllipseItem(QGraphicsEllipseItem):
    def __init__(self, rect: QRectF, color: QColor, width: int):
        super().__init__(rect)
        _mark(self)
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(Qt.NoBrush)


class HighlightItem(QGraphicsRectItem):
    """Translucent marker rectangle (multiplied onto the image look)."""

    def __init__(self, rect: QRectF, color: QColor):
        super().__init__(rect)
        _mark(self)
        c = QColor(color)
        c.setAlpha(90)
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(c))


class FreehandItem(QGraphicsPathItem):
    def __init__(self, start: QPointF, color: QColor, width: int):
        super().__init__()
        _mark(self)
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(start)
        self.setPath(path)

    def add_point(self, p: QPointF) -> None:
        path = self.path()
        path.lineTo(p)
        self.setPath(path)


class TextItem(QGraphicsTextItem):
    def __init__(self, pos: QPointF, color: QColor, point_size: int = 18):
        super().__init__()
        _mark(self)
        self.setPos(pos)
        self.setDefaultTextColor(color)
        font = QFont()
        font.setPointSize(point_size)
        font.setBold(True)
        self.setFont(font)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)

    def start_editing(self) -> None:
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)

    def focusOutEvent(self, event):  # noqa: N802
        super().focusOutEvent(event)
        # Freeze editing when focus leaves; empty items get removed by editor.
        self.setTextInteractionFlags(Qt.NoTextInteraction)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.start_editing()
        super().mouseDoubleClickEvent(event)


class StepItem(QGraphicsItem):
    """Numbered circle stamp, Snagit-style step tool."""

    def __init__(self, pos: QPointF, number: int, color: QColor,
                 radius: float = 16.0):
        super().__init__()
        _mark(self)
        self.number = number
        self._color = QColor(color)
        self.radius = radius
        self.setPos(pos)

    def set_radius(self, r: float) -> None:
        self.prepareGeometryChange()
        self.radius = max(8.0, min(80.0, r))
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        r = self.radius
        return QRectF(-r - 2, -r - 2, 2 * r + 4, 2 * r + 4)

    def paint(self, painter: QPainter, option, widget=None):
        r = self.radius
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(r * 0.85 if self.number < 10 else r * 0.7)
        painter.setFont(font)
        painter.setPen(QPen(QColor("white")))
        painter.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignCenter, str(self.number))
        if self.isSelected():
            painter.setPen(QPen(QColor(0, 0, 0, 180), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())


class HandleItem(QGraphicsRectItem):
    """Resize grip attached to an annotation as a child item.

    Children follow their parent automatically when the object moves; the
    grip stays a constant size on screen regardless of zoom.
    """

    SIZE = 10.0

    def __init__(self, target, role: str, on_pressed, on_moved):
        s = self.SIZE
        super().__init__(-s / 2, -s / 2, s, s, target)
        self.role = role
        self._on_pressed = on_pressed
        self._on_moved = on_moved
        self.press_state: dict = {}
        self._notify = True
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setBrush(QBrush(QColor("white")))
        self.setPen(QPen(QColor("#3daee9"), 1.5))
        self.setZValue(20000)
        self.setCursor(Qt.SizeAllCursor)

    def place(self, pos: QPointF) -> None:
        """Reposition without firing the moved callback."""
        self._notify = False
        self.setPos(pos)
        self._notify = True

    def mousePressEvent(self, event):  # noqa: N802
        self.press_state = self._on_pressed(self.parentItem(), self.role)
        super().mousePressEvent(event)

    def itemChange(self, change, value):  # noqa: N802
        if (change == QGraphicsItem.ItemPositionHasChanged and self._notify
                and self.parentItem() is not None):
            self._on_moved(self.parentItem(), self.role, self.pos(),
                           self.press_state)
        return super().itemChange(change, value)


def get_style(item) -> dict:
    """Read color / stroke width / font size off any annotation item."""
    style: dict = {}
    if isinstance(item, ArrowItem):
        style["color"] = QColor(item._color)
        style["width"] = item._width
    elif isinstance(item, StepItem):
        style["color"] = QColor(item._color)
    elif isinstance(item, TextItem):
        style["color"] = item.defaultTextColor()
        style["font_size"] = item.font().pointSize()
    elif isinstance(item, HighlightItem):
        c = item.brush().color()
        c.setAlpha(255)
        style["color"] = c
    elif isinstance(item, (LineItem, RectItem, EllipseItem, FreehandItem)):
        style["color"] = item.pen().color()
        style["width"] = item.pen().width()
    return style


def apply_style(item, color: QColor | None = None, width: int | None = None,
                font_size: int | None = None) -> None:
    """Apply color / stroke width / font size to any annotation item."""
    if isinstance(item, ArrowItem):
        item.set_style(color, width)
    elif isinstance(item, StepItem):
        if color is not None:
            item._color = QColor(color)
            item.update()
    elif isinstance(item, TextItem):
        if color is not None:
            item.setDefaultTextColor(color)
        if font_size is not None and font_size > 0:
            f = item.font()
            f.setPointSize(font_size)
            item.setFont(f)
    elif isinstance(item, HighlightItem):
        if color is not None:
            c = QColor(color)
            c.setAlpha(90)
            item.setBrush(QBrush(c))
    elif isinstance(item, (LineItem, RectItem, EllipseItem, FreehandItem)):
        pen = item.pen()
        if color is not None:
            pen.setColor(QColor(color))
        if width is not None:
            pen.setWidth(width)
        item.setPen(pen)


class PixelateItem(QGraphicsPixmapItem):
    """Pixelated patch pinned over the image. Selectable (deletable) but not movable."""

    def __init__(self, pixmap, pos: QPointF):
        super().__init__(pixmap)
        _mark(self)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setPos(pos)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(QColor(0, 120, 255, 200), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())
