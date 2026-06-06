"""Loom-style camera bubble: frameless circular always-on-top window.

The bubble paints camera frames itself (QVideoSink → QPainter with an
ellipse clip), so it needs no native video surface and composites cleanly
on Wayland. Because it's an ordinary on-screen window, any screen
recording captures it for free — no video mixing involved.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtMultimedia import (
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoSink,
)
from PySide6.QtWidgets import QMenu, QWidget

SIZES = [160, 220, 300, 400]

RULE_ID = "grabbitbubble"
WINDOW_TITLE = "grabbit camera"


def ensure_position_rule() -> None:
    """KWin window rule placing the bubble bottom-right on open.

    Wayland clients cannot position their own top-level windows; on KDE a
    window rule (policy 3 = 'apply initially') does it for us while still
    letting the user drag the bubble afterwards.
    """
    import shutil
    import subprocess

    if not shutil.which("kwriteconfig6"):
        return
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    size = 220
    # Wayland gives us no panel struts (availableGeometry == full screen),
    # so leave generous bottom clearance for the taskbar.
    x = avail.right() - size - 24
    y = avail.bottom() - size - 96

    def kwrite(key, value):
        subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc",
                        "--group", RULE_ID, "--key", key, value],
                       capture_output=True, timeout=5)

    try:
        out = subprocess.run(
            ["kreadconfig6", "--file", "kwinrulesrc",
             "--group", "General", "--key", "rules"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        rules = [r for r in out.split(",") if r]
        kwrite("Description", "grabbit camera bubble")
        kwrite("title", WINDOW_TITLE)
        kwrite("titlematch", "1")  # exact
        kwrite("position", f"{x},{y}")
        kwrite("positionrule", "3")  # apply initially
        if RULE_ID not in rules:
            rules.append(RULE_ID)
            subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc",
                            "--group", "General", "--key", "rules",
                            ",".join(rules)],
                           capture_output=True, timeout=5)
        subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/KWin",
                        "org.kde.KWin", "reconfigure"],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def find_camera(preferred_description: str = ""):
    cams = QMediaDevices.videoInputs()
    if not cams:
        return None
    if preferred_description:
        for c in cams:
            if c.description() == preferred_description:
                return c
    return QMediaDevices.defaultVideoInput() or cams[0]


class CameraBubble(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(220, 220)
        ensure_position_rule()

        self._frame = None
        self.session = QMediaCaptureSession(self)
        self.sink = QVideoSink(self)
        self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame_changed)
        self.camera: QCamera | None = None
        self.start_camera()

    # -- camera -----------------------------------------------------------

    def start_camera(self) -> None:
        device = find_camera(self.settings.camera_device)
        if device is None:
            return
        if self.camera is not None:
            self.camera.stop()
            self.camera.deleteLater()
        self.camera = QCamera(device, self)
        self.session.setCamera(self.camera)
        self.camera.start()

    def _frame_changed(self, frame) -> None:
        if frame.isValid():
            self._frame = frame
            self.update()

    # -- painting -------------------------------------------------------------

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        d = min(self.width(), self.height()) - 6
        circle = QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d)
        clip = QPainterPath()
        clip.addEllipse(circle)
        if self._frame is not None:
            img = self._frame.toImage()
            if not img.isNull():
                p.save()
                p.setClipPath(clip)
                # center-crop the frame to fill the circle (portrait look)
                scale = max(circle.width() / img.width(),
                            circle.height() / img.height())
                w, h = img.width() * scale, img.height() * scale
                target = QRectF(circle.center().x() - w / 2,
                                circle.center().y() - h / 2, w, h)
                p.drawImage(target, img)
                p.restore()
        else:
            p.setBrush(QColor(30, 30, 34))
            p.setPen(Qt.NoPen)
            p.drawEllipse(circle)
            p.setPen(QColor(200, 200, 205))
            p.drawText(circle, Qt.AlignCenter, "no\ncamera")
        p.setPen(QPen(QColor(255, 255, 255, 220), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(circle)
        p.end()

    # -- interaction --------------------------------------------------------------

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton and self.windowHandle() is not None:
            self.windowHandle().startSystemMove()

    def wheelEvent(self, ev):  # noqa: N802
        step = 24 if ev.angleDelta().y() > 0 else -24
        d = max(SIZES[0], min(SIZES[-1], self.width() + step))
        self.resize(d, d)

    def contextMenuEvent(self, ev):  # noqa: N802
        menu = QMenu(self)
        for s in SIZES:
            menu.addAction(f"{s}px", lambda s=s: self.resize(s, s))
        menu.addSeparator()
        menu.addAction("Hide bubble", self.close)
        menu.exec(ev.globalPos())

    def closeEvent(self, ev):  # noqa: N802
        if self.camera is not None:
            self.camera.stop()
        ev.accept()
