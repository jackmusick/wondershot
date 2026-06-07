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
    QStyle,
    QStyleOptionGraphicsItem,
)


class _NoSelectionBox:
    """Suppress Qt's dashed selection rect — selection is shown by the
    endpoint grips instead (a bounding box around a diagonal arrow reads
    as a weird floating square)."""

    def paint(self, painter, option, widget=None):
        opt = QStyleOptionGraphicsItem(option)
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, widget)

# Marker attribute: anything with .is_annotation == True gets flattened/undone.
ANNOTATION_FLAG = "is_annotation"


def _mark(item: QGraphicsItem) -> None:
    item.is_annotation = True
    item.setFlag(QGraphicsItem.ItemIsSelectable, True)
    item.setFlag(QGraphicsItem.ItemIsMovable, True)


def is_annotation(item: QGraphicsItem) -> bool:
    return getattr(item, ANNOTATION_FLAG, False)


def _color_str(c: QColor) -> str:
    return QColor(c).name(QColor.HexArgb)


def _transform_dict(item) -> dict:
    """Common geometry every serialized item carries."""
    p, o = item.pos(), item.transformOriginPoint()
    return {"pos": [p.x(), p.y()], "rotation": item.rotation(),
            "origin": [o.x(), o.y()]}


def _apply_transform(item, d: dict) -> None:
    # Same order as EditorWindow.apply_snapshot: origin, rotation, pos —
    # any other order shifts rotated items.
    o = d.get("origin", [0.0, 0.0])
    item.setTransformOriginPoint(QPointF(o[0], o[1]))
    item.setRotation(d.get("rotation", 0.0))
    p = d.get("pos", [0.0, 0.0])
    item.setPos(QPointF(p[0], p[1]))


