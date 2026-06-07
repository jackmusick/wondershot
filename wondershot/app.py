"""Application coordinator: tray icon, single instance, capture wiring."""

from __future__ import annotations

import json
import os
import shutil

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QImage, QPainter, QPixmap, QColor, QBrush, QPen
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import icons
from .capture import create_capture_manager, unique_path, timestamp_name, window_capture_available
from .editor import EditorWindow
from .gallery import GalleryWindow
from .hotkey import create_hotkey_backend
from .scrollsource import scroll_capture_available
from .settings import Settings


def server_name() -> str:
    # Windows has no os.getuid; the username scopes the socket the same way.
    uid = os.getuid() if hasattr(os, "getuid") else os.environ.get(
        "USERNAME", "user")
    return f"wondershot-{uid}"


def send_to_running(command: dict) -> bool:
    """Deliver a command to a running instance. True if one was reachable."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(500):
        return False
    sock.write(json.dumps(command).encode() + b"\n")
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def make_app_icon() -> QIcon:
    """Rabbit silhouette, drawn so we don't need an icon theme installed."""
    icon = icons.icon("wondershot")
    if not icon.isNull():
        return icon
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor("#26a69a")))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setBrush(QBrush(QColor("#f5f5f5")))
    # ears
    p.drawEllipse(16, 6, 11, 28)
    p.drawEllipse(37, 6, 11, 28)
    # head
    p.drawEllipse(12, 26, 40, 32)
    # camera lens "eye"
    p.setBrush(QBrush(QColor("#263238")))
    p.drawEllipse(26, 36, 12, 12)
    p.setBrush(QBrush(QColor("#90caf9")))
    p.drawEllipse(29, 39, 4, 4)
    p.end()
    return QIcon(pm)


