"""Our windows must leave the screen before a capture fires (and come back).

Jack's bug: capturing from the Capture window left it in the shot — its
self-hide raced the compositor, and gallery._capture_mode bypassed the
app's hide logic entirely. One path now: every trigger routes through
hide_for_capture()/restore_after_capture().
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget


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
                 "share_expiry_days", "quick_bar_timeout"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick", "capture_cursor")) else ""


class _Capture:
    def __getattr__(self, k):
        return lambda *a, **kw: None


def make_gallery(qapp, tmp_path):
    from wondershot.gallery import GalleryWindow
    return GalleryWindow(_Settings(str(tmp_path)), _Capture())


def test_hide_for_capture_hides_everything_and_needs_delay(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    g.show()
    g._open_capture_window()
    editor = QWidget()  # stands in for a standalone EditorWindow
    g._windows.append(editor)
    editor.show()

    assert g.hide_for_capture() == 300
    assert not g.isVisible()
    assert not g._capture_window.isVisible()
    assert not editor.isVisible()


def test_hide_for_capture_nothing_visible_no_delay(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    assert g.hide_for_capture() == 0


def test_restore_brings_back_capture_window_and_editors_not_gallery(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    g.show()
    g._open_capture_window()
    editor = QWidget()
    g._windows.append(editor)
    editor.show()
    g.hide_for_capture()

    g.restore_after_capture()
    assert g._capture_window.isVisible()
    assert editor.isVisible()
    # gallery's return is the app coordinator's call (show_gallery_after_capture
    # / quick-bar logic) — restore must NOT preempt it
    assert not g.isVisible()


def test_restore_skips_windows_hidden_before_capture(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    g._open_capture_window()
    g._capture_window.hide()  # user closed it earlier
    g.hide_for_capture()
    g.restore_after_capture()
    assert not g._capture_window.isVisible()


def test_capture_mode_emits_instead_of_calling_backend(qapp, tmp_path):
    g = make_gallery(qapp, tmp_path)
    fired = []
    g.capture_requested.connect(fired.append)
    g._capture_mode("window-auto")
    assert fired == ["window-auto"]
