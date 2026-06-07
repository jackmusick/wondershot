"""Snagit-style capture panel: one big Capture button + capture defaults.

Compact always-on-top window. The toggles write straight to settings
(they ARE the defaults), the big button fires a region capture, with
full-screen and record as smaller secondary actions.
"""

from __future__ import annotations

import os
import shutil
import sys

from PySide6.QtCore import Qt, Signal

from . import icons
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CaptureWindow(QWidget):
    capture_requested = Signal(str)  # "region" | "fullscreen" | "window-auto" | "scroll" | "record"

    def __init__(self, settings, parent=None, window_mode: bool = False,
                 scroll_mode: bool = False):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Capture")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        # Snagit-compact (Jack, 2026-06-07): a small panel, not a dialog.
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(16)

        # -- defaults column ------------------------------------------------
        left = QVBoxLayout()
        left.setSpacing(2)
        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)

        def toggle(label: str, attr: str, tip: str = "") -> QCheckBox:
            box = QCheckBox(label)
            box.setChecked(getattr(settings, attr))
            box.toggled.connect(lambda on: setattr(settings, attr, on))
            if tip:
                box.setToolTip(tip)
            form.addRow(box)
            return box

        toggle("Preview in editor", "show_gallery_after_capture")
        toggle("Copy to clipboard", "copy_after_capture")
        cursor = toggle("Capture cursor", "capture_cursor",
                        "Include the pointer (Spectacle backend)")
        if sys.platform == "win32":
            # mss grabs via BitBlt and cannot composite the cursor
            cursor.setEnabled(False)
            cursor.setToolTip("Not available on Windows (the capture "
                              "backend cannot include the pointer)")
        elif not shutil.which("spectacle"):
            cursor.setEnabled(False)
            cursor.setToolTip("Needs the Spectacle backend")

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 10)
        self.delay_spin.setSuffix(" s")
        self.delay_spin.setValue(settings.capture_delay)
        self.delay_spin.valueChanged.connect(
            lambda v: setattr(settings, "capture_delay", v))
        form.addRow("Delay", self.delay_spin)
        left.addLayout(form)

        # Hotkey UX lives in Settings → General now (QKeySequenceEdit;
        # app-owned registration on Windows) — no hint label here.
        left.addStretch(1)
        root.addLayout(left)

        # -- the big red button ----------------------------------------------
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignCenter)
        right.setSpacing(4)
        cap = QPushButton("Capture")
        cap.setFixedSize(80, 80)
        cap.setDefault(True)
        cap.setStyleSheet("""
            QPushButton {
                background: #d3382c; color: white; font-weight: bold;
                font-size: 11pt; border-radius: 40px; border: none;
            }
            QPushButton:hover { background: #e4493d; }
            QPushButton:pressed { background: #b32a20; }
        """)
        cap.clicked.connect(lambda: self._fire("region"))
        right.addWidget(cap, 0, Qt.AlignHCenter)

        row = QHBoxLayout()
        row.setSpacing(2)
        secondary = [("Full screen", "fullscreen")]
        if window_mode:
            secondary.append(("Window", "window-auto"))
        if scroll_mode:
            secondary.append(("Scrolling", "scroll"))
        secondary.append(("Record", "record"))
        for label, mode in secondary:
            b = QPushButton(label)
            b.setFlat(True)
            b.setStyleSheet(
                "color: palette(link); font-size: 8pt; padding: 2px 4px;")
            b.clicked.connect(lambda _=False, m=mode: self._fire(m))
            row.addWidget(b)
        right.addLayout(row)
        root.addLayout(right)

        self.setFixedSize(self.sizeHint())

    def _fire(self, mode: str) -> None:
        # Hiding is owned by gallery.hide_for_capture() (via the app
        # coordinator) so the panel is also RESTORED after the shot; hiding
        # here first would mark it as never-visible and lose it.
        self.capture_requested.emit(mode)


# -- scroll-capture stop pill -------------------------------------------------

class ScrollStopPill(QWidget):
    """Frameless always-on-top pill shown while a scroll capture runs.

    One affordance: click (or Esc) to finish. Short-lived like
    countdown.CountdownOverlay, so the compositor places it — no KWin
    position rule is written (Wayland clients can't self-position;
    bubble.py documents the rule mechanism we deliberately skip).
    Note for the manual checklist: when the user picks a MONITOR (not
    a window) in the portal, the pill itself can appear in captured
    frames; window picks stream the window buffer and exclude it."""

    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle("wondershot scroll stop")
        self._fired = False

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        btn = QPushButton("Scrolling — click to finish")
        btn.setStyleSheet("""
            QPushButton {
                background: #d3382c; color: white; font-weight: bold;
                border-radius: 14px; border: none; padding: 6px 18px;
            }
            QPushButton:hover { background: #e4493d; }
            QPushButton:pressed { background: #b32a20; }
        """)
        btn.clicked.connect(self._fire)
        row.addWidget(btn)
        self.setFixedSize(self.sizeHint())

    def _fire(self) -> None:
        if self._fired:
            return  # a double click must not double-stop
        self._fired = True
        self.stop_requested.emit()

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self._fire()
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):  # noqa: N802
        # Compositor/user closing the pill must still finish the scroll
        # session — otherwise it's only finishable via the tray.
        self._fire()
        super().closeEvent(ev)


# -- post-capture quick-action bar -------------------------------------------