class GrabbitApp(QObject):
    def __init__(self, qapp, parent=None):
        super().__init__(parent)
        self.qapp = qapp
        self.settings = Settings()
        self.capture = create_capture_manager(self.settings, self)
        self.capture.captured.connect(self._on_captured)
        self.capture.failed.connect(self._on_capture_failed)

        from .record import create_screen_recorder
        self.recorder = create_screen_recorder(self.settings, self)
        self.recorder.started.connect(self._on_recording_started)
        self.recorder.finished.connect(self._on_recording_finished)
        self.recorder.failed.connect(self._on_recording_failed)
        self.recorder.stopping.connect(self._on_recording_stopping)
        self.recorder.paused_changed.connect(self._on_paused_changed)

        self.gallery = GalleryWindow(self.settings, self.capture,
                                     recorder=self.recorder)
        self.gallery.quit_requested.connect(qapp.quit)
        self.gallery.settings_applied.connect(self._on_settings_applied)
        self.gallery.capture_requested.connect(self.trigger_capture)
        self.gallery.record_requested.connect(self._begin_recording)
        self.gallery.record_region_requested.connect(self.record_region)
        self._editors: list[EditorWindow] = []
        self._gallery_was_visible = False

        # "Window" capture works on KDE (KWin scripting) and on Windows
        # (GetForegroundWindow); the attribute keeps its historical name.
        self.kwin_ok = window_capture_available()
        self.gallery.kwin_ok = self.kwin_ok  # gates the CaptureWindow button

        self.scroll_ok = scroll_capture_available()
        self.gallery.scroll_ok = self.scroll_ok  # gates the panel button
        self._scroll = None        # ScrollCaptureController while running
        self._scroll_pill = None   # ScrollStopPill while running

        self.icon = make_app_icon()
        qapp.setWindowIcon(self.icon)
        self.tray = self._build_tray()
        # the editor's status bar is hidden while a video plays — toast too
        self.gallery.editor.share_status.connect(
            lambda m: self.tray.showMessage("Wondershot", m, self.icon, 3000))
        self.recorder.tick.connect(self._on_recording_tick)

        self.hotkey = create_hotkey_backend(self, settings=self.settings)
        self.hotkey.pressed.connect(lambda: self.trigger_capture("region"))
        self.hotkey.register()

        self.server = QLocalServer(self)
        QLocalServer.removeServer(server_name())
        self.server.listen(server_name())
        self.server.newConnection.connect(self._on_connection)

    # -- tray ------------------------------------------------------------

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self.icon, self)
        menu = QMenu()
        a = QAction("Capture region", menu)
        a.triggered.connect(lambda: self.trigger_capture("region"))
        menu.addAction(a)
        a = QAction("Capture full screen", menu)
        a.triggered.connect(lambda: self.trigger_capture("fullscreen"))
        menu.addAction(a)
        if self.kwin_ok:
            a = QAction("Capture window", menu)
            a.setToolTip("Grab the active window (no picker, KDE only)")
            a.triggered.connect(lambda: self.trigger_capture("window-auto"))
            menu.addAction(a)
        if self.scroll_ok:
            a = QAction("Scrolling capture", menu)
            a.setToolTip("Scroll a window; Wondershot stitches one tall "
                         "image — trigger again while scrolling to finish")
            a.triggered.connect(self._scroll_tray_action)
            menu.addAction(a)
        menu.addSeparator()
        self.record_action = QAction("Record screen…", menu)
        self.record_action.triggered.connect(self.toggle_recording)
        menu.addAction(self.record_action)
        self.pause_action = QAction("Pause recording", menu)
        self.pause_action.triggered.connect(self.toggle_pause)
        self.pause_action.setEnabled(False)
        self.pause_action.setVisible(False)
        menu.addAction(self.pause_action)
        self.region_action = QAction("Record region…", menu)
        self.region_action.setToolTip(
            "Pick a rectangle, then record only that area")
        self.region_action.triggered.connect(self.record_region)
        menu.addAction(self.region_action)
        self.bubble_action = QAction(icons.icon("camera-web"),
                                     "Camera", menu)
        self.bubble_action.setCheckable(True)
        self.bubble_action.setToolTip("Show camera (Loom-style bubble)")
        self.bubble_action.toggled.connect(self.toggle_bubble)
        menu.addAction(self.bubble_action)
        # same action also lives in the gallery toolbar
        self.gallery.add_bubble_action(self.bubble_action)
        menu.addSeparator()
        a = QAction("Show gallery", menu)
        a.triggered.connect(self.show_gallery)
        menu.addAction(a)
        menu.addSeparator()
        a = QAction("Quit", menu)
        a.triggered.connect(self.gallery.really_quit)
        menu.addAction(a)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.setToolTip("Wondershot — screenshots")
        tray.show()
        return tray

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:  # left click
            if self.gallery.isVisible():
                self.gallery.hide()
            else:
                self.show_gallery()

    # -- capture flow ---------------------------------------------------------

    def trigger_capture(self, mode: str) -> None:
        # Hide ALL our windows (gallery, capture panel, editors) so none
        # ends up in the shot; the delay gives the compositor time to unmap.
        self._gallery_was_visible = self.gallery.isVisible()
        delay = self.gallery.hide_for_capture()
        fn = {
            "region": self.capture.capture_region,
            "fullscreen": self.capture.capture_fullscreen,
            "window": self.capture.capture_window,
            "window-auto": self.capture.capture_active_window,
            "scroll": self._begin_scroll,
        }[mode]
        QTimer.singleShot(delay, fn)

    def _on_captured(self, path: str) -> None:
        self.gallery.restore_after_capture()
        if self.settings.copy_after_capture:
            img = QImage(path)
            if not img.isNull():
                QGuiApplication.clipboard().setImage(img)
        self.gallery.rescan()
        self.gallery.select_path(path)
        if self.settings.show_gallery_after_capture or self._gallery_was_visible:
            self.show_gallery()
        elif self.settings.quick_bar_enabled:
            # gallery isn't coming forward — offer quick actions instead
            self._show_quick_bar(path)
        note = " · copied to clipboard" if self.settings.copy_after_capture else ""
        self.tray.showMessage("Wondershot", os.path.basename(path) + note,
                              self.icon, 2500)

    def _on_capture_failed(self, message: str) -> None:
        self.gallery.restore_after_capture()
        if self._gallery_was_visible:
            self.show_gallery()
        self.tray.showMessage("Wondershot — capture failed", message, self.icon, 4000)

    def show_gallery(self) -> None:
        self.gallery.show()
        self.gallery.raise_()
        self.gallery.activateWindow()

    # -- post-capture quick-action bar ---------------------------------------

    def _show_quick_bar(self, path: str) -> None:
        from .capture_window import QuickActionBar, ensure_quickbar_rule
        old = getattr(self, "quick_bar", None)
        if old is not None:
            try:
                old.dismiss()
            except RuntimeError:
                pass  # already deleted (WA_DeleteOnClose)
        bar = QuickActionBar(self.settings, path)
        bar.setAttribute(Qt.WA_DeleteOnClose, True)
        bar.edit_requested.connect(self.gallery.open_editor)
        bar.share_requested.connect(self._share_from_bar)
        bar.trash_requested.connect(
            lambda p: self.gallery._trash_paths([p], confirm=False))
        self.quick_bar = bar
        ensure_quickbar_rule()
        # let KWin pick up the freshly-written position rule first
        # (same 300 ms dance as toggle_bubble, app.py line 241)
        QTimer.singleShot(300, bar.show)

    def _share_from_bar(self, path: str) -> None:
        from .share import default_provider
        provider = default_provider(self.settings)
        if not provider:
            self.tray.showMessage(
                "Wondershot", "Set up sharing in Settings → Sharing",
                self.icon, 3000)
            return
        # reuses the editor's async upload + clipboard flow; outcome toasts
        # arrive via the existing share_status → tray connection (line 90)
        self.gallery.editor.share_path(path, provider)

    # -- scroll capture --------------------------------------------------------

    def _scroll_tray_action(self) -> None:
        # The tray entry is the SECOND finish path (spec Addendum 2
        # Track 4b: "Ctrl+click tray or click Stop to finish"): while a
        # scroll session runs, triggering it again finishes the capture.
        # Deliberately NOT routed through trigger_capture, which would
        # clobber _gallery_was_visible mid-session.
        if self._scroll is not None:
            self._finish_scroll()
        else:
            self.trigger_capture("scroll")

    def _begin_scroll(self) -> None:
        if self._scroll is not None:
            return  # one scroll session at a time
        from .scrollsource import ScrollCaptureController
        ctl = ScrollCaptureController(self.settings, parent=self)
        ctl.started.connect(self._on_scroll_started)
        ctl.captured.connect(self._on_scroll_captured)
        ctl.failed.connect(self._on_scroll_failed)
        self._scroll = ctl
        ctl.start()

    def _on_scroll_started(self) -> None:
        from .capture_window import ScrollStopPill
        pill = ScrollStopPill()
        pill.setAttribute(Qt.WA_DeleteOnClose, True)
        pill.stop_requested.connect(self._finish_scroll)
        self._scroll_pill = pill
        pill.show()

    def _finish_scroll(self) -> None:
        self._close_scroll_pill()
        if self._scroll is not None:
            self._scroll.stop()

    def _close_scroll_pill(self) -> None:
        pill, self._scroll_pill = self._scroll_pill, None
        if pill is not None:
            try:
                pill._fired = True  # disarm: app-initiated close must not
                pill.close()        # re-enter the finish path via closeEvent
            except RuntimeError:
                pass  # already deleted (WA_DeleteOnClose)

    def _release_scroll(self) -> None:
        self._close_scroll_pill()
        ctl, self._scroll = self._scroll, None
        if ctl is not None:
            ctl.deleteLater()

    def _on_scroll_captured(self, path: str) -> None:
        self._release_scroll()
        self._on_captured(path)  # the normal captured path: clipboard,
        # rescan/select, preview-or-quick-bar, tray toast — all inherited.

    def _on_scroll_failed(self, message: str) -> None:
        self._release_scroll()
        self._on_capture_failed(message)

    # -- recording / camera bubble -----------------------------------------

    def toggle_recording(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()  # recorder.stopping resets BOTH controls
        else:
            self._begin_recording()

    def _begin_recording(self) -> None:
        cd = getattr(self, "_countdown", None)
        if cd is not None:
            try:
                cd.cancel()  # pressing Record again during the countdown
            except RuntimeError:
                pass  # already deleted (WA_DeleteOnClose)
            self._countdown = None
            return
        secs = int(getattr(self.settings, "record_countdown", 0) or 0)
        if secs <= 0:
            self.recorder.start()
            return
        from .countdown import CountdownOverlay
        cd = CountdownOverlay(secs)
        cd.finished.connect(self._countdown_finished)
        cd.cancelled.connect(self._countdown_cancelled)
        self._countdown = cd
        cd.show()

    # -- region recording (D2) -------------------------------------------

    def record_region(self) -> None:
        """Pick a rectangle on a fullscreen still, then record only that
        area (cropped in-pipeline via videocrop). The portal still streams
        the whole monitor; we crop downstream."""
        if self.recorder.recording or getattr(self.recorder, "_busy", False):
            return
        img, _virt = self._region_grab()
        if img is None:
            return
        ov = self._region_overlay(img)
        ov.selected.connect(lambda rect: self._region_record_selected(img, rect))
        ov.cancelled.connect(self._region_record_cancelled)
        self._region_ov = ov
        if hasattr(ov, "show_on_desktop"):
            ov.show_on_desktop()

    def _region_grab(self):
        """Grab the fullscreen still. Seam for tests. Live-desktop only."""
        try:
            from .wincapture import grab_fullscreen
            return grab_fullscreen()
        except Exception as e:
            self.tray.showMessage("Wondershot — region recording",
                                  f"could not grab the screen: {e}",
                                  self.icon, 4000)
            return None, None

    def _region_overlay(self, img):
        """Build the region picker. Seam for tests."""
        from .wincapture import RegionOverlay
        return RegionOverlay(img)

    def _region_record_selected(self, img, rect) -> None:
        self._region_ov = None
        if rect.isEmpty():
            return  # degenerate mapping; treat as cancel
        from .record import crop_props
        self.recorder._crop = crop_props(
            (rect.x(), rect.y(), rect.width(), rect.height()),
            img.width(), img.height())
        self._begin_recording()

    def _region_record_cancelled(self) -> None:
        self._region_ov = None

    def _countdown_finished(self) -> None:
        self._countdown = None
        self.recorder.start()

    def _countdown_cancelled(self) -> None:
        self._countdown = None

    def toggle_pause(self) -> None:
        if self.recorder.paused:
            self.recorder.resume()
        else:
            self.recorder.pause()

    def _on_paused_changed(self, paused: bool) -> None:
        # single source of truth: relabel BOTH controls (same discipline
        # as 'stopping')
        self.pause_action.setText(
            "Resume recording" if paused else "Pause recording")
        self.gallery.set_paused(paused)

    def _set_pause_enabled(self, on: bool) -> None:
        on = on and self.recorder.supports_pause  # Windows/ffmpeg: hide
        self.pause_action.setEnabled(on)
        self.pause_action.setVisible(on)
        if not on:
            self.pause_action.setText("Pause recording")
        self.gallery.set_pause_enabled(on)

    def _on_recording_stopping(self) -> None:
        # The gallery toolbar resets itself via its own stopping
        # connection (gallery.py __init__); only the tray is ours.
        self.record_action.setText("Stopping…")
        self.record_action.setEnabled(False)
        self._set_pause_enabled(False)

    def _on_recording_tick(self, t: str) -> None:
        self.record_action.setText(
            f"Stop recording ({t})" if t else "Stop recording")
        self.tray.setToolTip(
            f"Wondershot — recording {t}" if t
            else "Wondershot — screenshots")

    def _on_recording_started(self) -> None:
        self.record_action.setText("Stop recording")
        self._set_pause_enabled(True)
        self.gallery.set_recording(True)
        mic = "with mic" if self.settings.mic_enabled else "no mic"
        self.tray.showMessage("Wondershot — recording",
                              f"Recording ({mic}). Stop from the tray or "
                              "the Record button.", self.icon, 3500)

    def _on_recording_finished(self, path: str) -> None:
        self.record_action.setText("Record screen…")
        self.record_action.setEnabled(True)
        self._set_pause_enabled(False)
        self.gallery.set_recording(False)
        self.tray.setToolTip("Wondershot — screenshots")
        self.gallery.rescan()
        self.gallery.select_path(path)
        self.show_gallery()
        self.tray.showMessage("Wondershot", f"Recording saved: "
                              f"{os.path.basename(path)}", self.icon, 3000)

    def _on_recording_failed(self, message: str) -> None:
        self.record_action.setText("Record screen…")
        self.record_action.setEnabled(True)
        self._set_pause_enabled(False)
        self.gallery.set_recording(False)
        self.tray.setToolTip("Wondershot — screenshots")
        self.tray.showMessage("Wondershot — recording failed", message,
                              self.icon, 5000)

    def _on_settings_applied(self) -> None:
        # Re-register the global hotkey if the chord changed (Windows;
        # no-op elsewhere — Linux registration stays manual).
        rebind = getattr(self.hotkey, "rebind", None)
        if rebind is not None:
            rebind()
        # A live bubble should switch to the newly chosen camera without
        # needing an off/on toggle.
        bubble = getattr(self, "bubble", None)
        if bubble is not None:
            try:
                bubble.start_camera()
            except RuntimeError:
                pass  # bubble closed itself (WA_DeleteOnClose)

    def toggle_bubble(self, on: bool) -> None:
        if on:
            from .bubble import CameraBubble
            self.bubble = CameraBubble(self.settings)
            self.bubble.setAttribute(Qt.WA_DeleteOnClose, True)
            self.bubble.destroyed.connect(
                lambda *_: self.bubble_action.setChecked(False))
            # let KWin pick up the freshly-written position rule first
            QTimer.singleShot(300, self.bubble.show)
        elif getattr(self, "bubble", None) is not None:
            self.bubble.close()
            self.bubble = None

    # -- commands from second instances --------------------------------------

    def _on_connection(self) -> None:
        sock = self.server.nextPendingConnection()
        sock.readyRead.connect(lambda: self._read_command(sock))

    def _read_command(self, sock) -> None:
        data = bytes(sock.readAll()).decode(errors="replace").strip()
        sock.disconnectFromServer()
        for line in data.splitlines():
            try:
                self.handle_command(json.loads(line))
            except json.JSONDecodeError:
                pass

    def handle_command(self, cmd: dict) -> None:
        action = cmd.get("action", "show")
        if action == "capture":
            self.trigger_capture("region")
        elif action == "fullscreen":
            self.trigger_capture("fullscreen")
        elif action == "show":
            self.show_gallery()
        elif action == "edit":
            path = cmd.get("path", "")
            if os.path.exists(path):
                self.gallery.open_editor(os.path.abspath(path))
        elif action == "import":
            for src in cmd.get("paths", []):
                if os.path.exists(src):
                    dest = unique_path(self.settings.library_dir,
                                       os.path.basename(src))
                    shutil.copy2(src, dest)
            self.gallery.rescan()
        elif action == "quit":
            self.gallery.really_quit()
        elif action == "oauth":
            self.show_gallery()  # bring the Settings dialog forward
            self.gallery.oauth_callback.emit(cmd.get("url", ""))
