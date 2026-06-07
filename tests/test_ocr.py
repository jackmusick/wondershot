import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session", autouse=True)
def qapp():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


# Real tesseract 5 TSV shape: 12 tab-separated columns, level 5 = word.
TSV = "\t".join(["level", "page_num", "block_num", "par_num", "line_num",
                 "word_num", "left", "top", "width", "height", "conf",
                 "text"]) + "\n" + "\n".join([
    "1\t1\t0\t0\t0\t0\t0\t0\t640\t480\t-1\t",            # page row
    "5\t1\t1\t1\t1\t1\t10\t20\t80\t18\t96.5\tEmail:",
    "5\t1\t1\t1\t1\t2\t100\t20\t190\t18\t91.0\tjack@example.com",
    "5\t1\t1\t1\t2\t1\t10\t50\t60\t18\t88.2\tCard",
    "5\t1\t1\t1\t2\t2\t80\t50\t40\t18\t-1\t",            # empty word
    "5\t1\t1\t1\t2\t3\t130\t50\t90\t18\t85.0\t4111-1111",
])


def test_parse_tsv_words_and_boxes():
    from wondershot.ocr import parse_tsv
    words = parse_tsv(TSV)
    assert [w.text for w in words] == ["Email:", "jack@example.com",
                                       "Card", "4111-1111"]
    w = words[1]
    assert (w.x, w.y, w.w, w.h) == (100, 20, 190, 18)
    assert w.conf == 91.0


def test_parse_tsv_empty_input():
    from wondershot.ocr import parse_tsv
    assert parse_tsv("") == []


def test_ocr_words_degrades_without_tesseract(monkeypatch):
    import wondershot.ocr as ocr
    from PySide6.QtGui import QColor, QImage
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    img = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    assert ocr.find_tesseract() is None
    assert ocr.ocr_words(img) == []   # graceful: no crash, no boxes


def test_ocr_words_runs_binary(monkeypatch):
    import wondershot.ocr as ocr
    from PySide6.QtGui import QColor, QImage

    class _Out:
        returncode = 0
        stdout = TSV.encode()

    seen = {}

    def fake_run(cmd, input=None, capture_output=False, timeout=0):
        seen["cmd"] = cmd
        seen["png"] = input[:8]
        return _Out()

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    img = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    words = ocr.ocr_words(img, binary="/usr/bin/tesseract")
    assert seen["cmd"] == ["/usr/bin/tesseract", "stdin", "stdout", "tsv"]
    assert seen["png"] == b"\x89PNG\r\n\x1a\n"
    assert len(words) == 4
