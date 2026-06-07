import importlib.machinery
import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def qapp():
    # Full QApplication (not QGuiApplication): this file is collected before
    # the widget-based editor tests, which need the widgets-capable instance.
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _png_bytes(w, h, color, alpha=255):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format_ARGB32)
    c = QColor(color)
    c.setAlpha(alpha)
    img.fill(c)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


@pytest.fixture
def fake_rembg(monkeypatch):
    """A stand-in rembg whose remove() returns a half-transparent PNG."""
    mod = types.ModuleType("rembg")
    mod.__spec__ = importlib.machinery.ModuleSpec("rembg", None)
    mod.calls = []

    def remove(data: bytes) -> bytes:
        mod.calls.append(data[:8])
        return _png_bytes(4, 4, "blue", alpha=128)

    mod.remove = remove
    monkeypatch.setitem(sys.modules, "rembg", mod)
    return mod


def test_available_false_without_rembg(monkeypatch):
    import wondershot.bgremove as bgremove
    monkeypatch.setitem(sys.modules, "rembg", None)  # forces ImportError path
    monkeypatch.setattr(bgremove.importlib.util, "find_spec",
                        lambda name: None)
    assert bgremove.available() is False


def test_remove_background_raises_without_rembg(monkeypatch):
    import wondershot.bgremove as bgremove
    from PySide6.QtGui import QColor, QImage
    monkeypatch.setattr(bgremove.importlib.util, "find_spec",
                        lambda name: None)
    img = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    # Message is user-facing: no pip/Python (Jack, 2026-06-07).
    with pytest.raises(OSError, match="isn't included in this build"):
        bgremove.remove_background(img)


def test_remove_background_with_fake_rembg(fake_rembg):
    import wondershot.bgremove as bgremove
    from PySide6.QtGui import QColor, QImage
    assert bgremove.available() is True
    img = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    out = bgremove.remove_background(img)
    # rembg was fed PNG bytes of our image
    assert fake_rembg.calls == [b"\x89PNG\r\n\x1a\n"]
    # output preserves alpha in premultiplied format
    assert out.format() == QImage.Format_ARGB32_Premultiplied
    assert out.hasAlphaChannel()
    assert 100 < out.pixelColor(1, 1).alpha() < 160   # the fake's alpha=128
