"""Frameless on-screen countdown shown before a recording starts.

Wayland clients can't self-position; like the bubble and the quick bar
the compositor places this window. It only lives a few seconds, so no
KWin position rule is written — default placement is fine. Esc or a
click cancels; closing it any other way also counts as cancel.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class CountdownOverlay(QWidget):
    finished = Signal()   # ticked down to zero — start the recording
    cancelled = Signal()  # Esc / click / closed — do NOT start

    def __init__(self, seconds: int, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("wondershot countdown")
        self._left = max(1, int(seconds))
        self._done = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 24, 48, 24)
        self.label = QLabel(str(self._left), self)
        font = QFont()
        font.setPointSize(64)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        hint = QLabel("Esc to cancel", self)
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self._done = True
            self._timer.stop()
            self.finished.emit()
            self.close()
        else:
            self.label.setText(str(self._left))

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.cancelled.emit()
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancel()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, _event) -> None:
        self.cancel()

    def closeEvent(self, event) -> None:
        if not self._done:  # closed by the WM/user: treat as cancel
            self._done = True
            self._timer.stop()
            self.cancelled.emit()
        super().closeEvent(event)
