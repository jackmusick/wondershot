"""Pure-function tests for the AI simplifier (no editor, no network)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _img(w, h, color):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return img


def test_dominant_color_solid_region(qapp):
    from wondershot.simplify import dominant_color
    img = _img(100, 80, "#3daee9")
    assert dominant_color(img, QRect(10, 10, 50, 40)) == QColor("#3daee9")


def test_dominant_color_majority_wins(qapp):
    from wondershot.simplify import dominant_color
    img = _img(100, 100, "#102030")          # majority: dark blue
    p = QPainter(img)
    p.fillRect(0, 0, 100, 20, QColor("#ffffff"))   # minority stripe
    p.end()
    c = dominant_color(img, QRect(0, 0, 100, 100))
    assert c == QColor("#102030")


def test_dominant_color_clamps_and_falls_back(qapp):
    from wondershot.simplify import dominant_color
    img = _img(50, 50, "#ff0000")
    # fully off-image -> neutral fallback, never a crash
    assert dominant_color(img, QRect(200, 200, 10, 10)) == QColor("#808080")
    # partially off-image -> clamped, still the image color
    assert dominant_color(img, QRect(45, 45, 30, 30)) == QColor("#ff0000")


def test_parse_regions_normalized_to_pixels(qapp):
    from wondershot.simplify import parse_regions
    reply = ('[{"type": "text", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.2},'
             ' {"type": "chrome", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.05}]')
    regions = parse_regions(reply, 1000, 800)
    assert len(regions) == 2
    assert regions[0].kind == "text"
    assert regions[0].rect == QRect(100, 80, 400, 80)
    assert regions[1].kind == "chrome"
    assert regions[1].rect == QRect(0, 0, 1000, 40)


def test_parse_regions_unwraps_fences_and_clamps(qapp):
    from wondershot.simplify import parse_regions
    reply = ('```json\n[{"type": "IMAGE", "x0": 0.9, "y0": 0.9, '
             '"x1": 1.4, "y1": 1.4}]\n```')
    regions = parse_regions(reply, 100, 100)
    assert len(regions) == 1
    assert regions[0].kind == "image"          # kind is case-normalized
    assert regions[0].rect == QRect(90, 90, 10, 10)   # clamped to image


def test_parse_regions_skips_junk(qapp):
    from wondershot.simplify import parse_regions
    reply = ('[{"type": "hologram", "x0": 0, "y0": 0, "x1": 0.5, "y1": 0.5},'
             ' {"type": "text"},'
             ' "not an object",'
             ' {"type": "text", "x0": "a", "y0": 0, "x1": 0.5, "y1": 0.5},'
             ' {"type": "text", "x0": 0.5, "y0": 0.5, "x1": 0.5, "y1": 0.5}]')
    assert parse_regions(reply, 100, 100) == []   # unknown kind, missing
    # coords, wrong shape, non-numeric, zero-area: all silently dropped


def test_parse_regions_rejects_non_json(qapp):
    from wondershot.simplify import parse_regions
    with pytest.raises(OSError):
        parse_regions("I could not find any regions, sorry!", 100, 100)
    with pytest.raises(OSError):
        parse_regions('"just a string"', 100, 100)   # JSON, but not array
    # an object-wrapped EMPTY array means "no regions", not an error
    assert parse_regions('{"regions": []}', 100, 100) == []


def test_simplify_regions_pipeline_calls_chat(qapp, monkeypatch):
    import wondershot.simplify as simplify
    calls = {}

    def fake_chat(endpoint, api_key, model, prompt, image=None, timeout=120):
        calls.update(endpoint=endpoint, model=model, prompt=prompt,
                     image=image)
        return '[{"type": "text", "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}]'

    monkeypatch.setattr(simplify.aiclient, "chat", fake_chat)
    img = _img(200, 100, "white")
    regions = simplify.simplify_regions(img, "http://localhost:1234", "k",
                                        "llava")
    assert calls["model"] == "llava"
    assert calls["image"] is img               # vision call carries the image
    assert "JSON array" in calls["prompt"]
    assert regions == [simplify.Region(QRect(0, 0, 100, 50), "text")]


def test_parse_regions_unwraps_object_wrapped_array(qapp):
    """Some models return {"regions":[...]} instead of a bare array."""
    from wondershot.simplify import parse_regions
    reply = '{"regions": [{"type":"text","x0":0,"y0":0,"x1":0.5,"y1":0.5}]}'
    regions = parse_regions(reply, 100, 100)
    assert len(regions) == 1 and regions[0].kind == "text"


def test_parse_regions_survives_prose_wrapped_array(qapp):
    from wondershot.simplify import parse_regions
    reply = ('I found these regions:\n'
             '[{"type":"chrome","x0":0,"y0":0,"x1":1,"y1":0.1}]\nDone.')
    regions = parse_regions(reply, 200, 200)
    assert len(regions) == 1 and regions[0].kind == "chrome"
