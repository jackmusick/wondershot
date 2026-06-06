"""Markup editor: QGraphicsScene canvas with annotation tools and undo."""

from __future__ import annotations

import enum
import os

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QUndoCommand,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QToolBar,
    QLabel,
)

from . import imageops
from .items import (
    ArrowItem,
    EllipseItem,
    FreehandItem,
    HandleItem,
    HighlightItem,
    LineItem,
    PixelateItem,
    RectItem,
    StepItem,
    TextItem,
    is_annotation,
)


class Tool(enum.Enum):
    SELECT = "select"
    ARROW = "arrow"
    LINE = "line"
    RECT = "rect"
    ELLIPSE = "ellipse"
    PEN = "pen"
    HIGHLIGHT = "highlight"
    TEXT = "text"
    STEP = "step"
    PIXELATE = "pixelate"
    CROP = "crop"
    CUTOUT_V = "cutout_v"  # removes a vertical band, joins left+right
    CUTOUT_H = "cutout_h"  # removes a horizontal band, joins top+bottom


_EDIT_KEYS = {
    Qt.Key_C, Qt.Key_V, Qt.Key_X, Qt.Key_A, Qt.Key_Z, Qt.Key_Y, Qt.Key_S,
}


class AddItemCommand(QUndoCommand):
    def __init__(self, editor: "EditorWindow", item, text: str = "add annotation"):
        super().__init__(text)
        self.editor = editor
        self.item = item

    def redo(self):
        if self.item.scene() is None:
            self.editor.scene.addItem(self.item)
        if isinstance(self.item, StepItem):
            self.editor.step_counter = self.item.number + 1

    def undo(self):
        if self.item.scene() is not None:
            self.editor.scene.removeItem(self.item)
        if isinstance(self.item, StepItem):
            self.editor.step_counter = self.item.number


class RemoveItemsCommand(QUndoCommand):
    def __init__(self, editor: "EditorWindow", items, text: str = "delete"):
        super().__init__(text)
        self.editor = editor
        self.items = list(items)

    def redo(self):
        for it in self.items:
            if it.scene() is not None:
                self.editor.scene.removeItem(it)

    def undo(self):
        for it in self.items:
            if it.scene() is None:
                self.editor.scene.addItem(it)


class FlattenCommand(QUndoCommand):
    """Crop/cut-out: swap the base image, folding annotations into it."""

    def __init__(self, editor: "EditorWindow", new_image: QImage, text: str):
        super().__init__(text)
        self.editor = editor
        self.old_image = editor.base_image
        self.new_image = new_image
        self.items = [i for i in editor.scene.items() if is_annotation(i)]

    def redo(self):
        self.editor.scene.clearSelection()
        for it in self.items:
            if it.scene() is not None:
                self.editor.scene.removeItem(it)
        self.editor.set_base_image(self.new_image)

    def undo(self):
        self.editor.set_base_image(self.old_image)
        for it in self.items:
            if it.scene() is None:
                self.editor.scene.addItem(it)


class GripCommand(QUndoCommand):
    """Undo entry for a grip edit (resize / rotate / reshape)."""

    def __init__(self, editor: "EditorWindow", item, before: dict, after: dict):
        super().__init__("transform")
        self.editor = editor
        self.item = item
        self.before = before
        self.after = after
        self._first = True

    def redo(self):
        if self._first:  # the live drag already applied the change
            self._first = False
            return
        self.editor.apply_snapshot(self.item, self.after)

    def undo(self):
        self.editor.apply_snapshot(self.item, self.before)


