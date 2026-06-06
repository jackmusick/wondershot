import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []

    def __getattr__(self, k):
        if k in ("stroke_width", "font_size", "capture_delay",
                 "share_expiry_days"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic",
                                      "noise", "copy")) else ""


class _Capture:
    def __getattr__(self, k):
        return lambda *a, **kw: None


def make_gallery(qapp, tmp_path):
    from grabbit.gallery import GalleryWindow
    return GalleryWindow(_Settings(str(tmp_path)), _Capture())


def test_trash_undo_roundtrip(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    f = tmp_path / "shot.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\nx")
    g._trash_paths([str(f)], confirm=False)
    assert not f.exists(), "file should be staged away"
    g._undo_delete()
    assert f.exists(), "Ctrl+Z must restore the file"


def test_trash_undo_stack_is_lifo(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    g._trash_paths([str(a)], confirm=False)
    g._trash_paths([str(b)], confirm=False)
    g._undo_delete()
    assert b.exists() and not a.exists()
    g._undo_delete()
    assert a.exists()


def test_flush_empties_undo(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    f = tmp_path / "c.png"
    f.write_bytes(b"c")
    g._trash_paths([str(f)], confirm=False)
    g.flush_trash()
    assert g._trash_undo == []
    g._undo_delete()  # no-op, must not raise
    assert not f.exists()
