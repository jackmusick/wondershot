"""Follow the OS light/dark scheme on Windows.

On KDE the platform theme paints us and we keep our hands off. On
Windows, Qt's native styles keep a light palette even when the system
is dark (observed 2026-06-07: dark titlebar, light chrome — worst of
both). So on win32 we switch to Fusion and drive the palette from
``styleHints().colorScheme()``, re-applying live when the OS scheme
flips. Bundled icons (icons.py) tint from the live palette at paint
time, so they follow automatically.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def dark_palette() -> QPalette:
    """The well-worn Fusion dark palette."""
    p = QPalette()
    window = QColor(53, 53, 53)
    base = QColor(35, 35, 35)
    text = QColor(220, 220, 220)
    disabled = QColor(127, 127, 127)
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, window)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 80, 80))
    p.setColor(QPalette.Link, QColor(90, 160, 255))
    p.setColor(QPalette.Highlight, QColor(42, 110, 187))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.PlaceholderText, disabled)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, disabled)
    return p


def _apply(qapp) -> None:
    dark = qapp.styleHints().colorScheme() == Qt.ColorScheme.Dark
    qapp.setPalette(dark_palette() if dark else QPalette())


def apply_system_theme(qapp, platform: str | None = None) -> None:
    """Install scheme-following theming. No-op outside Windows."""
    if (platform or sys.platform) != "win32":
        return  # the desktop's platform theme owns us (KDE: Breeze)
    qapp.setStyle("Fusion")  # native styles ignore dark palettes
    _apply(qapp)
    qapp.styleHints().colorSchemeChanged.connect(lambda _s: _apply(qapp))