class CanvasView(QGraphicsView):
    def __init__(self, editor: "EditorWindow"):
        super().__init__(editor.scene)
        self.editor = editor
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(35, 35, 38))
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._passthrough = False

    def event(self, ev):
        # Don't let single-letter tool shortcuts steal keys while typing text.
        if ev.type() == QEvent.ShortcutOverride:
            focus = self.scene().focusItem()
            if isinstance(focus, TextItem):
                mods = ev.modifiers()
                if mods in (Qt.NoModifier, Qt.ShiftModifier) or (
                    mods == Qt.ControlModifier and ev.key() in _EDIT_KEYS
                ):
                    ev.accept()
                    return True
        return super().event(ev)

    def wheelEvent(self, ev):  # noqa: N802
        if ev.modifiers() & Qt.ControlModifier:
            factor = 1.2 if ev.angleDelta().y() > 0 else 1 / 1.2
            self.editor.zoom_by(factor)
            ev.accept()
        else:
            super().wheelEvent(ev)

    def mousePressEvent(self, ev):  # noqa: N802
        if self.editor.tool == Tool.SELECT or ev.button() != Qt.LeftButton:
            super().mousePressEvent(ev)
            return
        # Snagit behavior: clicking an existing object (or one of its resize
        # grips) manipulates it no matter which tool is active.
        from .items import HandleItem
        item = self.itemAt(ev.position().toPoint())
        if item is not None and (is_annotation(item)
                                 or isinstance(item, HandleItem)):
            self._passthrough = True
            super().mousePressEvent(ev)
            return
        self.editor.begin_draw(self.mapToScene(ev.position().toPoint()))
        ev.accept()

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self._passthrough or self.editor.tool == Tool.SELECT \
                or not self.editor.drawing:
            super().mouseMoveEvent(ev)
            return
        self.editor.update_draw(self.mapToScene(ev.position().toPoint()))
        ev.accept()

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self._passthrough:
            self._passthrough = False
            super().mouseReleaseEvent(ev)
            return
        if self.editor.tool == Tool.SELECT or ev.button() != Qt.LeftButton:
            super().mouseReleaseEvent(ev)
            return
        if self.editor.drawing:
            self.editor.end_draw(self.mapToScene(ev.position().toPoint()))
        ev.accept()


