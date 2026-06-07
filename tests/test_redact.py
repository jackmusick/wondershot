import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QRect


@pytest.fixture(scope="session", autouse=True)
def qapp():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def W(text, x, y, w=50, h=16):
    from wondershot.ocr import Word
    return Word(text=text, x=x, y=y, w=w, h=h, conf=90.0)


def test_extract_json_strips_markdown_fences():
    from wondershot.redact import extract_json
    assert extract_json('["a"]') == '["a"]'
    assert extract_json('```json\n["a", "b"]\n```') == '["a", "b"]'
    assert extract_json('Sure! Here you go:\n```\n[1]\n```\n') == '[1]'


def test_parse_spans():
    from wondershot.redact import parse_spans
    assert parse_spans('["jack@example.com", "4111-1111"]') == \
        ["jack@example.com", "4111-1111"]
    assert parse_spans("[]") == []
    with pytest.raises(OSError):
        parse_spans("the model rambled instead of returning JSON")
    with pytest.raises(OSError):
        parse_spans('{"not": "a list"}')


def test_match_single_word_span():
    from wondershot.redact import match_spans
    words = [W("Email:", 10, 20), W("jack@example.com", 100, 20, 190)]
    rects = match_spans(["jack@example.com"], words)
    assert rects == [QRect(100, 20, 190, 16)]


def test_match_multi_word_span_unions_boxes():
    from wondershot.redact import match_spans
    words = [W("token", 10, 20), W("is", 70, 20, 20),
             W("ghp_abc123", 100, 20, 120)]
    rects = match_spans(["is ghp_abc123"], words)
    assert rects == [QRect(70, 20, 150, 16)]


def test_match_is_case_and_punctuation_tolerant():
    from wondershot.redact import match_spans
    # OCR saw "Jack@Example.com," (trailing comma); LLM returns clean text
    words = [W("Jack@Example.com,", 5, 5, 180)]
    assert match_spans(["jack@example.com"], words) == [QRect(5, 5, 180, 16)]


def test_match_unmatched_span_yields_nothing():
    from wondershot.redact import match_spans
    assert match_spans(["nope"], [W("hello", 0, 0)]) == []


def test_parse_bboxes_denormalizes_and_clamps():
    from wondershot.redact import parse_bboxes
    reply = json.dumps([
        {"x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.3},
        {"x0": -0.2, "y0": 0.0, "x1": 1.4, "y1": 0.1},   # out of range
    ])
    rects = parse_bboxes(reply, 1000, 500)
    assert rects[0] == QRect(100, 100, 400, 50)
    assert rects[1] == QRect(0, 0, 1000, 50)             # clamped to image


def test_redact_regions_uses_ocr_path_when_words_found(monkeypatch):
    import wondershot.redact as redact
    from PySide6.QtGui import QColor, QImage

    words = [W("secret@example.com", 30, 40, 200)]
    monkeypatch.setattr(redact.ocr, "ocr_words", lambda img: words)
    prompts = []

    def fake_chat(endpoint, key, model, prompt, image=None, timeout=120):
        prompts.append(prompt)
        return '["secret@example.com"]'

    monkeypatch.setattr(redact.aiclient, "chat", fake_chat)
    img = QImage(640, 480, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    rects = redact.redact_regions(img, "http://x", "", "llava")
    assert rects == [QRect(30, 40, 200, 16)]
    assert "secret@example.com" in prompts[0]   # OCR words fed to the LLM


def test_redact_regions_falls_back_to_bboxes(monkeypatch):
    import wondershot.redact as redact
    from PySide6.QtGui import QColor, QImage

    monkeypatch.setattr(redact.ocr, "ocr_words", lambda img: [])
    monkeypatch.setattr(
        redact.aiclient, "chat",
        lambda *a, **k: '[{"x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}]')
    img = QImage(200, 100, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    assert redact.redact_regions(img, "http://x", "", "llava") == \
        [QRect(0, 0, 100, 50)]