QUICKBAR_TITLE = "wondershot quick actions"
QUICKBAR_RULE_ID = "wondershotquickbar"


def quickbar_rule_position(avail, bar_w: int = 480, bar_h: int = 110):
    """Bottom-center placement for the KWin window rule.

    Wayland gives no panel struts (availableGeometry == full screen), so
    leave the same generous bottom clearance the bubble uses.
    """
    x = avail.x() + (avail.width() - bar_w) // 2
    y = avail.y() + avail.height() - bar_h - 96
    return x, y


def ensure_quickbar_rule() -> None:
    """KWin window rule placing the bar bottom-center on open.

    Same mechanism as bubble.ensure_position_rule (see bubble.py:27):
    Wayland clients can't position their own top-levels; rule policy 3 =
    'apply initially'. No-op off KDE. GUI glue — not unit tested.
    """
    import shutil as _shutil
    import subprocess

    if not _shutil.which("kwriteconfig6"):
        return
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    x, y = quickbar_rule_position(screen.availableGeometry())

    def kwrite(key, value):
        subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc",
                        "--group", QUICKBAR_RULE_ID, "--key", key, value],
                       capture_output=True, timeout=5)

    try:
        out = subprocess.run(
            ["kreadconfig6", "--file", "kwinrulesrc",
             "--group", "General", "--key", "rules"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        rules = [r for r in out.split(",") if r]
        kwrite("Description", "Wondershot quick-action bar")
        kwrite("title", QUICKBAR_TITLE)
        kwrite("titlematch", "1")  # exact
        kwrite("position", f"{x},{y}")
        kwrite("positionrule", "3")  # apply initially
        if QUICKBAR_RULE_ID not in rules:
            rules.append(QUICKBAR_RULE_ID)
            subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc",
                            "--group", "General", "--key", "rules",
                            ",".join(rules)],
                           capture_output=True, timeout=5)
        subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/KWin",
                        "org.kde.KWin", "reconfigure"],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


class QuickActionBar(QWidget):
    """Frameless always-on-top bar shown after a capture lands.

    Acts on the just-captured file. Copy/Save-as are handled here;
    Edit/Share/Trash are emitted for the app coordinator to wire into
    the existing gallery/editor flows. Mouse-first; Esc dismisses;
    auto-dismisses after settings.quick_bar_timeout seconds (paused
    while hovered).
    """

    edit_requested = Signal(str)
    share_requested = Signal(str)
    trash_requested = Signal(str)
    dismissed = Signal()

    def __init__(self, settings, path: str, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QIcon, QPixmap
        from PySide6.QtWidgets import QToolButton

        self.settings = settings
        self.path = path
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setWindowTitle(QUICKBAR_TITLE)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(6)

        self.thumb = QLabel(self)
        pm = QPixmap(path)
        if not pm.isNull():
            self.thumb.setPixmap(
                pm.scaledToHeight(56, Qt.SmoothTransformation))
        row.addWidget(self.thumb)
        row.addSpacing(8)

        def btn(text, icon, slot):
            b = QToolButton(self)
            b.setText(text)
            b.setIcon(icons.icon(icon))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        self.edit_btn = btn("Edit", "document-edit",
                            lambda: self._act(self.edit_requested))
        self.copy_btn = btn("Copy", "edit-copy", self._copy)
        self.save_btn = btn("Save as", "document-save-as", self._save_as)
        self.share_btn = btn("Share", "document-send",
                             lambda: self._act(self.share_requested))
        self.trash_btn = btn("Trash", "user-trash",
                             lambda: self._act(self.trash_requested))

        self.close_btn = QToolButton(self)
        self.close_btn.setText("✕")
        self.close_btn.setAutoRaise(True)
        self.close_btn.setToolTip("Dismiss (Esc)")
        self.close_btn.clicked.connect(self.dismiss)
        row.addWidget(self.close_btn)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(2, int(settings.quick_bar_timeout)) * 1000)
        self._timer.timeout.connect(self.dismiss)

    # -- behavior ---------------------------------------------------------

    def _act(self, sig) -> None:
        sig.emit(self.path)
        self.dismiss()

    def _copy(self) -> None:
        from PySide6.QtGui import QGuiApplication, QImage
        img = QImage(self.path)
        if not img.isNull():
            QGuiApplication.clipboard().setImage(img)
        self.dismiss()

    def _save_as(self) -> None:  # GUI glue — file dialog, not unit tested
        import shutil as _shutil
        from PySide6.QtWidgets import QFileDialog
        self._timer.stop()  # don't vanish under the dialog
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save copy", os.path.join(
                os.path.expanduser("~"), os.path.basename(self.path)),
            "Images (*.png *.jpg *.webp)")
        if dest:
            try:
                _shutil.copy2(self.path, dest)
            except OSError:
                pass
        self.dismiss()

    def dismiss(self) -> None:
        self._timer.stop()
        self.dismissed.emit()
        self.close()

    # -- events -------------------------------------------------------------

    def showEvent(self, ev):  # noqa: N802
        self._timer.start()
        super().showEvent(ev)

    def enterEvent(self, ev):  # noqa: N802 — hover pauses auto-dismiss
        self._timer.stop()
        super().enterEvent(ev)

    def leaveEvent(self, ev):  # noqa: N802
        self._timer.start()
        super().leaveEvent(ev)

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(ev)
