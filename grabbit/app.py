"""Application coordinator: tray icon, single instance, capture wiring."""

from __future__ import annotations

import json
import os
import shutil

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QImage, QPainter, QPixmap, QColor, QBrush, QPen
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .capture import CaptureManager, unique_path, timestamp_name
from .editor import EditorWindow
from .gallery import GalleryWindow
from .hotkey import HotkeyManager
from .settings import Settings


def server_name() -> str:
    return f"grabbit-{os.getuid()}"


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
    icon = QIcon.fromTheme("grabbit")
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
        self.capture = CaptureManager(self.settings, self)
        self.capture.captured.connect(self._on_captured)
        self.capture.failed.connect(self._on_capture_failed)

        self.gallery = GalleryWindow(self.settings, self.capture)
        self.gallery.quit_requested.connect(qapp.quit)
        self._editors: list[EditorWindow] = []
        self._gallery_was_visible = False

        self.icon = make_app_icon()
        qapp.setWindowIcon(self.icon)
        self.tray = self._build_tray()

        self.hotkey = HotkeyManager(self)
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
        menu.addSeparator()
        a = QAction("Record region", menu)
        a.triggered.connect(lambda: self._start_recording("region"))
        menu.addAction(a)
        a = QAction("Record full screen", menu)
        a.triggered.connect(lambda: self._start_recording("screen"))
        menu.addAction(a)
        self.bubble_action = QAction("Camera bubble", menu)
        self.bubble_action.setCheckable(True)
        self.bubble_action.toggled.connect(self.toggle_bubble)
        menu.addAction(self.bubble_action)
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
        tray.setToolTip("grabbit — screenshots")
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
        # Hide our own windows so they're not in the shot.
        self._gallery_was_visible = self.gallery.isVisible()
        if self._gallery_was_visible:
            self.gallery.hide()
        delay = 300 if self._gallery_was_visible else 0
        fn = {
            "region": self.capture.capture_region,
            "fullscreen": self.capture.capture_fullscreen,
            "window": self.capture.capture_window,
        }[mode]
        QTimer.singleShot(delay, fn)

    def _on_captured(self, path: str) -> None:
        if self.settings.copy_after_capture:
            img = QImage(path)
            if not img.isNull():
                QGuiApplication.clipboard().setImage(img)
        self.gallery.rescan()
        self.gallery.select_path(path)
        if self.settings.show_gallery_after_capture or self._gallery_was_visible:
            self.show_gallery()
        note = " · copied to clipboard" if self.settings.copy_after_capture else ""
        self.tray.showMessage("grabbit", os.path.basename(path) + note,
                              self.icon, 2500)

    def _on_capture_failed(self, message: str) -> None:
        if self._gallery_was_visible:
            self.show_gallery()
        self.tray.showMessage("grabbit — capture failed", message, self.icon, 4000)

    def show_gallery(self) -> None:
        self.gallery.show()
        self.gallery.raise_()
        self.gallery.activateWindow()

    # -- recording / camera bubble -----------------------------------------

    def _start_recording(self, mode: str) -> None:
        fn = (self.capture.record_region if mode == "region"
              else self.capture.record_screen)
        if fn():
            self.tray.showMessage(
                "grabbit — recording",
                "Recording starts after you confirm. Stop it with the "
                "pulsing Spectacle tray icon; the file appears in the "
                "gallery when done.", self.icon, 5000)

    def toggle_bubble(self, on: bool) -> None:
        if on:
            from .bubble import CameraBubble
            self.bubble = CameraBubble(self.settings)
            self.bubble.setAttribute(Qt.WA_DeleteOnClose, True)
            self.bubble.destroyed.connect(
                lambda *_: self.bubble_action.setChecked(False))
            self.bubble.show()
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
