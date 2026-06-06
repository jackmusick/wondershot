"""Main window: big markup editor on top, filmstrip carousel underneath.

Snagit-style layout — the carousel shows the screenshot library; selecting a
thumbnail loads it into the editor, and thumbnails drag out as files.
"""

from __future__ import annotations

import os

from PySide6.QtCore import (
    QFileSystemWatcher,
    QItemSelectionModel,
    QMimeData,
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLabel,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .editor import EditorWindow

PATH_ROLE = Qt.UserRole + 1
THUMB_SIZE = QSize(170, 105)
CAROUSEL_HEIGHT = 158
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


class _ThumbSignal(QObject):
    done = Signal(str, QImage)


class _ThumbJob(QRunnable):
    def __init__(self, path: str, emitter: _ThumbSignal):
        super().__init__()
        self.path = path
        self.emitter = emitter

    def run(self):
        if is_video(self.path):
            img = self._video_frame()
        else:
            img = QImage(self.path)
            if img.isNull():
                # The file may still be mid-write (watcher fires on creation).
                import time
                time.sleep(0.4)
                img = QImage(self.path)
        if not img.isNull():
            scaled = img.scaled(THUMB_SIZE, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
            # Compose onto a fixed-size canvas so every thumbnail is
            # identically sized and centered in its carousel cell.
            canvas = QImage(THUMB_SIZE, QImage.Format_ARGB32_Premultiplied)
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            p.drawImage((THUMB_SIZE.width() - scaled.width()) // 2,
                        (THUMB_SIZE.height() - scaled.height()) // 2, scaled)
            if is_video(self.path):
                self._draw_play_badge(p, canvas)
            p.end()
            img = canvas
        self.emitter.done.emit(self.path, img)

    def _video_frame(self) -> QImage:
        """Poster frame via ffmpegthumbnailer/ffmpeg, else a dark slate."""
        import shutil
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            out = tf.name
        try:
            if shutil.which("ffmpegthumbnailer"):
                r = subprocess.run(
                    ["ffmpegthumbnailer", "-i", self.path, "-o", out,
                     "-s", "512", "-q", "8"],
                    capture_output=True, timeout=15)
            elif shutil.which("ffmpeg"):
                r = subprocess.run(
                    ["ffmpeg", "-y", "-ss", "1", "-i", self.path,
                     "-frames:v", "1", out],
                    capture_output=True, timeout=15)
            else:
                r = None
            img = QImage(out) if r is not None and r.returncode == 0 else QImage()
        except (OSError, subprocess.TimeoutExpired):
            img = QImage()
        finally:
            if os.path.exists(out):
                os.unlink(out)
        if img.isNull():
            img = QImage(THUMB_SIZE, QImage.Format_ARGB32_Premultiplied)
            img.fill(QColor(40, 40, 46))
        return img

    @staticmethod
    def _draw_play_badge(p: QPainter, canvas: QImage) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPolygonF
        cx, cy, r = canvas.width() / 2, canvas.height() / 2, 19
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawPolygon(QPolygonF([
            QPointF(cx - 6, cy - 9), QPointF(cx - 6, cy + 9),
            QPointF(cx + 10, cy),
        ]))


class GalleryModel(QStandardItemModel):
    """Standard model that serves file URLs (and raw image data) on drag-out."""

    def mimeData(self, indexes) -> QMimeData:  # noqa: N802
        mime = QMimeData()
        paths = [self.data(i, PATH_ROLE) for i in indexes if i.column() == 0]
        paths = [p for p in paths if p]
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        if len(paths) == 1:
            img = QImage(paths[0])
            if not img.isNull():
                mime.setImageData(img)
        return mime

    def mimeTypes(self):  # noqa: N802
        return ["text/uri-list", "image/png"]

    def supportedDragActions(self):  # noqa: N802
        return Qt.CopyAction


def _placeholder_image() -> QImage:
    img = QImage(900, 520, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(46, 46, 50))
    p = QPainter(img)
    p.setPen(QColor(160, 160, 165))
    f = p.font()
    f.setPointSize(16)
    p.setFont(f)
    p.drawText(img.rect(), Qt.AlignCenter,
               "No screenshots yet\n\nCapture a region to get started")
    p.end()
    return img


def _video_placeholder(path: str) -> QImage:
    """Poster frame (if extractable) with a playback hint."""
    poster = _ThumbJob(path, _ThumbSignal())._video_frame()
    img = poster.scaled(900, 520, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p = QPainter(img)
    p.fillRect(img.rect().adjusted(0, img.height() - 44, 0, 0),
               QColor(0, 0, 0, 170))
    p.setPen(QColor(235, 235, 235))
    f = p.font()
    f.setPointSize(11)
    p.setFont(f)
    p.drawText(img.rect().adjusted(12, img.height() - 44, -12, 0),
               Qt.AlignVCenter | Qt.AlignLeft,
               f"▶ {os.path.basename(path)} — double-click thumbnail to play")
    p.end()
    return img


class GalleryWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(self, settings, capture, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.capture = capture
        self._windows: list[EditorWindow] = []
        self._thumb_pool = QThreadPool(self)
        self._thumb_emitter = _ThumbSignal()
        self._thumb_emitter.done.connect(self._thumb_ready)
        self._really_quit = False

        # -- embedded editor (QMainWindow works fine as a child widget) ----
        self.editor = EditorWindow(image=_placeholder_image(),
                                   settings=self.settings)
        self.editor.setWindowFlags(Qt.Widget)
        self.editor.saved.connect(self.refresh_path)
        self.editor.undo_stack.cleanChanged.connect(
            lambda _c: self._update_title())
        self._current_path: str | None = None

        # -- video pane (optional: needs QtMultimedia's ffmpeg backend) ----
        try:
            from .video import VideoPane
            self.video_pane = VideoPane(self.settings)
            self.video_pane.status.connect(
                lambda msg, ms: self.editor.statusBar().showMessage(msg, ms))
            self.video_pane.gif_ready.connect(self._gif_ready)
        except ImportError:
            self.video_pane = None

        # -- carousel -------------------------------------------------------
        self.model = GalleryModel(self)
        self.strip = QListView(self)
        self.strip.setModel(self.model)
        self.strip.setViewMode(QListView.IconMode)
        self.strip.setFlow(QListView.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setResizeMode(QListView.Adjust)
        self.strip.setMovement(QListView.Static)
        self.strip.setIconSize(THUMB_SIZE)
        self.strip.setGridSize(QSize(THUMB_SIZE.width() + 16,
                                     THUMB_SIZE.height() + 16))
        self.strip.setSpacing(6)
        self.strip.setFixedHeight(CAROUSEL_HEIGHT)
        self.strip.setSelectionMode(QListView.ExtendedSelection)
        self.strip.setDragEnabled(True)
        self.strip.setDragDropMode(QListView.DragOnly)
        self.strip.setEditTriggers(QListView.NoEditTriggers)
        self.strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.strip.setContextMenuPolicy(Qt.CustomContextMenu)
        self.strip.customContextMenuRequested.connect(self._context_menu)
        # Distinct shelf look: clearly darker background than the canvas,
        # thumbnails sit as raised cards with hover/selection chrome.
        self.strip.setStyleSheet("""
            QListView {
                background: #18181b;
                border: none;
                border-top: 2px solid #44444c;
                padding: 6px;
            }
            QListView::item {
                background: #2b2b31;
                border-radius: 8px;
                border: 2px solid #36363d;
            }
            QListView::item:hover { border: 2px solid #56565f; }
            QListView::item:selected {
                background: #28394a;
                border: 2px solid #3daee9;
            }
        """)
        self.strip.selectionModel().selectionChanged.connect(
            self._selection_changed)
        self.strip.doubleClicked.connect(self._double_clicked)

        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.editor)
        if self.video_pane is not None:
            self.stack.addWidget(self.video_pane)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.strip, 0)
        self.setCentralWidget(central)

        self.watcher = QFileSystemWatcher(self)
        # Debounce: spectacle/portal write files in several chunks.
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(350)
        self._rescan_timer.timeout.connect(self.rescan)
        self.watcher.directoryChanged.connect(
            lambda _p: self._rescan_timer.start())

        self._build_toolbar()
        self._counter = QLabel(self)
        self.editor.statusBar().addPermanentWidget(self._counter)

        self._update_title()
        self.resize(1280, 860)
        self._apply_pin()
        self.set_library(self.settings.library_dir)

    # -- library --------------------------------------------------------------

    def set_library(self, directory: str) -> None:
        os.makedirs(directory, exist_ok=True)
        for d in self.watcher.directories():
            self.watcher.removePath(d)
        self.watcher.addPath(directory)
        self.rescan()

    def _list_library(self) -> list[str]:
        directory = self.settings.library_dir
        try:
            entries = [
                os.path.join(directory, n)
                for n in os.listdir(directory)
                if os.path.splitext(n)[1].lower() in (IMAGE_EXTS | VIDEO_EXTS)
            ]
        except OSError:
            return []
        entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return entries

    def rescan(self) -> None:
        entries = self._list_library()

        # Copy icons out before the model clear deletes the C++ items.
        existing: dict[str, QIcon] = {}
        for row in range(self.model.rowCount()):
            it = self.model.item(row)
            existing[it.data(PATH_ROLE)] = it.icon()

        with_signals_blocked(self.strip.selectionModel(), self.model.clear)
        for path in entries:
            old_icon = existing.pop(path, None)
            item = QStandardItem()
            item.setData(path, PATH_ROLE)
            item.setDragEnabled(True)
            item.setToolTip(os.path.basename(path))
            if old_icon is not None and not old_icon.isNull():
                item.setIcon(old_icon)
            else:
                self._thumb_pool.start(_ThumbJob(path, self._thumb_emitter))
            self.model.appendRow(item)
        self._counter.setText(f"{len(entries)} shots")

        # Keep the current item selected; otherwise load the newest.
        if self._current_path in entries:
            self._select_silently(self._current_path)
        elif entries:
            self.select_path(entries[0])
        else:
            self._current_path = None
            self.stack.setCurrentWidget(self.editor)
            self.editor.load(None, _placeholder_image())

    @Slot(str, QImage)
    def _thumb_ready(self, path: str, img: QImage) -> None:
        if img.isNull():
            return
        for row in range(self.model.rowCount()):
            it = self.model.item(row)
            if it.data(PATH_ROLE) == path:
                it.setIcon(QIcon(QPixmap.fromImage(img)))
                break

    def refresh_path(self, path: str) -> None:
        self._thumb_pool.start(_ThumbJob(path, self._thumb_emitter))

    def _index_of(self, path: str):
        for row in range(self.model.rowCount()):
            it = self.model.item(row)
            if it.data(PATH_ROLE) == path:
                return self.model.indexFromItem(it)
        return None

    def select_path(self, path: str) -> None:
        """Select in the strip and load into the editor."""
        idx = self._index_of(path)
        if idx is None:
            return
        self.strip.setCurrentIndex(idx)  # triggers _selection_changed
        self.strip.scrollTo(idx)

    def _select_silently(self, path: str) -> None:
        idx = self._index_of(path)
        if idx is None:
            return
        sm = self.strip.selectionModel()
        sm.blockSignals(True)
        sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect)
        sm.blockSignals(False)
        self.strip.scrollTo(idx)

    def _selection_changed(self, *_args) -> None:
        paths = self._selected_paths()
        if len(paths) != 1:
            return  # multi-select is for dragging/deleting, keep editor put
        path = paths[0]
        if path == self._current_path:
            return
        if not self.editor.maybe_save():
            self._select_silently(self._current_path or "")
            return
        if is_video(path):
            if self.video_pane is not None:
                self.stack.setCurrentWidget(self.video_pane)
                self.video_pane.load(path)
            else:
                self.stack.setCurrentWidget(self.editor)
                self.editor.load_preview(path, _video_placeholder(path))
        else:
            if self.video_pane is not None:
                self.video_pane.stop()
            self.stack.setCurrentWidget(self.editor)
            if not self.editor.load(path):
                self.editor.load(None, _placeholder_image())
        self._current_path = path
        self._update_title()

    def _gif_ready(self, path: str) -> None:
        self.rescan()
        self.select_path(path)

    # -- toolbar ----------------------------------------------------------------

    def _tb_act(self, text: str, icon: str, slot, shortcut=None) -> QAction:
        a = QAction(QIcon.fromTheme(icon), text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        return a

    def _build_toolbar(self) -> None:
        tb = QToolBar("Capture", self)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(22, 22))
        self.addToolBar(tb)

        tb.addAction(self._tb_act("Capture region", "transform-crop",
                                  self.capture.capture_region, "Ctrl+N"))
        tb.addAction(self._tb_act("Full screen", "computer",
                                  self.capture.capture_fullscreen))
        tb.addSeparator()
        tb.addAction(self._tb_act("Open in window", "window-new",
                                  self._open_in_window))
        tb.addAction(self._tb_act("Trash", "edit-delete",
                                  self._delete_selected, "Ctrl+Del"))
        tb.addSeparator()
        tb.addAction(self._tb_act("Folder", "folder-open", self._open_folder))

        self.pin_action = self._tb_act("Pin", "window-pin", self._toggle_pin)
        self.pin_action.setCheckable(True)
        self.pin_action.setChecked(self.settings.pin_on_top)
        tb.addAction(self.pin_action)

        tb.addAction(self._tb_act("Settings", "configure", self._open_settings))

    # -- actions -----------------------------------------------------------------

    def _selected_paths(self) -> list[str]:
        return [i.data(PATH_ROLE)
                for i in self.strip.selectionModel().selectedIndexes()]

    def open_editor(self, path: str) -> None:
        """Standalone editor window (used by `grabbit -e` and Open in window)."""
        win = EditorWindow(path, settings=self.settings)
        win.saved.connect(self.refresh_path)
        win.destroyed.connect(lambda *_: self._windows.remove(win)
                              if win in self._windows else None)
        win.setAttribute(Qt.WA_DeleteOnClose)
        self._windows.append(win)
        win.show()

    def _open_in_window(self) -> None:
        for path in self._selected_paths()[:4]:
            if is_video(path):
                self._play_video(path)
            else:
                self.open_editor(path)

    def _double_clicked(self, index) -> None:
        path = index.data(PATH_ROLE)
        if not path or not is_video(path):
            return
        if self.video_pane is not None and self.video_pane.path == path:
            self.video_pane.toggle()
        else:
            self._play_video(path)

    @staticmethod
    def _play_video(path: str) -> None:
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _delete_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        names = "\n".join(os.path.basename(p) for p in paths[:8])
        more = f"\n… and {len(paths) - 8} more" if len(paths) > 8 else ""
        if QMessageBox.question(
            self, "grabbit", f"Move to trash?\n\n{names}{more}"
        ) != QMessageBox.Yes:
            return
        from PySide6.QtCore import QFile
        for p in paths:
            QFile.moveToTrash(p)
        if self.editor.path in paths:
            self.editor.undo_stack.clear()  # don't prompt to save a trashed file
            self.editor.path = None
        if self.video_pane is not None and self.video_pane.path in paths:
            self.video_pane.stop()
        if self._current_path in paths:
            self._current_path = None
        self.rescan()

    def _rename_selected(self) -> None:
        paths = self._selected_paths()
        if len(paths) != 1:
            return
        old = paths[0]
        base = os.path.basename(old)
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=base)
        if not ok or not name or name == base:
            return
        new = os.path.join(os.path.dirname(old), name)
        try:
            os.rename(old, new)
            if self.editor.path == old:
                self.editor.path = new
        except OSError as e:
            QMessageBox.warning(self, "grabbit", str(e))
        self.rescan()

    def _copy_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        if is_video(paths[0]):
            QGuiApplication.clipboard().setText(paths[0])
            self.editor.statusBar().showMessage("Copied video path", 2500)
            return
        img = QImage(paths[0])
        if not img.isNull():
            QGuiApplication.clipboard().setImage(img)
            self.editor.statusBar().showMessage("Copied to clipboard", 2500)

    def _open_folder(self) -> None:
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.library_dir))

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == SettingsDialog.Accepted:
            if dlg.apply():
                self.set_library(self.settings.library_dir)

    def _toggle_pin(self) -> None:
        self.settings.pin_on_top = self.pin_action.isChecked()
        self._apply_pin()
        self.show()  # re-applying window flags requires re-show

    def _apply_pin(self) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.settings.pin_on_top)

    def _context_menu(self, pos) -> None:
        index = self.strip.indexAt(pos)
        menu = QMenu(self)
        if index.isValid():
            menu.addAction(QIcon.fromTheme("window-new"), "Open in window",
                           self._open_in_window)
            menu.addAction(QIcon.fromTheme("edit-copy"), "Copy image",
                           self._copy_selected)
            menu.addAction(QIcon.fromTheme("edit-copy-path"), "Copy path",
                           lambda: QGuiApplication.clipboard().setText(
                               "\n".join(self._selected_paths())))
            menu.addAction(QIcon.fromTheme("edit-rename"), "Rename…",
                           self._rename_selected)
            menu.addSeparator()
            menu.addAction(QIcon.fromTheme("edit-delete"), "Move to trash",
                           self._delete_selected)
        else:
            menu.addAction(QIcon.fromTheme("view-refresh"), "Refresh", self.rescan)
        menu.exec(self.strip.mapToGlobal(pos))

    # -- window ---------------------------------------------------------------------

    def _update_title(self) -> None:
        name = (os.path.basename(self._current_path)
                if self._current_path else "gallery")
        dirty = "" if self.editor.undo_stack.isClean() else " •"
        self.setWindowTitle(f"{name}{dirty} — grabbit")

    def really_quit(self) -> None:
        self._really_quit = True
        self.close()

    def closeEvent(self, ev):  # noqa: N802
        if self._really_quit:
            if not self.editor.maybe_save():
                self._really_quit = False
                ev.ignore()
                return
            ev.accept()
            self.quit_requested.emit()
            return
        # Hide to tray instead of quitting.
        ev.ignore()
        self.hide()

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(ev)


def with_signals_blocked(obj, fn):
    obj.blockSignals(True)
    try:
        return fn()
    finally:
        obj.blockSignals(False)
