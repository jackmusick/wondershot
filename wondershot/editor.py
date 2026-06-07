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


_checker_cache = None


def _checker_brush():
    """16px light/dark checkerboard — the universal 'transparent' backdrop."""
    global _checker_cache
    if _checker_cache is None:
        from PySide6.QtGui import QBrush
        tile = QPixmap(16, 16)
        tile.fill(QColor(70, 70, 76))
        p = QPainter(tile)
        p.fillRect(0, 0, 8, 8, QColor(54, 54, 60))
        p.fillRect(8, 8, 8, 8, QColor(54, 54, 60))
        p.end()
        _checker_cache = QBrush(tile)
    return _checker_cache


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


class SetBaseImageCommand(QUndoCommand):
    """Swap only the base image, keeping annotations on the scene.

    FlattenCommand minus the annotation fold — Remove Background changes
    the pixels underneath but must not eat the user's markup.
    """

    def __init__(self, editor: "EditorWindow", new_image: QImage, text: str):
        super().__init__(text)
        self.editor = editor
        self.old_image = editor.base_image
        self.new_image = new_image

    def redo(self):
        self.editor.set_base_image(self.new_image)

    def undo(self):
        self.editor.set_base_image(self.old_image)


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

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        # Keep the image fitted as the window resizes (Snagit behavior),
        # but only while the user is in fit mode.
        if getattr(self.editor, "_fit_mode", False):
            self.editor.zoom_fit()

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
    share_status = Signal(str)  # share outcome, for toast surfaces

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
        # Checkerboard mat behind the image: padding lets the rounded
        # corners / bottom fade read as transparency instead of vanishing
        # into the dark canvas. Hidden during flatten so it never bakes in.
        self.mat_item = QGraphicsRectItem()
        self.mat_item.setZValue(-2000)
        self.mat_item.setPen(QPen(Qt.NoPen))
        self.mat_item.setBrush(_checker_brush())
        self.scene.addItem(self.mat_item)
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
        s = self.settings
        self.color = QColor(s.tool_color if s else "#e3242b")
        self.stroke_width = s.stroke_width if s else 10
        self.font_size = s.font_size if s else 24
        self.step_counter = 1
        self.preview_only = False
        self._fit_mode = True  # fit-to-window until the user picks a zoom
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
        self._fit_if_large()  # fit-to-window by default
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
            self, "Wondershot", "Save changes to this image?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if ret == QMessageBox.Save:
            self.save()
            return self.undo_stack.isClean()
        return ret == QMessageBox.Discard

    # Padding around the image so rounded corners / fade are visible
    # against the mat (proportional, capped).
    def _mat_margin(self) -> int:
        if not (self.settings and (getattr(self.settings, "effect_rounded",
                                            False)
                 or getattr(self.settings, "effect_fade", False))):
            return 0
        return max(24, min(80, self.base_image.width() // 12))

    def set_base_image(self, image: QImage) -> None:
        self.base_image = image
        self.base_item.setPixmap(QPixmap.fromImage(self.apply_effects(image)))
        self._reflow_scene()
        self._update_status()

    def _reflow_scene(self) -> None:
        w, h = self.base_image.width(), self.base_image.height()
        m = self._mat_margin()
        self.mat_item.setVisible(m > 0)
        self.mat_item.setRect(QRectF(-m, -m, w + 2 * m, h + 2 * m))
        self.scene.setSceneRect(QRectF(-m, -m, w + 2 * m, h + 2 * m))

    def apply_effects(self, img: QImage) -> QImage:
        """Output effects (rounded corners, bottom fade) — persisted
        defaults, applied to the preview and at flatten time."""
        s = self.settings
        if not s:
            return img
        if getattr(s, "effect_rounded", False):
            img = imageops.rounded_corners(img, s.effect_corner_radius)
        if getattr(s, "effect_fade", False):
            img = imageops.bottom_fade(img, s.effect_fade_height)
        return img

    def _refresh_effect_preview(self) -> None:
        self.base_item.setPixmap(
            QPixmap.fromImage(self.apply_effects(self.base_image)))
        self._reflow_scene()  # margin appears/disappears with the effects

    def _fit_if_large(self) -> None:
        # Default to fit-to-window so images never overflow the viewport
        # (no more scrolling just to see the whole shot). Small images
        # stay at 100% because zoom_fit() caps upscaling.
        self.zoom_fit()

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

        # File ops left the toolbar (Snagit-style: tools only) — they
        # live on shortcuts and in the carousel's context menu.
        for text, icon, key, fn in [
            ("Delete", "edit-delete", "Del", self.delete_selected),
            ("Save", "document-save", QKeySequence.Save, self.save),
            ("Save As", "document-save-as", QKeySequence.SaveAs,
             self.save_as),
            ("Copy", "edit-copy", QKeySequence.Copy, self.copy_to_clipboard),
        ]:
            a = self._act(text, icon, key)
            a.triggered.connect(fn)
            self.addAction(a)  # window-level: keeps the shortcut alive

        tb.addSeparator()
        self.redact_action = self._act("AI Redact", "view-private")
        self.redact_action.setToolTip(
            "Find and pixelate sensitive text (Settings → AI)")
        self.redact_action.triggered.connect(self.ai_redact)
        tb.addAction(self.redact_action)

        from . import bgremove
        self.bg_action = self._act("Remove BG", "edit-clear-all")
        self.bg_action.triggered.connect(self.remove_background)
        tb.addAction(self.bg_action)
        if not bgremove.available():
            self.bg_action.setEnabled(False)
            self.bg_action.setToolTip(
                "Needs the optional extra: pip install wondershot[ai-local]")
        else:
            self.bg_action.setToolTip(
                "Make the background transparent (local ONNX)")

        from PySide6.QtWidgets import QMenu, QSizePolicy, QToolButton, QWidget
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.share_btn = QToolButton(self)
        self.share_btn.setText("Share")
        self.share_btn.setIcon(QIcon.fromTheme("document-send"))
        self.share_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.share_btn.clicked.connect(self._share_default)
        self._share_menu = QMenu(self.share_btn)
        self.share_action = tb.addWidget(self.share_btn)
        self._update_share_button()

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

    # -- sharing -------------------------------------------------------------

    def _share_providers(self) -> list[str]:
        from .share import configured_providers
        return configured_providers(self.settings) if self.settings else []

    def _update_share_button(self) -> None:
        from PySide6.QtWidgets import QToolButton
        providers = self._share_providers()
        self.share_btn.setToolTip(
            "Copy a share link" if providers
            else "Set up sharing in Settings → Sharing")
        self._share_menu.clear()
        if len(providers) > 1:
            labels = {"s3": "Share via S3", "azure": "Share via Azure",
                      "onedrive": "Share via OneDrive"}
            for p in providers:
                self._share_menu.addAction(
                    labels[p], lambda p=p: self.share_path(self.path, p))
            self.share_btn.setMenu(self._share_menu)
            self.share_btn.setPopupMode(QToolButton.MenuButtonPopup)
        else:
            self.share_btn.setMenu(None)

    def _share_default(self) -> None:
        providers = self._share_providers()
        if not providers:
            msg = "No sharing configured — Settings → Sharing"
            self.statusBar().showMessage(msg, 6000)
            self.share_status.emit(msg)
            return
        default = self.settings.share_provider
        self.share_path(self.path,
                        default if default in providers else providers[0])

    def share_path(self, path: str | None, provider: str) -> None:
        """Upload `path` and put the share URL on the clipboard."""
        from PySide6.QtCore import QThreadPool
        from .share import ShareJob
        if path == self.path and path and not self.undo_stack.isClean():
            self.save()  # share what's on the canvas, not a stale file
        if not path:
            self.statusBar().showMessage("Nothing to share — save first",
                                         4000)
            return
        self.settings.share_provider = provider  # clicking selects default
        self.share_btn.setEnabled(False)
        self.statusBar().showMessage("Uploading…")
        self.share_status.emit("Uploading…")
        job = ShareJob(self.settings, path, provider)
        job.emitter.done.connect(self._share_done)
        self._share_job = job  # keep the signal emitter alive
        QThreadPool.globalInstance().start(job)

    def _share_done(self, url: str, error: str) -> None:
        self.share_btn.setEnabled(True)
        if error:
            msg = f"Share failed: {error}"
        else:
            QGuiApplication.clipboard().setText(url)
            msg = "Copied URL to clipboard"
        self.statusBar().showMessage(msg, 10000 if error else 5000)
        self.share_status.emit(msg)

    # -- AI actions -----------------------------------------------------------

    def _start_ai_job(self, fn, label: str, on_done) -> None:
        """Run `fn` on the thread pool behind a cancelable progress dialog."""
        from PySide6.QtCore import QThreadPool
        from PySide6.QtWidgets import QProgressDialog
        from .aiclient import AIJob
        job = AIJob(fn)
        dlg = QProgressDialog(label, "Cancel", 0, 0, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.canceled.connect(lambda: setattr(job, "cancel", True))
        job.emitter.done.connect(
            lambda result, error: (dlg.close(), on_done(result, error)))
        self._ai_job = job  # keep the signal emitter alive
        QThreadPool.globalInstance().start(job)

    def ai_redact(self) -> None:
        from .aiclient import ai_configured
        from . import redact
        if not (self.settings and ai_configured(self.settings)):
            self.statusBar().showMessage(
                "Configure an AI endpoint in Settings → AI first", 6000)
            return
        s = self.settings
        image = self.base_image.copy()  # snapshot off the GUI thread's state
        endpoint, key, model = s.ai_endpoint, s.ai_api_key, s.ai_model
        self._start_ai_job(
            lambda: redact.redact_regions(image, endpoint, key, model),
            "Finding sensitive text…", self._redact_done)

    def _redact_done(self, rects, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Wondershot",
                                f"AI Redact failed: {error}")
            return
        self.apply_redact_regions(rects or [])

    def apply_redact_regions(self, rects) -> int:
        """Add a PixelateItem per region — non-destructive, one undo step."""
        img_rect = QRect(0, 0, self.base_image.width(),
                         self.base_image.height())
        clamped = []
        for r in rects:
            c = QRect(r).intersected(img_rect)
            if c.width() >= 4 and c.height() >= 4:
                clamped.append(c)
        if clamped:
            self.undo_stack.beginMacro("AI redact")
            try:
                for c in clamped:
                    item = PixelateItem(lambda: self.base_image, QRectF(c))
                    self.undo_stack.push(
                        AddItemCommand(self, item, "AI redact"))
            finally:
                self.undo_stack.endMacro()
        msg = (f"AI Redact: pixelated {len(clamped)} region(s) — review, "
               "adjust, then save" if clamped
               else "AI Redact: nothing sensitive found")
        self.statusBar().showMessage(msg, 8000)
        return len(clamped)

    def remove_background(self) -> None:
        from . import bgremove
        if not bgremove.available():
            return  # action should be disabled anyway
        image = self.base_image.copy()
        self._start_ai_job(lambda: bgremove.remove_background(image),
                           "Removing background…", self._bg_done)

    def _bg_done(self, image, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Wondershot",
                                f"Remove Background failed: {error}")
            return
        self.undo_stack.push(
            SetBaseImageCommand(self, image, "remove background"))
        self.statusBar().showMessage(
            "Background removed — save as PNG to keep transparency", 8000)

    def _build_statusbar(self) -> None:
        from PySide6.QtWidgets import QComboBox, QToolButton
        self._status = QLabel(self)
        self.statusBar().addWidget(self._status)
        self._hint = QLabel(self)
        self.statusBar().addPermanentWidget(self._hint)

        zoom_out = QToolButton(self)
        zoom_out.setText("−")
        zoom_out.setToolTip("Zoom out (Ctrl+-)")
        zoom_out.clicked.connect(lambda: self.zoom_by(1 / 1.2))
        self.zoom_combo = QComboBox(self)
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.NoInsert)
        self.zoom_combo.addItems(["Fit", "25%", "50%", "75%", "100%",
                                  "150%", "200%", "400%"])
        self.zoom_combo.setFixedWidth(74)
        self.zoom_combo.lineEdit().setAlignment(Qt.AlignCenter)
        self.zoom_combo.textActivated.connect(self._zoom_text)
        zoom_in = QToolButton(self)
        zoom_in.setText("+")
        zoom_in.setToolTip("Zoom in (Ctrl++)")
        zoom_in.clicked.connect(lambda: self.zoom_by(1.2))
        fit_btn = QToolButton(self)
        fit_btn.setText("Fit")
        fit_btn.setToolTip("Fit to window (Ctrl+9)")
        fit_btn.clicked.connect(self.zoom_fit)
        for wdg in (zoom_out, self.zoom_combo, zoom_in, fit_btn):
            self.statusBar().addPermanentWidget(wdg)
        self._update_status()

    def _zoom_text(self, text: str) -> None:
        t = text.strip().lower().rstrip("%").strip()
        if t.startswith("fit"):
            self.zoom_fit()
            return
        try:
            self.set_zoom(float(t) / 100.0)
        except ValueError:
            self._update_status()  # revert the edit field

    def _update_status(self) -> None:
        if hasattr(self, "_status"):
            img = self.base_image
            self._status.setText(f"{img.width()} × {img.height()}")
        if hasattr(self, "zoom_combo"):
            self.zoom_combo.blockSignals(True)
            if getattr(self, "_fit_mode", False):
                self.zoom_combo.setEditText("Fit")
            else:
                zoom = int(self.view.transform().m11() * 100)
                self.zoom_combo.setEditText(f"{zoom}%")
            self.zoom_combo.blockSignals(False)

    def _update_title(self) -> None:
        name = os.path.basename(self.path) if self.path else "untitled"
        dirty = "" if self.undo_stack.isClean() else " •"
        self.setWindowTitle(f"{name}{dirty} — Wondershot")

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

        from PySide6.QtWidgets import QCheckBox
        effects_title = QLabel("<b>Effects</b>", w)
        form.addRow(effects_title)

        def effect_toggle(label, attr):
            box = QCheckBox(label, w)
            box.setChecked(bool(self.settings
                                and getattr(self.settings, attr, False)))
            box.toggled.connect(lambda on: self._effect_changed(attr, on))
            form.addRow(box)
            return box

        self.rounded_check = effect_toggle("Rounded corners",
                                           "effect_rounded")
        self.radius_spin = QSpinBox(w)
        self.radius_spin.setRange(2, 64)
        self.radius_spin.setValue(
            getattr(self.settings, "effect_corner_radius", 16) or 16
            if self.settings else 16)
        self.radius_spin.valueChanged.connect(
            lambda v: self._effect_changed("effect_corner_radius", v))
        form.addRow("Radius", self.radius_spin)

        self.fade_check = effect_toggle("Bottom fade", "effect_fade")
        self.fade_spin = QSpinBox(w)
        self.fade_spin.setRange(8, 512)
        self.fade_spin.setValue(
            getattr(self.settings, "effect_fade_height", 96) or 96
            if self.settings else 96)
        self.fade_spin.valueChanged.connect(
            lambda v: self._effect_changed("effect_fade_height", v))
        form.addRow("Fade height", self.fade_spin)

        hint = QLabel("Applies to the selection\nand to new objects", w)
        hint.setStyleSheet("color: palette(mid);")
        form.addRow(hint)

        dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._panel_form = form
        self._update_color_swatch()
        self._update_panel_rows()
        self.scene.selectionChanged.connect(self._sync_panel)

    def _update_panel_rows(self) -> None:
        """Only show the rows that apply: stroke for shapes, size for text."""
        from .items import get_style
        items = self._selected_annotations()
        if items:
            styles = [get_style(i) for i in items]
            stroke = any("width" in s for s in styles)
            text = any("font_size" in s for s in styles)
        else:  # nothing selected: follow the active tool
            stroke = self.tool in (Tool.ARROW, Tool.LINE, Tool.RECT,
                                   Tool.ELLIPSE, Tool.PEN, Tool.SELECT)
            text = self.tool in (Tool.TEXT, Tool.SELECT)
        self._panel_form.setRowVisible(self.width_spin, stroke)
        self._panel_form.setRowVisible(self.font_spin, text)

    def _selected_annotations(self):
        return [i for i in self.scene.selectedItems() if is_annotation(i)]

    def _sync_panel(self) -> None:
        """Reflect the first selected object's style in the panel."""
        self._update_panel_rows()
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
        if self.settings:
            self.settings.tool_color = c.name()
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

    def _effect_changed(self, attr: str, value) -> None:
        if self.settings:
            setattr(self.settings, attr, value)
        self._refresh_effect_preview()

    def _width_changed(self, w: int) -> None:
        self.stroke_width = w
        if self._syncing_panel:
            return
        if self.settings:
            self.settings.stroke_width = w
        self._apply_to_selection(width=w)

    def _font_changed(self, size: int) -> None:
        self.font_size = size
        if self._syncing_panel:
            return
        if self.settings:
            self.settings.font_size = size
        self._apply_to_selection(font_size=size)

    # -- tools -------------------------------------------------------------

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self._tool_actions[tool].setChecked(True)
        self._update_panel_rows()
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
        target = max(0.05, min(16, current * factor))
        self.set_zoom(target)

    def set_zoom(self, scale: float) -> None:
        self._fit_mode = False
        self.view.resetTransform()
        self.view.scale(scale, scale)
        self._update_status()

    def zoom_reset(self) -> None:
        self.set_zoom(1.0)

    def zoom_fit(self) -> None:
        """Fit the image in the viewport (never upscaling past 100%)."""
        self._fit_mode = True
        self.view.resetTransform()
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        if self.view.transform().m11() > 1.0:
            self.view.resetTransform()  # small images stay at actual size
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
        # Image bounds (not sceneRect — that now includes the effect mat).
        sr = QRectF(0, 0, self.base_image.width(), self.base_image.height())
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
        # Render only the image rect (exclude the mat/padding), and hide
        # the checkerboard so transparent corners stay transparent. The
        # base pixmap already carries the effects, so don't re-apply.
        mat_was = self.mat_item.isVisible()
        self.mat_item.setVisible(False)
        self.scene.render(p, QRectF(0, 0, size.width(), size.height()),
                          QRectF(0, 0, size.width(), size.height()))
        self.mat_item.setVisible(mat_was)
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
            QMessageBox.warning(self, "Wondershot", f"Could not save {self.path}")

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
