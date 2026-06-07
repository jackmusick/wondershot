"""Local background removal via rembg/U²-Net ONNX — optional extra.

Installed with `pip install wondershot[ai-local]`. Per the design spec,
background removal is ALWAYS local ONNX, never the LLM endpoint (chat
APIs don't return alpha mattes). All rembg imports are guarded so the
core app never requires onnxruntime.
"""

from __future__ import annotations

import importlib.util


def available() -> bool:
    return importlib.util.find_spec("rembg") is not None


def remove_background(image):
    """QImage -> QImage with the background made transparent.

    Round-trips through PNG bytes (rembg's native interface); the result
    comes back ARGB32_Premultiplied so the editor's checkerboard mat and
    flatten path handle the alpha untouched.
    """
    if not available():
        raise OSError("Background removal needs the optional extra: "
                      "pip install wondershot[ai-local]")
    import rembg
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    out_bytes = rembg.remove(bytes(buf.data()))
    out = QImage.fromData(out_bytes, "PNG")
    if out.isNull():
        raise OSError("background removal produced no image")
    return out.convertToFormat(QImage.Format_ARGB32_Premultiplied)
