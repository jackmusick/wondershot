import pytest
from PySide6.QtGui import QColor, QImage

from wondershot import clipboard


@pytest.fixture(scope="session", autouse=True)
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def solid(w=20, h=10, color="red") -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return img


def test_null_image_is_not_copied(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(clipboard, "_on_wayland", lambda: False)
    monkeypatch.setattr(
        clipboard.QGuiApplication, "clipboard",
        lambda: (_ for _ in ()).throw(AssertionError("should not be reached")))
    assert clipboard.copy_image(QImage()) is False


def test_wayland_uses_wl_copy_with_png(monkeypatch):
    seen = {}

    def fake_run(cmd, *, input, check, timeout):
        seen["cmd"] = cmd
        seen["input"] = input
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(clipboard, "_on_wayland", lambda: True)
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)

    assert clipboard.copy_image(solid()) is True
    assert seen["cmd"] == ["wl-copy", "--type", "image/png"]
    # PNG magic number — proves we piped real image bytes, not a path.
    assert seen["input"][:8] == b"\x89PNG\r\n\x1a\n"


def test_wl_copy_failure_falls_back_to_qt(monkeypatch):
    def boom(*a, **k):
        raise OSError("wl-copy missing mid-run")

    fell_back = {"hit": False}

    class FakeClip:
        def setImage(self, img):
            fell_back["hit"] = True

    monkeypatch.setattr(clipboard, "_on_wayland", lambda: True)
    monkeypatch.setattr(clipboard.subprocess, "run", boom)
    monkeypatch.setattr(clipboard.QGuiApplication, "clipboard", lambda: FakeClip())

    assert clipboard.copy_image(solid()) is True
    assert fell_back["hit"] is True


def test_non_wayland_uses_qt(monkeypatch):
    used = {"hit": False}

    class FakeClip:
        def setImage(self, img):
            used["hit"] = True

    monkeypatch.setattr(clipboard, "_on_wayland", lambda: False)
    monkeypatch.setattr(clipboard.QGuiApplication, "clipboard", lambda: FakeClip())

    assert clipboard.copy_image(solid()) is True
    assert used["hit"] is True
