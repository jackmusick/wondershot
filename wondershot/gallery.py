"""Main window: big markup editor on top, filmstrip carousel underneath.

Snagit-style layout — the carousel shows the screenshot library; selecting a
thumbnail loads it into the editor, and thumbnails drag out as files.
"""

from __future__ import annotations

import os
from datetime import date, datetime

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
    QPen,
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
    QStyledItemDelegate,
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


def _timestamp_labels(mtime: float) -> tuple[str, str]:
    """('Today' or '01/01/2026', '12:03PM') for a file mtime."""
    dt = datetime.fromtimestamp(mtime)
    date_s = "Today" if dt.date() == date.today() else dt.strftime("%m/%d/%Y")
    return date_s, dt.strftime("%I:%M%p").lstrip("0")


class _ThumbDelegate(QStyledItemDelegate):
    """Date/time overlay on each card: 'Today'/date bottom-left, time
    bottom-right. Painted live from mtime (not baked into the thumbnail)
    so 'Today' rolls over correctly in a long-running session.
    Hovered cards get an (x) top-right for one-click trash."""

    CLOSE_SIZE = 20

    def __init__(self, parent, on_delete=None):
        super().__init__(parent)
        self._on_delete = on_delete

    def _close_rect(self, option):
        from PySide6.QtCore import QRect
        r = option.rect
        pad_x = (r.width() - THUMB_SIZE.width()) // 2
        pad_y = (r.height() - THUMB_SIZE.height()) // 2
        s = self.CLOSE_SIZE
        return QRect(r.right() - pad_x - s - 4, r.y() + pad_y + 4, s, s)

    def editorEvent(self, event, model, option, index):  # noqa: N802
        from PySide6.QtCore import QEvent
        if (self._on_delete is not None
                and event.type() in (QEvent.MouseButtonPress,
                                     QEvent.MouseButtonRelease)
                and event.button() == Qt.LeftButton
                and self._close_rect(option).contains(
                    event.position().toPoint())):
            if event.type() == QEvent.MouseButtonRelease:
                path = index.data(PATH_ROLE)
                if path:
                    self._on_delete(path)
            return True  # swallow: no select/drag from the (x)
        return super().editorEvent(event, model, option, index)

    def paint(self, p, option, index):  # noqa: N802
        super().paint(p, option, index)
        path = index.data(PATH_ROLE)
        if not path:
            return
        from PySide6.QtWidgets import QStyle
        if option.state & QStyle.State_MouseOver:
            c = self._close_rect(option)
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawEllipse(c)
            pen = QPen(QColor(235, 235, 235), 2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            m = 6
            p.drawLine(c.left() + m, c.top() + m,
                       c.right() - m, c.bottom() - m)
            p.drawLine(c.right() - m, c.top() + m,
                       c.left() + m, c.bottom() - m)
            p.restore()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        date_s, time_s = _timestamp_labels(mtime)
        r = option.rect
        band_h = 18
        band = r.adjusted(
            (r.width() - THUMB_SIZE.width()) // 2,
            r.height() - (r.height() - THUMB_SIZE.height()) // 2 - band_h,
            -(r.width() - THUMB_SIZE.width()) // 2, 0)
        band.setHeight(band_h)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(band, 4, 4)
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QColor(235, 235, 235, 235))
        text = band.adjusted(6, 0, -6, 0)
        p.drawText(text, Qt.AlignVCenter | Qt.AlignLeft, date_s)
        p.drawText(text, Qt.AlignVCenter | Qt.AlignRight, time_s)
        p.restore()


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def is_animated(path: str) -> bool:
    """Anything routed to the player pane: real videos plus GIFs."""
    ext = os.path.splitext(path)[1].lower()
    return ext in VIDEO_EXTS or ext == ".gif"


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
            elif self.path.lower().endswith(".gif"):
                self._draw_gif_badge(p, canvas)
            p.end()
            img = canvas
        self.emitter.done.emit(self.path, img)

    def _video_frame(self) -> QImage:
        """Poster frame via ffmpegthumbnailer/ffmpeg, else a dark slate."""
        import shutil
        import subprocess
        import tempfile

        from . import ffmpegutil

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            out = tf.name
        try:
            if shutil.which("ffmpegthumbnailer"):
                r = subprocess.run(
                    ["ffmpegthumbnailer", "-i", self.path, "-o", out,
                     "-s", "512", "-q", "8"],
                    capture_output=True, timeout=15)
            elif ffmpegutil.have_ffmpeg():
                r = ffmpegutil.run_ffmpeg(
                    ["-y", "-ss", "1", "-i", self.path,
                     "-frames:v", "1", out],
                    timeout=15)
            else:
                r = None
            img = QImage(out) if r is not None and r.returncode == 0 else QImage()
        except (OSError, subprocess.TimeoutExpired, ffmpegutil.FfmpegMissing):
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

    @staticmethod
    def _draw_gif_badge(p: QPainter, canvas: QImage) -> None:
        from PySide6.QtCore import QRectF
        # Sits above the date/time band the delegate paints along the bottom.
        rect = QRectF(canvas.width() - 42, canvas.height() - 46, 36, 18)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(rect, 5, 5)
        f = p.font()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(rect, Qt.AlignCenter, "GIF")


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


_placeholder_thumb_cache: QIcon | None = None


def _placeholder_thumb() -> QIcon:
    """Neutral skeleton card shown while a thumbnail loads."""
    global _placeholder_thumb_cache
    if _placeholder_thumb_cache is None:
        pm = QPixmap(THUMB_SIZE)
        pm.fill(QColor(31, 31, 35))
        _placeholder_thumb_cache = QIcon(pm)
    return _placeholder_thumb_cache


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
    settings_applied = Signal()
    oauth_callback = Signal(str)  # wondershot://auth?... redirect URL
    capture_requested = Signal(str)  # routed through app.trigger_capture

    def __init__(self, settings, capture, recorder=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.capture = capture
        self.recorder = recorder
        self._windows: list[EditorWindow] = []
        self._thumb_pool = QThreadPool(self)
        self._thumb_emitter = _ThumbSignal()
        self._thumb_emitter.done.connect(self._thumb_ready)
        self._really_quit = False
        self._prompting = False

        # -- embedded editor (QMainWindow works fine as a child widget) ----
        self.editor = EditorWindow(image=_placeholder_image(),
                                   settings=self.settings)
        self.editor.setWindowFlags(Qt.Widget)
        self.editor.share_action.setVisible(False)  # gallery toolbar owns Share
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
            self.video_pane.file_ready.connect(self._file_ready)
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
        self.strip.setUniformItemSizes(True)
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
        self.strip.setItemDelegate(_ThumbDelegate(
            self.strip, on_delete=lambda p: self._trash_paths([p],
                                                              confirm=True)))
        self.strip.setMouseTracking(True)  # hover state for the (x)
        # Ctrl+Z over the strip restores the last delete (the canvas keeps
        # its own Ctrl+Z for annotations).
        self._trash_undo: list[list[tuple[str, str]]] = []
        undo_del = QAction("Undo delete", self.strip)
        undo_del.setShortcut(QKeySequence.Undo)
        undo_del.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        undo_del.triggered.connect(self._undo_delete)
        self.strip.addAction(undo_del)
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
        if self.recorder is not None:
            self.recorder.tick.connect(
                lambda t: self.record_action.setText(f"Stop {t}" if t
                                                     else "Stop"))
        self._counter = QLabel(self)
        self.editor.statusBar().addPermanentWidget(self._counter)

        self._update_title()
        self.resize(1280, 860)
        self._apply_pin()
        self.set_library(self.settings.library_dir)

    # -- library --------------------------------------------------------------

    def _watch_dirs(self) -> list[str]:
        dirs = [self.settings.library_dir]
        for d in self.settings.extra_dirs:
            if d not in dirs and os.path.isdir(d):
                dirs.append(d)
        return dirs

    def set_library(self, directory: str) -> None:
        os.makedirs(directory, exist_ok=True)
        for d in self.watcher.directories():
            self.watcher.removePath(d)
        for d in self._watch_dirs():
            self.watcher.addPath(d)
        self.rescan()

    def _list_library(self) -> list[str]:
        entries = []
        for directory in self._watch_dirs():
            try:
                entries.extend(
                    os.path.join(directory, n)
                    for n in os.listdir(directory)
                    if os.path.splitext(n)[1].lower()
                    in (IMAGE_EXTS | VIDEO_EXTS)
                )
            except OSError:
                continue
        entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return entries

    def rescan(self) -> None:
        # A save-prompt may be open (nested event loop): rebuilding the
        # model under it invalidates indexes mid-flight. Try again later.
        if self._prompting:
            self._rescan_timer.start()
            return
        entries = self._list_library()

        # Copy icons out before the model clear deletes the C++ items.
        existing: dict[str, QIcon] = {}
        for row in range(self.model.rowCount()):
            it = self.model.item(row)
            existing[it.data(PATH_ROLE)] = it.icon()

        # Rebuild with updates frozen — incremental relayout of the icon
        # view paints overlapping "half cards" otherwise.
        self.strip.setUpdatesEnabled(False)
        try:
            with_signals_blocked(self.strip.selectionModel(), self.model.clear)
            for path in entries:
                old_icon = existing.pop(path, None)
                item = QStandardItem()
                item.setData(path, PATH_ROLE)
                item.setDragEnabled(True)
                item.setToolTip(os.path.basename(path))
                # Fixed size + placeholder icon: thumbnails load async, and
                # the view must never measure a card while it's icon-less
                # (uniformItemSizes caches the first measurement for all).
                item.setSizeHint(QSize(THUMB_SIZE.width() + 8,
                                       THUMB_SIZE.height() + 8))
                if old_icon is not None and not old_icon.isNull():
                    item.setIcon(old_icon)
                else:
                    item.setIcon(_placeholder_thumb())
                    self._thumb_pool.start(_ThumbJob(path, self._thumb_emitter))
                self.model.appendRow(item)
        finally:
            self.strip.setUpdatesEnabled(True)
            self.strip.doItemsLayout()
            self.strip.viewport().update()
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
                self.strip.viewport().update()
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
        # Scroll BEFORE selecting: setCurrentIndex can open a save-prompt
        # whose nested event loop lets a watcher rescan clear the model,
        # and scrollTo on the stale index then segfaults.
        self.strip.scrollTo(idx)
        self.strip.setCurrentIndex(idx)  # triggers _selection_changed

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
        self._prompting = True
        try:
            keep_going = self.editor.maybe_save()
        finally:
            self._prompting = False
        if not keep_going:
            self._select_silently(self._current_path or "")
            return
        if is_animated(path):
            if self.video_pane is not None:
                self.stack.setCurrentWidget(self.video_pane)
                self.video_pane.load(path)
            elif is_video(path):
                self.stack.setCurrentWidget(self.editor)
                self.editor.load_preview(path, _video_placeholder(path))
            else:  # gif without QtMultimedia: edit first frame
                self.stack.setCurrentWidget(self.editor)
                self.editor.load(path)
        else:
            if self.video_pane is not None:
                self.video_pane.stop()
            self.stack.setCurrentWidget(self.editor)
            if not self.editor.load(path):
                self.editor.load(None, _placeholder_image())
        self._current_path = path
        self._update_title()

    def _file_ready(self, path: str) -> None:
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

        tb.addAction(self._tb_act("Capture", "camera-photo",
                                  self._open_capture_window, "Ctrl+N"))
        self.record_action = self._tb_act("Record", "media-record",
                                          self._toggle_record, "Ctrl+R")
        tb.addAction(self.record_action)
        self._bubble_anchor = tb.addSeparator()
        self.main_toolbar = tb
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

        from PySide6.QtWidgets import QMenu as _QMenu, QSizePolicy, QToolButton
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.share_btn = QToolButton(self)
        self.share_btn.setText("Share")
        self.share_btn.setIcon(QIcon.fromTheme("document-send"))
        self.share_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.share_btn.clicked.connect(
            lambda: self._share_default_path(self._share_target()))
        self._share_menu = _QMenu(self.share_btn)
        tb.addWidget(self.share_btn)
        self.editor.share_status.connect(self._on_share_status)
        self._update_share_toolbar()

    def _on_share_status(self, msg: str) -> None:
        """Make the toolbar Share button itself the confirmation."""
        if msg == "Uploading…":
            self.share_btn.setText("Uploading…")
            return
        if msg.startswith("Copied"):
            self.share_btn.setText("✓ Copied link")
        elif msg.startswith(("Share failed", "No sharing")):
            self.share_btn.setText("Share")
            QMessageBox.warning(self, "Wondershot", msg)
            return
        else:
            self.share_btn.setText("Share")
            return
        QTimer.singleShot(2500, lambda: self.share_btn.setText("Share"))

    def _share_target(self) -> str:
        paths = self._selected_paths()
        return paths[0] if paths else (self._current_path or "")

    def _update_share_toolbar(self) -> None:
        from PySide6.QtWidgets import QToolButton
        from .share import configured_providers
        providers = configured_providers(self.settings)
        self.share_btn.setToolTip(
            "Copy a share link for the selected item" if providers
            else "Set up sharing in Settings → Sharing")
        self._share_menu.clear()
        if len(providers) > 1:
            labels = {"s3": "Share via S3", "azure": "Share via Azure",
                      "onedrive": "Share via OneDrive"}
            for p in providers:
                self._share_menu.addAction(
                    labels[p],
                    lambda p=p: self.editor.share_path(
                        self._share_target(), p))
            self.share_btn.setMenu(self._share_menu)
            self.share_btn.setPopupMode(QToolButton.MenuButtonPopup)
        else:
            self.share_btn.setMenu(None)

    # -- actions -----------------------------------------------------------------

    def _open_capture_window(self) -> None:
        if getattr(self, "_capture_window", None) is None:
            from .capture_window import CaptureWindow
            self._capture_window = CaptureWindow(
                self.settings, window_mode=getattr(self, "kwin_ok", False))
            self._capture_window.capture_requested.connect(
                self._capture_mode)
        self._capture_window.show()
        self._capture_window.raise_()
        self._capture_window.activateWindow()

    def _capture_mode(self, mode: str) -> None:
        if mode == "record":
            if getattr(self, "_capture_window", None) is not None:
                self._capture_window.hide()  # not in the recording
            self._toggle_record()
        else:
            # Route through app.trigger_capture so OUR windows leave the
            # screen (with compositor grace time) before the shot fires.
            self.capture_requested.emit(mode)

    def hide_for_capture(self) -> int:
        """Hide every Wondershot window so none ends up in the shot.

        Returns the ms delay the caller must wait before capturing —
        Wayland needs a beat for the compositor to actually unmap us.
        """
        wins = [self, getattr(self, "_capture_window", None), *self._windows]
        self._capture_hidden = [w for w in wins if w is not None and w.isVisible()]
        for w in self._capture_hidden:
            w.hide()
        return 300 if self._capture_hidden else 0

    def restore_after_capture(self) -> None:
        """Re-show what hide_for_capture() hid — except the gallery itself,
        whose return is the app coordinator's decision (preview setting /
        quick bar)."""
        for w in getattr(self, "_capture_hidden", []):
            if w is not self:
                w.show()
        self._capture_hidden = []

    def _selected_paths(self) -> list[str]:
        return [i.data(PATH_ROLE)
                for i in self.strip.selectionModel().selectedIndexes()]

    def open_editor(self, path: str) -> None:
        """Standalone editor window (used by `wondershot -e` and Open in window)."""
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
        if not path or not is_animated(path):
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
        self._trash_paths(self._selected_paths(), confirm=True)

    @staticmethod
    def _staging_dir() -> str:
        from PySide6.QtCore import QStandardPaths
        d = os.path.join(QStandardPaths.writableLocation(
            QStandardPaths.GenericDataLocation), "wondershot", "trash")
        os.makedirs(d, exist_ok=True)
        return d

    def _trash_paths(self, paths: list[str], confirm: bool) -> None:
        """Stage deletes so Ctrl+Z can restore them; staged files reach
        the real system trash on quit / when the undo stack is deep."""
        if not paths:
            return
        if confirm:
            names = "\n".join(os.path.basename(p) for p in paths[:8])
            more = f"\n… and {len(paths) - 8} more" if len(paths) > 8 else ""
            if QMessageBox.question(
                self, "Wondershot", f"Move to trash?\n\n{names}{more}"
            ) != QMessageBox.Yes:
                return
        import shutil
        import time
        batch = []
        stage = self._staging_dir()
        for p in paths:
            staged = os.path.join(
                stage, f"{time.monotonic_ns()}-{os.path.basename(p)}")
            try:
                shutil.move(p, staged)
            except OSError:
                continue
            batch.append((staged, p))
        if batch:
            self._trash_undo.append(batch)
            while len(self._trash_undo) > 20:  # keep undo shallow-ish
                self._flush_batch(self._trash_undo.pop(0))
            n = len(batch)
            what = (os.path.basename(batch[0][1]) if n == 1
                    else f"{n} files")
            self.editor.statusBar().showMessage(
                f"Moved {what} to trash — Ctrl+Z to undo", 6000)
        if self.editor.path in paths:
            self.editor.undo_stack.clear()  # don't prompt to save a trashed file
            self.editor.path = None
        if self.video_pane is not None and self.video_pane.path in paths:
            self.video_pane.stop()
        if self._current_path in paths:
            self._current_path = None
        self.rescan()

    def _undo_delete(self) -> None:
        import shutil
        if not self._trash_undo:
            return
        restored = []
        for staged, original in self._trash_undo.pop():
            if os.path.exists(staged):
                try:
                    shutil.move(staged, original)
                    restored.append(original)
                except OSError:
                    pass
        self.rescan()
        if restored:
            self.select_path(restored[0])
            self.editor.statusBar().showMessage(
                f"Restored {os.path.basename(restored[0])}", 4000)

    @staticmethod
    def _flush_batch(batch: list[tuple[str, str]]) -> None:
        from PySide6.QtCore import QFile
        for staged, _original in batch:
            if os.path.exists(staged):
                QFile.moveToTrash(staged)

    def flush_trash(self) -> None:
        while self._trash_undo:
            self._flush_batch(self._trash_undo.pop())

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
            QMessageBox.warning(self, "Wondershot", str(e))
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

    def add_bubble_action(self, action) -> None:
        self.main_toolbar.insertAction(self._bubble_anchor, action)

    def _toggle_record(self) -> None:
        if self.recorder is None:
            self.capture.record_region()  # spectacle fallback
            return
        if self.recorder.recording:
            self.set_stopping()
            self.recorder.stop()
        else:
            self.recorder.start()

    def set_recording(self, on: bool) -> None:
        self.record_action.setEnabled(True)
        self.record_action.setText("Stop" if on else "Record")
        self.record_action.setIcon(QIcon.fromTheme(
            "media-playback-stop" if on else "media-record"))

    def set_stopping(self) -> None:
        # finalizing: neither button should accept clicks until done
        self.record_action.setText("Stopping…")
        self.record_action.setEnabled(False)

    def _share_selected(self) -> None:
        """Upload via the default provider; works for videos too."""
        paths = self._selected_paths()
        if paths:
            self._share_default_path(paths[0])

    def _share_default_path(self, path: str) -> None:
        from .share import configured_providers
        providers = configured_providers(self.settings)
        if not providers:
            self.editor.share_status.emit(
                "No sharing configured — Settings → Sharing")
            return
        if not path:
            return
        default = self.settings.share_provider
        provider = default if default in providers else providers[0]
        self.editor.share_path(path, provider)

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == SettingsDialog.Accepted:
            if dlg.apply():
                self.set_library(self.settings.library_dir)
            self._update_share_toolbar()
            self.settings_applied.emit()

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
            menu.addAction(QIcon.fromTheme("document-send"), "Share…",
                           self._share_selected)
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
        self.setWindowTitle(f"{name}{dirty} — Wondershot")

    def really_quit(self) -> None:
        self.flush_trash()
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
            # Esc cancels things; it never hides the window.
            if (self.video_pane is not None
                    and self.video_pane.blur_btn.isChecked()):
                self.video_pane.blur_btn.setChecked(False)
            elif (self.video_pane is not None
                    and self.video_pane.trim_btn.isChecked()):
                self.video_pane.trim_btn.setChecked(False)
            else:
                self.editor.scene.clearSelection()
        else:
            super().keyPressEvent(ev)

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        # The strip is populated before the window has a real size; force a
        # fresh layout or the cards can come up blank until the next rescan.
        QTimer.singleShot(0, self._relayout_strip)

    def _relayout_strip(self) -> None:
        self.strip.doItemsLayout()
        self.strip.viewport().update()
        if self._current_path:
            self._select_silently(self._current_path)


def with_signals_blocked(obj, fn):
    obj.blockSignals(True)
    try:
        return fn()
    finally:
        obj.blockSignals(False)