class ArrowItem(_NoSelectionBox, QGraphicsPathItem):
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

    def to_dict(self) -> dict:
        return {"type": "arrow",
                "p1": [self._p1.x(), self._p1.y()],
                "p2": [self._p2.x(), self._p2.y()],
                "color": _color_str(self._color), "width": self._width,
                **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "ArrowItem":
        item = cls(QPointF(*d["p1"]), QPointF(*d["p2"]),
                   QColor(d["color"]), int(d["width"]))
        _apply_transform(item, d)
        return item

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


class LineItem(_NoSelectionBox, QGraphicsPathItem):
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

    def to_dict(self) -> dict:
        return {"type": "line",
                "p1": [self._p1.x(), self._p1.y()],
                "p2": [self._p2.x(), self._p2.y()],
                "color": _color_str(self.pen().color()),
                "width": self.pen().width(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "LineItem":
        item = cls(QPointF(*d["p1"]), QPointF(*d["p2"]),
                   QColor(d["color"]), int(d["width"]))
        _apply_transform(item, d)
        return item

    def _rebuild(self) -> None:
        path = QPainterPath()
        path.moveTo(self._p1)
        path.lineTo(self._p2)
        self.setPath(path)


class RectItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, color: QColor, width: int,
                 fill: QColor | None = None):
        super().__init__(rect)
        _mark(self)
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self._fill = QColor(fill) if fill is not None else None
        self.setBrush(QBrush(self._fill) if self._fill is not None
                      else Qt.NoBrush)

    def to_dict(self) -> dict:
        r = self.rect()
        d = {"type": "rect",
             "rect": [r.x(), r.y(), r.width(), r.height()],
             "color": _color_str(self.pen().color()),
             "width": self.pen().width(), **_transform_dict(self)}
        if self._fill is not None:
            d["fill"] = _color_str(self._fill)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RectItem":
        r = d["rect"]
        fill = QColor(d["fill"]) if d.get("fill") else None
        item = cls(QRectF(r[0], r[1], r[2], r[3]),
                   QColor(d["color"]), int(d["width"]), fill=fill)
        _apply_transform(item, d)
        return item


class EllipseItem(QGraphicsEllipseItem):
    def __init__(self, rect: QRectF, color: QColor, width: int):
        super().__init__(rect)
        _mark(self)
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(Qt.NoBrush)

    def to_dict(self) -> dict:
        r = self.rect()
        return {"type": "ellipse",
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "color": _color_str(self.pen().color()),
                "width": self.pen().width(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "EllipseItem":
        r = d["rect"]
        item = cls(QRectF(r[0], r[1], r[2], r[3]),
                   QColor(d["color"]), int(d["width"]))
        _apply_transform(item, d)
        return item


class HighlightItem(QGraphicsRectItem):
    """Translucent marker rectangle (multiplied onto the image look)."""

    def __init__(self, rect: QRectF, color: QColor):
        super().__init__(rect)
        _mark(self)
        c = QColor(color)
        c.setAlpha(90)
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(c))

    def to_dict(self) -> dict:
        r = self.rect()
        c = QColor(self.brush().color())
        c.setAlpha(255)
        return {"type": "highlight",
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "color": c.name(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "HighlightItem":
        r = d["rect"]
        item = cls(QRectF(r[0], r[1], r[2], r[3]), QColor(d["color"]))
        _apply_transform(item, d)
        return item


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

    def to_dict(self) -> dict:
        path = self.path()
        pts = [[path.elementAt(i).x, path.elementAt(i).y]
               for i in range(path.elementCount())]
        return {"type": "freehand", "points": pts,
                "color": _color_str(self.pen().color()),
                "width": self.pen().width(), **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "FreehandItem":
        pts = d["points"]
        item = cls(QPointF(pts[0][0], pts[0][1]),
                   QColor(d["color"]), int(d["width"]))
        for x, y in pts[1:]:
            item.add_point(QPointF(x, y))
        _apply_transform(item, d)
        return item


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

    def to_dict(self) -> dict:
        f = self.font()
        return {"type": "text", "text": self.toPlainText(),
                "color": _color_str(self.defaultTextColor()),
                "family": f.family(), "point_size": f.pointSize(),
                "bold": f.bold(), "text_width": self.textWidth(),
                **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "TextItem":
        item = cls(QPointF(0, 0), QColor(d["color"]),
                   int(d.get("point_size", 18)))
        f = item.font()
        if d.get("family"):
            f.setFamily(d["family"])
        f.setBold(bool(d.get("bold", True)))
        item.setFont(f)
        item.setPlainText(d.get("text", ""))
        tw = d.get("text_width", -1.0)
        if tw is not None and tw > 0:
            item.setTextWidth(tw)
        # restored items are not mid-edit; double-click re-enables editing
        item.setTextInteractionFlags(Qt.NoTextInteraction)
        _apply_transform(item, d)
        return item


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

    def to_dict(self) -> dict:
        return {"type": "step", "number": self.number,
                "color": _color_str(self._color), "radius": self.radius,
                **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "StepItem":
        item = cls(QPointF(0, 0), int(d["number"]), QColor(d["color"]),
                   radius=float(d.get("radius", 16.0)))
        _apply_transform(item, d)
        return item

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


_rotate_cursor_cache = None


def rotate_cursor():
    """Curved-arrow rotate cursor (Qt ships none)."""
    global _rotate_cursor_cache
    if _rotate_cursor_cache is None:
        from PySide6.QtGui import QCursor, QPixmap
        pm = QPixmap(24, 24)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(5, 5, 14, 14)
        for pen in (QPen(QColor(0, 0, 0, 220), 4.5),
                    QPen(QColor(255, 255, 255), 2.2)):
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(rect, 30 * 16, 280 * 16)
        # arrowhead at the arc's end (~30°)
        head = QPolygonF([QPointF(21.5, 6.5), QPointF(14.5, 5.0),
                          QPointF(19.5, 12.5)])
        p.setPen(QPen(QColor(0, 0, 0, 220), 1.5))
        p.setBrush(QColor(255, 255, 255))
        p.drawPolygon(head)
        p.end()
        _rotate_cursor_cache = QCursor(pm, 12, 12)
    return _rotate_cursor_cache


class HandleItem(QGraphicsRectItem):
    """Resize grip attached to an annotation as a child item.

    Children follow their parent automatically when the object moves; the
    grip stays a constant size on screen regardless of zoom.
    """

    SIZE = 10.0
    CURSORS = {
        "rotate": Qt.OpenHandCursor,
        "width": Qt.SizeHorCursor,
        "radius": Qt.SizeHorCursor,
        "tl": Qt.SizeFDiagCursor,
        "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor,
        "bl": Qt.SizeBDiagCursor,
        "font": Qt.SizeFDiagCursor,
    }

    def __init__(self, target, role: str, on_pressed, on_moved,
                 on_released=None):
        # Endpoint grips are the only selection indicator on arrows/lines
        # (no bounding box) — make them a touch bigger.
        s = 12.0 if role in ("p1", "p2") else self.SIZE
        super().__init__(-s / 2, -s / 2, s, s, target)
        self.role = role
        self._on_pressed = on_pressed
        self._on_moved = on_moved
        self._on_released = on_released
        self.press_state: dict = {}
        self._notify = True
        self._press_scene = None
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        if role == "rotate":
            self.setBrush(QBrush(QColor("#3daee9")))
            self.setPen(QPen(QColor("white"), 1.5))
            self.setCursor(rotate_cursor())
        else:
            self.setBrush(QBrush(QColor("white")))
            self.setPen(QPen(QColor("#3daee9"), 1.5))
            self.setCursor(self.CURSORS.get(role, Qt.SizeAllCursor))
        self.setZValue(20000)

    def paint(self, painter, option, widget=None):
        if self.role in ("rotate", "p1", "p2"):
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(self.brush())
            painter.setPen(self.pen())
            painter.drawEllipse(self.rect())
        else:
            super().paint(painter, option, widget)

    def place(self, pos: QPointF) -> None:
        """Reposition without firing the moved callback."""
        self._notify = False
        self.setPos(pos)
        self._notify = True

    def mousePressEvent(self, event):  # noqa: N802
        self.press_state = self._on_pressed(self.parentItem(), self.role)
        self._press_scene = event.scenePos()
        # Qt's movable-drag moves ALL selected items along with the
        # grabber — the selected parent would follow the mouse and the
        # grip (parent-relative) would never move at all. Freeze the
        # parent for the duration of the grip drag.
        parent = self.parentItem()
        self._restore_movable = bool(
            parent.flags() & QGraphicsItem.ItemIsMovable)
        parent.setFlag(QGraphicsItem.ItemIsMovable, False)
        super().mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self.role != "rotate":
            super().mouseMoveEvent(event)
            return
        # Smooth absolute rotation: track the cursor's angle around the
        # object's center in SCENE coordinates — no movable-item feedback
        # loop, no grip repositioning mid-drag.
        import math
        parent = self.parentItem()
        state = self.press_state
        if parent is None or "center_local" not in state:
            return
        center = parent.mapToScene(state["center_local"])
        v0 = self._press_scene - center
        v1 = event.scenePos() - center
        a0 = math.degrees(math.atan2(v0.y(), v0.x()))
        a1 = math.degrees(math.atan2(v1.y(), v1.x()))
        rot = (state.get("rot0", 0.0) + (a1 - a0)) % 360
        if event.modifiers() & Qt.ShiftModifier:
            rot = round(rot / 15) * 15  # snap to 15° with Shift
        parent.setRotation(rot)
        self._on_moved(parent, "rotate", self.pos(), state)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        parent = self.parentItem()
        if parent is not None and getattr(self, "_restore_movable", False):
            parent.setFlag(QGraphicsItem.ItemIsMovable, True)
        super().mouseReleaseEvent(event)
        if self._on_released is not None and parent is not None:
            self._on_released(parent, self.role, self.press_state)

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


class PixelateItem(QGraphicsItem):
    """Live pixelation of whatever part of the base image sits under it.

    Behaves exactly like the shape items: movable, corner-resizable,
    deletable. The patch regenerates from the base image whenever the
    item moves or resizes.
    """

    def __init__(self, base_provider, rect: QRectF, block: int = 14):
        super().__init__()
        _mark(self)
        self._base_provider = base_provider  # callable -> QImage
        self._rect = QRectF(rect)
        self._block = block
        self._patch = None
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self._regen()

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def setRect(self, r: QRectF) -> None:  # noqa: N802 (mirror QGraphicsRectItem)
        self.prepareGeometryChange()
        self._rect = QRectF(r)
        self._regen()
        self.update()

    def to_dict(self) -> dict:
        r = self._rect
        return {"type": "pixelate",
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "block": self._block, **_transform_dict(self)}

    @classmethod
    def from_dict(cls, d: dict, base_provider) -> "PixelateItem":
        r = d["rect"]
        item = cls(base_provider, QRectF(r[0], r[1], r[2], r[3]),
                   block=int(d.get("block", 14)))
        _apply_transform(item, d)
        return item

    def _regen(self) -> None:
        from . import imageops
        base = self._base_provider()
        if base is None or base.isNull():
            self._patch = None
            return
        scene_rect = self.mapRectToScene(self._rect.normalized()).toRect()
        patch = imageops.pixelated_patch(base, scene_rect, self._block)
        self._patch = None if patch.isNull() else patch

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._regen()
            self.update()
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._rect.normalized().adjusted(-2, -2, 2, 2)

    def paint(self, painter, option, widget=None):
        r = self._rect.normalized()
        if self._patch is not None:
            painter.drawImage(r, self._patch)
        else:
            painter.fillRect(r, QColor(127, 127, 127, 160))
        if self.isSelected():
            painter.setPen(QPen(QColor(0, 120, 255, 200), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r)


def item_from_dict(d: dict, base_provider=None):
    """Rebuild a live annotation item from its serialized dict.

    Returns None for unknown/future types (the editor skips them rather
    than crashing on a newer sidecar). PixelateItem needs the editor's
    base_provider callable to regenerate its patch.
    """
    t = d.get("type")
    if t == "pixelate":
        if base_provider is None:
            return None
        return PixelateItem.from_dict(d, base_provider)
    cls = _ITEM_TYPES.get(t)
    return cls.from_dict(d) if cls is not None else None


_ITEM_TYPES = {
    "arrow": ArrowItem, "line": LineItem, "rect": RectItem,
    "ellipse": EllipseItem, "highlight": HighlightItem,
    "freehand": FreehandItem, "text": TextItem, "step": StepItem,
}