class EditorWindow(QMainWindow):
    saved = Signal(str)  # emitted with file path after a successful save

    def __init__(self, path: str | None = None, image: QImage | None = None,
                 settings=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.settings = settings
        if image is None and path:
            image = QImage(path)
        if image is None or image.isNull():
            image = QImage(QSize(800, 500), QImage.Format_ARGB32_Premultiplied)
            image.fill(QColor("white"))

        self.scene = QGraphicsScene(self)
        self.base_item = QGraphicsPixmapItem()
        self.base_item.setZValue(-1000)
        self.scene.addItem(self.base_item)
        self.base_image = QImage()
        self.set_base_image(image)

        self.view = CanvasView(self)
        self.setCentralWidget(self.view)

        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._update_title)

        self.tool = Tool.SELECT
        self.color = QColor("#e3242b")
        self.stroke_width = 6
        self.font_size = 18
        self.step_counter = 1
        self.preview_only = False
        self._syncing_panel = False

        self.drawing = False
        self._draw_item = None
        self._draw_origin = QPointF()
        self._overlay: QGraphicsRectItem | None = None
        self._handles: list[HandleItem] = []
        self._adjusting = False
        self.scene.selectionChanged.connect(self._rebuild_handles)

        self._build_toolbar()
        self._build_panel()
        self._build_statusbar()
        self._update_title()
        self.resize(1100, 750)
        self._fit_if_large()

    # -- base image -------------------------------------------------------

    def load(self, path: str | None, image: QImage | None = None) -> bool:
        """Swap the editor to a different image, dropping edit history."""
        if image is None and path:
            image = QImage(path)
        if image is None or image.isNull():
            return False
        self.scene.clearSelection()
        for it in list(self.scene.items()):
            if is_annotation(it):
                self.scene.removeItem(it)
        self.path = path
        self.preview_only = False
        self.undo_stack.clear()
        self.step_counter = 1
        self.set_base_image(image)
        self.zoom_reset()
        self._fit_if_large()
        self._update_title()
        return True

    def load_preview(self, path: str, image: QImage) -> bool:
        """Show a stand-in image (e.g. a video poster). Saving never writes
        to `path`; it redirects to Save As."""
        if not self.load(None, image):
            return False
        self.path = path
        self.preview_only = True
        self._update_title()
        return True

    def maybe_save(self) -> bool:
        """Offer to save pending changes. False means the user cancelled."""
        if self.undo_stack.isClean():
            return True
        ret = QMessageBox.question(
            self, "grabbit", "Save changes to this image?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if ret == QMessageBox.Save:
            self.save()
            return self.undo_stack.isClean()
        return ret == QMessageBox.Discard

    def set_base_image(self, image: QImage) -> None:
        self.base_image = image
        self.base_item.setPixmap(QPixmap.fromImage(image))
        self.scene.setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self._update_status()

    def _fit_if_large(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableSize()
        img = self.base_image
        if img.width() > avail.width() * 0.8 or img.height() > avail.height() * 0.8:
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            self._update_status()

    # -- UI ----------------------------------------------------------------

    def _act(self, text: str, icon: str, shortcut=None, checkable=False):
        a = QAction(QIcon.fromTheme(icon), text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        return a

    def _build_toolbar(self) -> None:
        tb = QToolBar("Tools", self)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(22, 22))
        self.addToolBar(tb)

        group = QActionGroup(self)
        group.setExclusive(True)
        tools = [
            (Tool.SELECT, "Select", "edit-select", "V"),
            (Tool.ARROW, "Arrow", "draw-arrow", "A"),
            (Tool.LINE, "Line", "draw-line", "L"),
            (Tool.RECT, "Box", "draw-rectangle", "R"),
            (Tool.ELLIPSE, "Ellipse", "draw-ellipse", "E"),
            (Tool.PEN, "Pen", "draw-freehand", "P"),
            (Tool.HIGHLIGHT, "Highlight", "draw-highlight", "H"),
            (Tool.TEXT, "Text", "draw-text", "T"),
            (Tool.STEP, "Step", "format-list-ordered", "N"),
            (Tool.PIXELATE, "Pixelate", "view-private", "X"),
            (Tool.CROP, "Crop", "transform-crop", "C"),
            (Tool.CUTOUT_V, "Cut |", "edit-cut", "U"),
            (Tool.CUTOUT_H, "Cut —", "edit-cut", "Shift+U"),
        ]
        self._tool_actions = {}
        for tool, text, icon, key in tools:
            a = self._act(text, icon, key, checkable=True)
            a.triggered.connect(lambda _=False, t=tool: self.set_tool(t))
            group.addAction(a)
            tb.addAction(a)
            self._tool_actions[tool] = a
        self._tool_actions[Tool.SELECT].setChecked(True)

        tb.addSeparator()

        undo = self.undo_stack.createUndoAction(self, "Undo")
        undo.setIcon(QIcon.fromTheme("edit-undo"))
        undo.setShortcut(QKeySequence.Undo)
        redo = self.undo_stack.createRedoAction(self, "Redo")
        redo.setIcon(QIcon.fromTheme("edit-redo"))
        redo.setShortcut(QKeySequence.Redo)
        tb.addAction(undo)
        tb.addAction(redo)

        delete = self._act("Delete", "edit-delete", "Del")
        delete.triggered.connect(self.delete_selected)
        tb.addAction(delete)

        tb.addSeparator()

        save = self._act("Save", "document-save", QKeySequence.Save)
        save.triggered.connect(self.save)
        tb.addAction(save)

        save_as = self._act("Save As", "document-save-as", QKeySequence.SaveAs)
        save_as.triggered.connect(self.save_as)
        tb.addAction(save_as)

        copy = self._act("Copy", "edit-copy", QKeySequence.Copy)
        copy.triggered.connect(self.copy_to_clipboard)
        tb.addAction(copy)

        # zoom shortcuts (no toolbar buttons needed)
        for text, key, fn in [
            ("Zoom in", QKeySequence.ZoomIn, lambda: self.zoom_by(1.2)),
            ("Zoom out", QKeySequence.ZoomOut, lambda: self.zoom_by(1 / 1.2)),
            ("Actual size", "Ctrl+0", self.zoom_reset),
            ("Fit", "Ctrl+9", self.zoom_fit),
        ]:
            a = QAction(text, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            self.addAction(a)

    def _build_statusbar(self) -> None:
        self._status = QLabel(self)
        self.statusBar().addWidget(self._status)
        self._hint = QLabel(self)
        self.statusBar().addPermanentWidget(self._hint)
        self._update_status()

    def _update_status(self) -> None:
        if hasattr(self, "_status"):
            img = self.base_image
            zoom = int(self.view.transform().m11() * 100) if hasattr(self, "view") else 100
            self._status.setText(f"{img.width()} × {img.height()}  ·  {zoom}%")

    def _update_title(self) -> None:
        name = os.path.basename(self.path) if self.path else "untitled"
        dirty = "" if self.undo_stack.isClean() else " •"
        self.setWindowTitle(f"{name}{dirty} — grabbit")

    # -- properties panel (Snagit-style right sidebar) -----------------------

    def _build_panel(self) -> None:
        from PySide6.QtWidgets import (
            QDockWidget, QFormLayout, QPushButton, QWidget,
        )

        dock = QDockWidget("Properties", self)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setAllowedAreas(Qt.RightDockWidgetArea)
        w = QWidget(dock)
        form = QFormLayout(w)

        self.color_btn = QPushButton(w)
        self.color_btn.setToolTip("Color")
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Color", self.color_btn)

        self.width_spin = QSpinBox(w)
        self.width_spin.setRange(1, 32)
        self.width_spin.setValue(self.stroke_width)
        self.width_spin.valueChanged.connect(self._width_changed)
        form.addRow("Stroke", self.width_spin)

        self.font_spin = QSpinBox(w)
        self.font_spin.setRange(6, 96)
        self.font_spin.setValue(self.font_size)
        self.font_spin.valueChanged.connect(self._font_changed)
        form.addRow("Text size", self.font_spin)

        hint = QLabel("Applies to the selection\nand to new objects", w)
        hint.setStyleSheet("color: palette(mid);")
        form.addRow(hint)

        dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._update_color_swatch()
        self.scene.selectionChanged.connect(self._sync_panel)

    def _selected_annotations(self):
        return [i for i in self.scene.selectedItems() if is_annotation(i)]

    def _sync_panel(self) -> None:
        """Reflect the first selected object's style in the panel."""
        items = self._selected_annotations()
        if not items:
            return
        from .items import get_style
        style = get_style(items[0])
        self._syncing_panel = True
        try:
            if "color" in style:
                self.color = style["color"]
                self._update_color_swatch()
            if "width" in style:
                self.width_spin.setValue(style["width"])
            if "font_size" in style and style["font_size"] > 0:
                self.font_spin.setValue(style["font_size"])
        finally:
            self._syncing_panel = False

    def _apply_to_selection(self, **kwargs) -> None:
        from .items import apply_style
        items = self._selected_annotations()
        if not items:
            return
        for item in items:
            apply_style(item, **kwargs)
        self.undo_stack.resetClean()  # restyling counts as an edit

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self.color, self, "Annotation color")
        if not c.isValid():
            return
        self.color = c
        self._update_color_swatch()
        if not self._syncing_panel:
            self._apply_to_selection(color=c)

    def _update_color_swatch(self) -> None:
        pm = QPixmap(48, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self.color)
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.drawRoundedRect(1, 1, 46, 18, 4, 4)
        p.end()
        self.color_btn.setIcon(QIcon(pm))
        self.color_btn.setIconSize(pm.size())

    def _width_changed(self, w: int) -> None:
        self.stroke_width = w
        if not self._syncing_panel:
            self._apply_to_selection(width=w)

    def _font_changed(self, size: int) -> None:
        self.font_size = size
        if not self._syncing_panel:
            self._apply_to_selection(font_size=size)

    # -- tools -------------------------------------------------------------

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self._tool_actions[tool].setChecked(True)
        hints = {
            Tool.SELECT: "Drag to move · grips to resize · Del to delete",
            Tool.CROP: "Drag a rectangle to crop (Ctrl+Z undoes)",
            Tool.CUTOUT_V: "Drag across the vertical band to remove; left and right halves join",
            Tool.CUTOUT_H: "Drag across the horizontal band to remove; top and bottom join",
            Tool.TEXT: "Click for a label, or drag a box for wrapped text",
            Tool.STEP: "Click to stamp the next number",
            Tool.PIXELATE: "Drag a rectangle to pixelate",
        }
        self._hint.setText(hints.get(tool, ""))

    # -- zoom ----------------------------------------------------------------

    def zoom_by(self, factor: float) -> None:
        current = self.view.transform().m11()
        if 0.05 < current * factor < 16:
            self.view.scale(factor, factor)
        self._update_status()

    def zoom_reset(self) -> None:
        self.view.resetTransform()
        self._update_status()

    def zoom_fit(self) -> None:
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._update_status()

    # -- drawing -------------------------------------------------------------

    def begin_draw(self, pos: QPointF) -> None:
        self.drawing = True
        self._draw_origin = pos
        t = self.tool
        if t == Tool.ARROW:
            self._draw_item = ArrowItem(pos, pos, self.color, self.stroke_width)
        elif t == Tool.LINE:
            self._draw_item = LineItem(pos, pos, self.color, self.stroke_width)
        elif t == Tool.RECT:
            self._draw_item = RectItem(QRectF(pos, pos), self.color, self.stroke_width)
        elif t == Tool.ELLIPSE:
            self._draw_item = EllipseItem(QRectF(pos, pos), self.color, self.stroke_width)
        elif t == Tool.HIGHLIGHT:
            self._draw_item = HighlightItem(QRectF(pos, pos), QColor("#ffe000"))
        elif t == Tool.PEN:
            self._draw_item = FreehandItem(pos, self.color, self.stroke_width)
        elif t == Tool.STEP:
            self.drawing = False
            item = StepItem(pos, self.step_counter, self.color)
            self.undo_stack.push(AddItemCommand(self, item, "add step"))
            self._select_only(item)
            return
        elif t in (Tool.TEXT, Tool.PIXELATE, Tool.CROP,
                   Tool.CUTOUT_V, Tool.CUTOUT_H):
            self._overlay = QGraphicsRectItem()
            pen = QPen(QColor(0, 150, 255), 1, Qt.DashLine)
            pen.setCosmetic(True)
            self._overlay.setPen(pen)
            self._overlay.setBrush(QColor(0, 150, 255, 40))
            self._overlay.setZValue(10000)
            self.scene.addItem(self._overlay)
            return
        if self._draw_item is not None:
            self.scene.addItem(self._draw_item)

    def update_draw(self, pos: QPointF) -> None:
        t = self.tool
        item = self._draw_item
        if t in (Tool.ARROW, Tool.LINE) and item is not None:
            item.set_end(pos)
        elif t in (Tool.RECT, Tool.ELLIPSE) and item is not None:
            item.setRect(QRectF(self._draw_origin, pos).normalized())
        elif t == Tool.HIGHLIGHT and item is not None:
            item.setRect(QRectF(self._draw_origin, pos).normalized())
        elif t == Tool.PEN and item is not None:
            item.add_point(pos)
        elif self._overlay is not None:
            self._overlay.setRect(self._band_rect(pos))

    def end_draw(self, pos: QPointF) -> None:
        self.drawing = False
        t = self.tool
        if t in (Tool.ARROW, Tool.LINE, Tool.RECT, Tool.ELLIPSE, Tool.HIGHLIGHT, Tool.PEN):
            item, self._draw_item = self._draw_item, None
            if item is None:
                return
            # Discard degenerate click-without-drag shapes.
            if (pos - self._draw_origin).manhattanLength() < 3:
                self.scene.removeItem(item)
                return
            self.undo_stack.push(AddItemCommand(self, item))
            self._select_only(item)
        elif t in (Tool.TEXT, Tool.PIXELATE, Tool.CROP,
                   Tool.CUTOUT_V, Tool.CUTOUT_H):
            overlay, self._overlay = self._overlay, None
            if overlay is not None:
                self.scene.removeItem(overlay)
            rect = self._band_rect(pos).toRect()
            if t == Tool.TEXT:
                self._place_text(pos, rect)
                return
            if rect.width() < 4 or rect.height() < 4:
                return
            if t == Tool.PIXELATE:
                self._apply_pixelate(rect)
            elif t == Tool.CROP:
                self._apply_crop(rect)
            else:
                self._apply_cutout(t, rect)

    def _select_only(self, item) -> None:
        self.scene.clearSelection()
        item.setSelected(True)

    def _place_text(self, pos: QPointF, rect) -> None:
        """Click = auto-sizing label; drag = box with wrapped text."""
        boxed = rect.width() >= 24 and rect.height() >= 16
        anchor = QPointF(rect.topLeft()) if boxed else self._draw_origin
        item = TextItem(anchor, self.color, self.font_size)
        if boxed:
            item.setTextWidth(rect.width())
        self.undo_stack.push(AddItemCommand(self, item, "add text"))
        self._select_only(item)
        item.start_editing()

    def _band_rect(self, pos: QPointF) -> QRectF:
        """Selection rect; cut-out tools span the full image across the band."""
        r = QRectF(self._draw_origin, pos).normalized()
        sr = self.scene.sceneRect()
        if self.tool == Tool.CUTOUT_V:  # vertical band, full height
            r = QRectF(r.left(), sr.top(), r.width(), sr.height())
        elif self.tool == Tool.CUTOUT_H:  # horizontal band, full width
            r = QRectF(sr.left(), r.top(), sr.width(), r.height())
        return r

    # -- resize handles ----------------------------------------------------

    ROTATE_OFFSET = 28  # grip distance above the object's top edge

    def _handle_positions(self, t) -> dict[str, QPointF]:
        """Role → position (in the item's coordinates) for its grips."""
        if isinstance(t, (ArrowItem, LineItem)):
            p1, p2 = t.endpoints()
            return {"p1": p1, "p2": p2}
        if isinstance(t, (RectItem, EllipseItem, HighlightItem)):
            r = t.rect()
            # rotate grip sits ON the top edge midpoint: grips floating
            # outside the object miss hit-testing at some zoom levels
            return {"tl": r.topLeft(), "tr": r.topRight(),
                    "bl": r.bottomLeft(), "br": r.bottomRight(),
                    "rotate": QPointF(r.center().x(), r.top())}
        if isinstance(t, PixelateItem):
            r = t.rect()
            return {"tl": r.topLeft(), "tr": r.topRight(),
                    "bl": r.bottomLeft(), "br": r.bottomRight()}
        if isinstance(t, TextItem):
            br = t.boundingRect()
            return {"font": br.bottomRight(),
                    "width": QPointF(br.right(), br.center().y()),
                    "rotate": QPointF(br.center().x(), br.top())}
        if isinstance(t, StepItem):
            return {"radius": QPointF(t.radius, 0)}
        return {}

    def _rebuild_handles(self) -> None:
        for h in self._handles:
            h.setParentItem(None)  # detach or undo of a flatten revives them
            if h.scene() is not None:
                h.scene().removeItem(h)
        self._handles = []
        sel = self._selected_annotations()
        if len(sel) != 1:
            return
        t = sel[0]
        for role, pos in self._handle_positions(t).items():
            h = HandleItem(t, role, self._handle_pressed, self._handle_moved,
                           self._handle_released)
            h.place(pos)
            self._handles.append(h)

    def _place_handles(self, t) -> None:
        positions = self._handle_positions(t)
        for h in self._handles:
            if h.role in positions:
                h.place(positions[h.role])

    def snapshot(self, t) -> dict:
        s = {"pos": QPointF(t.pos()), "rotation": t.rotation(),
             "origin": QPointF(t.transformOriginPoint())}
        if isinstance(t, (ArrowItem, LineItem)):
            s["p1"], s["p2"] = t.endpoints()
        elif hasattr(t, "rect"):
            from PySide6.QtCore import QRectF as _R
            s["rect"] = _R(t.rect())
        if isinstance(t, TextItem):
            s["font_size"] = t.font().pointSize()
            s["text_width"] = t.textWidth()
        if isinstance(t, StepItem):
            s["radius"] = t.radius
        return s

    def apply_snapshot(self, t, s: dict) -> None:
        t.setTransformOriginPoint(s["origin"])
        t.setRotation(s["rotation"])
        t.setPos(s["pos"])
        if "p1" in s:
            t.set_start(s["p1"])
            t.set_end(s["p2"])
        elif "rect" in s:
            t.setRect(s["rect"])
        if "font_size" in s and isinstance(t, TextItem):
            f = t.font()
            f.setPointSize(int(s["font_size"]))
            t.setFont(f)
            t.setTextWidth(s["text_width"])
        if "radius" in s and isinstance(t, StepItem):
            t.set_radius(s["radius"])
        if t.isSelected():
            self._place_handles(t)

    @staticmethod
    def _snapshots_differ(a: dict, b: dict) -> bool:
        return any(a[k] != b[k] for k in a)

    @staticmethod
    def _set_origin_keeping_position(t, c: QPointF) -> None:
        """Move the transform origin without the visual jump."""
        if t.transformOriginPoint() == c:
            return
        old = t.mapToScene(c)
        t.setTransformOriginPoint(c)
        new = t.mapToScene(c)
        t.setPos(t.pos() + old - new)

    def _handle_pressed(self, t, role: str) -> dict:
        state = {"snapshot": self.snapshot(t)}
        if role == "font" and isinstance(t, TextItem):
            state.update({"font0": t.font().pointSizeF(),
                          "h0": max(1.0, t.boundingRect().height())})
        elif role == "rotate":
            c = (t.rect().center() if hasattr(t, "rect")
                 else t.boundingRect().center())
            self._set_origin_keeping_position(t, c)
            state.update({"center_local": c, "rot0": t.rotation()})
        return state

    def _handle_released(self, t, role: str, state: dict) -> None:
        before = state.get("snapshot")
        if before is None:
            return
        after = self.snapshot(t)
        if self._snapshots_differ(before, after):
            self.undo_stack.push(GripCommand(self, t, before, after))

    def _handle_moved(self, t, role: str, pos: QPointF, state: dict) -> None:
        if self._adjusting:
            return
        self._adjusting = True
        try:
            if role == "p1":
                t.set_start(pos)
            elif role == "p2":
                t.set_end(pos)
            elif role in ("tl", "tr", "bl", "br"):
                r = t.rect()
                {"tl": r.setTopLeft, "tr": r.setTopRight,
                 "bl": r.setBottomLeft, "br": r.setBottomRight}[role](pos)
                t.setRect(r)
            elif role == "font" and isinstance(t, TextItem):
                factor = pos.y() / state.get("h0", 1.0)
                size = max(6, min(96, round(state.get("font0", 18) * factor)))
                f = t.font()
                f.setPointSize(size)
                t.setFont(f)
            elif role == "width" and isinstance(t, TextItem):
                t.setTextWidth(max(40.0, pos.x()))
            elif role == "rotate":
                pass  # HandleItem rotates the parent itself (scene-angle math)
            elif role == "radius" and isinstance(t, StepItem):
                import math
                t.set_radius(math.hypot(pos.x(), pos.y()))
            if role != "rotate":
                self._place_handles(t)
        finally:
            self._adjusting = False

    # -- destructive ops -------------------------------------------------------

    def flattened(self) -> QImage:
        self.scene.clearSelection()
        size = self.base_image.size()
        img = QImage(size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        self.scene.render(p, QRectF(0, 0, size.width(), size.height()),
                          self.scene.sceneRect())
        p.end()
        return img

    def _apply_pixelate(self, rect: QRect) -> None:
        img = self.base_image
        clamped = rect.intersected(QRect(0, 0, img.width(), img.height()))
        if clamped.width() < 4 or clamped.height() < 4:
            return
        item = PixelateItem(lambda: self.base_image, QRectF(clamped))
        self.undo_stack.push(AddItemCommand(self, item, "pixelate"))
        self._select_only(item)

    def _apply_crop(self, rect: QRect) -> None:
        new_image = imageops.crop(self.flattened(), rect)
        self.undo_stack.push(FlattenCommand(self, new_image, "crop"))

    def _apply_cutout(self, tool: Tool, r: QRect) -> None:
        flat = self.flattened()
        if r.isEmpty():
            return
        # note: QRect.right()/bottom() are x+w-1, not the true edge
        if tool == Tool.CUTOUT_V:
            new_image = imageops.cut_out(flat, r.x(), r.x() + r.width(),
                                         horizontal=False)
        else:
            new_image = imageops.cut_out(flat, r.y(), r.y() + r.height(),
                                         horizontal=True)
        self.undo_stack.push(FlattenCommand(self, new_image, "cut out"))

    # -- edit actions ---------------------------------------------------------

    def delete_selected(self) -> None:
        items = [i for i in self.scene.selectedItems() if is_annotation(i)]
        if items:
            self.undo_stack.push(RemoveItemsCommand(self, items))

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setImage(self.flattened())
        self.statusBar().showMessage("Copied to clipboard", 2500)

    def save(self) -> None:
        if not self.path or self.preview_only:
            self.save_as()
            return
        self._cleanup_empty_text()
        if self.flattened().save(self.path):
            self.undo_stack.setClean()
            self.saved.emit(self.path)
            self.statusBar().showMessage("Saved", 2000)
        else:
            QMessageBox.warning(self, "grabbit", f"Could not save {self.path}")

    def save_as(self) -> None:
        start_dir = (self.settings.library_dir if self.settings
                     else os.path.expanduser("~/Pictures"))
        suggestion = self.path or os.path.join(start_dir, "annotated.png")
        if self.preview_only:
            base = os.path.splitext(os.path.basename(suggestion))[0]
            suggestion = os.path.join(start_dir, f"{base}.png")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save image", suggestion, "Images (*.png *.jpg *.webp)")
        if not path:
            return
        self.path = path
        self.preview_only = False
        self.save()

    def _cleanup_empty_text(self) -> None:
        for it in list(self.scene.items()):
            if isinstance(it, TextItem) and not it.toPlainText().strip():
                self.scene.removeItem(it)

    # -- window ----------------------------------------------------------------

    def closeEvent(self, ev):  # noqa: N802
        ev.accept() if self.maybe_save() else ev.ignore()
