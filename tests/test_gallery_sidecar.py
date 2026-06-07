"""Gallery <-> sidecar integration: trash, undo-delete, rename, scan, quit."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
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
                 "share_expiry_days",
                 # numeric video settings from the video-backlog track:
                 # GalleryWindow builds the video pane with these
                 "video_blur_strength", "gif_fps", "gif_max_width"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic",
                                      "noise", "copy")) else ""


class _Capture:
    def __getattr__(self, k):
        return lambda *a, **kw: None


def make_gallery(qapp, tmp_path):
    from wondershot.gallery import GalleryWindow
    return GalleryWindow(_Settings(str(tmp_path)), _Capture())


def seed_image_with_sidecar(tmp_path, name="shot.png"):
    from wondershot import sidecar
    path = os.path.join(str(tmp_path), name)
    img = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    img.save(path)
    sidecar.save(path, {"version": 1, "bases": 1, "items": [],
                        "effects": {}})
    img.save(sidecar.base_path(path, 0))
    return path


def test_trash_takes_sidecar_files_along(qapp, tmp_path):
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g._trash_paths([path], confirm=False)
    assert not os.path.exists(path)
    assert not os.path.exists(sidecar.sidecar_path(path))
    assert not os.path.exists(sidecar.base_path(path, 0))


def test_undo_delete_restores_sidecar_files(qapp, tmp_path):
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g._trash_paths([path], confirm=False)
    g._undo_delete()
    assert os.path.exists(path)
    assert os.path.exists(sidecar.sidecar_path(path))
    assert os.path.exists(sidecar.base_path(path, 0))
    data = json.load(open(sidecar.sidecar_path(path)))
    assert data["version"] == 1


def test_undo_delete_recreates_wondershot_dir(qapp, tmp_path):
    """Trashing the LAST image may leave .wondershot empty/removed; the
    restore must recreate the directory before moving files back."""
    import shutil
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g._trash_paths([path], confirm=False)
    shutil.rmtree(sidecar.sidecar_dir(path), ignore_errors=True)
    g._undo_delete()
    assert os.path.exists(sidecar.sidecar_path(path))


def test_wondershot_dir_never_appears_in_strip(qapp, tmp_path):
    """Regression pin: base PNGs live under .wondershot/ and must not be
    scanned into the carousel."""
    seed_image_with_sidecar(tmp_path)
    g = make_gallery(qapp, tmp_path)
    g.rescan()
    from wondershot.gallery import PATH_ROLE
    names = [os.path.basename(g.model.item(r).data(PATH_ROLE))
             for r in range(g.model.rowCount())]
    assert names == ["shot.png"]


def test_rename_moves_sidecar_files(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from wondershot import sidecar
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g.rescan()
    g._select_silently(path)
    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("renamed.png", True)))
    g._rename_selected()
    new = os.path.join(str(tmp_path), "renamed.png")
    assert os.path.exists(new)
    assert os.path.exists(sidecar.sidecar_path(new))
    assert os.path.exists(sidecar.base_path(new, 0))
    assert sidecar.related_files(path) == []


def test_really_quit_autosaves_standalone_editor(qapp, tmp_path,
                                                 monkeypatch):
    """App quit: open standalone editors close (and autosave) silently."""
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QMessageBox
    from wondershot import sidecar
    from wondershot.editor import AddItemCommand
    from wondershot.items import RectItem
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: pytest.fail("quit must not prompt")))
    g = make_gallery(qapp, tmp_path)
    path = seed_image_with_sidecar(tmp_path)
    g.open_editor(path)
    win = g._windows[0]
    win.undo_stack.push(
        AddItemCommand(win, RectItem(QRectF(1, 1, 10, 10),
                                     QColor("red"), 2)))
    g.really_quit()
    data = json.load(open(sidecar.sidecar_path(path)))
    assert len(data["items"]) == 1, "standalone window autosaved on quit"
