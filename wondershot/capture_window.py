"""Snagit-style capture panel: one big Capture button + capture defaults.

Compact always-on-top window. The toggles write straight to settings
(they ARE the defaults), the big button fires a region capture, with
full-screen and record as smaller secondary actions.
"""

from __future__ import annotations

import shutil

from PySide6.QtCore import Qt, Signal
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
    capture_requested = Signal(str)  # "region" | "fullscreen" | "record"

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Wondershot capture")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(24)

        # -- defaults column ------------------------------------------------
        left = QVBoxLayout()
        form = QFormLayout()
        form.setHorizontalSpacing(10)

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
        if not shutil.which("spectacle"):
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

        hint = QLabel("Hotkey: bind <code>wondershot --capture</code> in "
                      "System Settings")
        hint.setStyleSheet("color: palette(mid); font-size: 8pt;")
        left.addWidget(hint)
        left.addStretch(1)
        root.addLayout(left)

        # -- the big red button ----------------------------------------------
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignCenter)
        cap = QPushButton("Capture")
        cap.setFixedSize(92, 92)
        cap.setDefault(True)
        cap.setStyleSheet("""
            QPushButton {
                background: #d3382c; color: white; font-weight: bold;
                font-size: 12pt; border-radius: 46px; border: none;
            }
            QPushButton:hover { background: #e4493d; }
            QPushButton:pressed { background: #b32a20; }
        """)
        cap.clicked.connect(lambda: self._fire("region"))
        right.addWidget(cap, 0, Qt.AlignHCenter)

        row = QHBoxLayout()
        for label, mode in (("Full screen", "fullscreen"),
                            ("Record", "record")):
            b = QPushButton(label)
            b.setFlat(True)
            b.setStyleSheet("color: palette(link);")
            b.clicked.connect(lambda _=False, m=mode: self._fire(m))
            row.addWidget(b)
        right.addLayout(row)
        root.addLayout(right)

        self.setFixedSize(self.sizeHint())

    def _fire(self, mode: str) -> None:
        self.hide()  # never end up in the shot
        self.capture_requested.emit(mode)
