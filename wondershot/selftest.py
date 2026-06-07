"""Dev-only: render UI screenshots offscreen so the app can be inspected
without a display (used during development; harmless to ship)."""

from __future__ import annotations

import os
import sys


def _sample_image(w=900, h=560):
    from PySide6.QtCore import Qt, QRect
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter

    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor("#2b5876"))
    grad.setColorAt(1, QColor("#4e4376"))
    p = QPainter(img)
    p.fillRect(0, 0, w, h, grad)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPointSize(28)
    p.setFont(f)
    p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, "sample screenshot")
    p.setPen(QColor("#aacccc"))
    for x in range(0, w, 60):
        p.drawLine(x, h - 30, x, h - 10)
    p.end()
    return img


def run_selftest(out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    from PySide6.QtCore import QPointF, QRect, QRectF, QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName("wondershot")
    qapp.setOrganizationName("wondershot")

    from .capture import CaptureManager
    from .editor import EditorWindow, Tool
    from .gallery import PATH_ROLE, GalleryWindow
    from .items import ArrowItem, HighlightItem, RectItem, StepItem, TextItem
    from .settings import Settings

    # --- editor with one of each annotation -------------------------------
    img = _sample_image()
    sample_path = os.path.join(out_dir, "sample.png")
    img.save(sample_path)

    editor = EditorWindow(sample_path, settings=None)
    ed = editor  # alias
    red = QColor("#e3242b")
    arrow = ArrowItem(QPointF(120, 420), QPointF(330, 250), red, 6)
    ed.scene.addItem(arrow)
    ed.scene.addItem(RectItem(QRectF(360, 180, 220, 130), QColor("#2196f3"), 4))
    ed.scene.addItem(HighlightItem(QRectF(250, 250, 380, 60), QColor("#ffe000")))
    step1 = StepItem(QPointF(140, 140), 1, red)
    step2 = StepItem(QPointF(640, 140), 2, red)
    ed.scene.addItem(step1)
    ed.scene.addItem(step2)
    text = TextItem(QPointF(420, 430), QColor("white"))
    text.setPlainText("Annotated with Wondershot")
    ed.scene.addItem(text)
    ed._apply_pixelate(QRect(620, 320, 180, 120))

    editor.resize(1180, 760)
    editor.show()
    arrow.setSelected(True)  # sidebar reflects the arrow's style
    editor.grab().save(os.path.join(out_dir, "editor.png"))

    flat = editor.flattened()
    flat.save(os.path.join(out_dir, "flattened.png"))

    # crop test via tool path
    ed._apply_crop(QRect(80, 80, 700, 420))
    editor.flattened().save(os.path.join(out_dir, "cropped.png"))
    ed.undo_stack.undo()
    editor.grab().save(os.path.join(out_dir, "editor_after_undo.png"))

    # --- gallery populated with sample shots ------------------------------
    import tempfile

    libdir = tempfile.mkdtemp(prefix="wondershot-selftest-")
    for i in range(5):
        variant = _sample_image(720 + i * 60, 420 + i * 30)
        variant.save(os.path.join(libdir, f"Screenshot_2026060{i + 1}_12000{i}.png"))

    settings = Settings()
    real_lib = settings.library_dir

    class FakeSettings:
        library_dir = libdir
        extra_dirs = []
        backend = "auto"
        copy_after_capture = False
        show_gallery_after_capture = True
        pin_on_top = False

        def __getattr__(self, k):
            # The editor/gallery grow settings faster than this harness
            # tracks; default sanely so --selftest (the frozen-build
            # smoke test) doesn't rot every time a setting is added.
            if k in ("stroke_width", "font_size", "capture_delay",
                     "share_expiry_days", "video_blur_strength",
                     "gif_fps", "gif_max_width", "quick_bar_timeout"):
                return 10
            if k == "tool_color":
                return "#e3242b"
            return (False if k.startswith(("pin", "show", "mic", "noise",
                                           "copy", "record", "capture"))
                    else "")

    capture = CaptureManager(FakeSettings())
    gallery = GalleryWindow(FakeSettings(), capture)
    gallery.resize(1280, 860)
    gallery.show()

    # Let thumbnail jobs finish, then grab and quit.
    def finish():
        gallery.grab().save(os.path.join(out_dir, "gallery.png"))

        # switching carousel selection swaps the editor image
        second = gallery.model.item(1).data(PATH_ROLE)
        gallery.select_path(second)
        assert gallery.editor.path == second, "carousel selection did not load editor"
        gallery.grab().save(os.path.join(out_dir, "gallery_second.png"))

        # verify drag mime payload
        idx = gallery.model.index(0, 0)
        mime = gallery.model.mimeData([idx])
        urls = mime.urls()
        assert mime.hasUrls() and urls, "drag mime has no urls"
        assert os.path.exists(urls[0].toLocalFile()), "drag url target missing"
        assert mime.hasImage(), "drag mime has no image data"
        print("drag mime ok:", urls[0].toString())
        print("selftest artifacts in", out_dir, "(library was", real_lib, ")")
        qapp.exit(0)

    QTimer.singleShot(1200, finish)
    return qapp.exec()
