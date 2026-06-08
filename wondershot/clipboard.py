"""Clipboard helpers that survive Wayland's focus requirement.

On Wayland a client may only take the selection (``wl_data_device.set_selection``)
using an input-event *serial*, which the compositor grants only while the client
holds focus. Wondershot's auto-copy after a capture runs at the one moment it has
*no* focused surface — every window was hidden to stay out of the shot — so Qt's
``clipboard().setImage()`` silently fails to take ownership there.

``wl-copy`` sidesteps this: it forks a process that holds the selection on its own,
independent of any Qt focus. We use it on Wayland and fall back to Qt elsewhere
(X11, Windows), where the focus rule does not apply.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QImage


def _on_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) and shutil.which("wl-copy") is not None


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def copy_image(img: QImage) -> bool:
    """Put `img` on the clipboard. Returns True if it actually took.

    Uses wl-copy on Wayland (focus-independent), Qt otherwise.
    """
    if img.isNull():
        return False
    if _on_wayland():
        try:
            subprocess.run(
                ["wl-copy", "--type", "image/png"],
                input=_png_bytes(img),
                check=True,
                timeout=10,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            pass  # fall through to Qt as a last resort
    QGuiApplication.clipboard().setImage(img)
    return True
