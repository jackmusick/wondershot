"""AI redaction: find sensitive text on a screenshot, return regions.

Primary path: tesseract word boxes + a vision LLM that names WHICH text
is sensitive (text spans, never pixel coordinates — LLMs are bad at
those); spans are matched back to OCR boxes here. Fallback without
tesseract: ask the LLM for normalized bounding boxes directly
(documented as sloppier — localization quality is model-dependent).

The editor turns the returned QRects into PixelateItems — always
non-destructive, never auto-flattened.
"""

from __future__ import annotations

import json
import re

from PySide6.QtCore import QRect

from . import aiclient, ocr

SPAN_PROMPT = (
    "This is a screenshot. OCR detected the following words on it, in "
    "reading order:\n\n{words}\n\n"
    "Identify any text that should be redacted before sharing publicly: "
    "email addresses, names of private individuals, phone numbers, "
    "credit-card or account numbers, passwords, API keys/tokens, "
    "IP addresses, home addresses, and similar secrets or PII.\n"
    "Reply with ONLY a JSON array of strings. Each string must be an "
    "exact substring of the OCR text above (copy it verbatim, including "
    "several consecutive words when the sensitive value spans them). "
    "Reply [] if nothing is sensitive. No prose, no markdown."
)

BBOX_PROMPT = (
    "This is a screenshot. Find any text that should be redacted before "
    "sharing publicly: email addresses, names of private individuals, "
    "phone numbers, credit-card or account numbers, passwords, API "
    "keys/tokens, IP addresses, home addresses, and similar secrets or "
    "PII.\n"
    "Reply with ONLY a JSON array of bounding boxes, each an object "
    '{"x0": .., "y0": .., "x1": .., "y1": ..} with coordinates '
    "normalized to 0..1 relative to the image width/height (x0,y0 = "
    "top-left, x1,y1 = bottom-right). Reply [] if nothing is sensitive. "
    "No prose, no markdown."
)


def _span_from(text: str, start: int) -> str | None:
    """Balanced [...]/{...} starting at `start`, ignoring brackets inside
    JSON strings. None if it never closes."""
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _balanced_json_span(text: str) -> str | None:
    """First balanced [...] / {...} substring that PARSES as JSON. Trying
    each opening bracket in turn skips incidental prose brackets (e.g.
    'see [below]') and returns the real payload."""
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        span = _span_from(text, i)
        if span is None:
            continue
        try:
            json.loads(span)
        except ValueError:
            continue
        return span
    return None


def iter_json_values(text: str):
    """Yield every balanced [...]/{...} substring that parses as JSON, in
    order. Lets callers recover a list of objects a model scattered
    through prose/markdown instead of returning one array."""
    i, n = 0, len(text)
    while i < n:
        if text[i] in "[{":
            span = _span_from(text, i)
            if span is not None:
                try:
                    yield json.loads(span)
                except ValueError:
                    pass
                else:
                    i += len(span)
                    continue
        i += 1


def extract_json(reply: str) -> str:
    """Models love to wrap JSON in ``` fences and chatter — unwrap it.

    A ```fence``` if present, else the first balanced [...]/{...} span
    (handles prose before/after the JSON, which models emit despite
    'no prose'), else the stripped text (so json.loads raises usefully).
    """
    text = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    span = _balanced_json_span(text)
    return span if span is not None else text


def parse_spans(reply: str) -> list[str]:
    try:
        data = json.loads(extract_json(reply))
    except ValueError as e:
        raise OSError(f"AI reply was not JSON: {reply[:120]}") from e
    if not isinstance(data, list):
        raise OSError("AI reply was not a JSON array")
    return [s for s in data if isinstance(s, str) and s.strip()]


def _norm(s: str) -> str:
    """Lowercase, keep only chars that survive OCR/LLM round-trips."""
    return re.sub(r"[^a-z0-9@._+-]", "", s.lower()).strip(".,;:")


def match_spans(spans: list[str], words: list[ocr.Word]) -> list[QRect]:
    """Match LLM text spans back to OCR word boxes; union multi-word hits."""
    norm_words = [_norm(w.text) for w in words]
    rects: list[QRect] = []
    for span in spans:
        tokens = [t for t in (_norm(t) for t in span.split()) if t]
        if not tokens:
            continue
        n = len(tokens)
        for i in range(len(words) - n + 1):
            window = norm_words[i:i + n]
            if all(t == w or t in w for t, w in zip(tokens, window)):
                r = QRect(words[i].x, words[i].y, words[i].w, words[i].h)
                for w in words[i + 1:i + n]:
                    r = r.united(QRect(w.x, w.y, w.w, w.h))
                if r not in rects:
                    rects.append(r)
    return rects


def parse_bboxes(reply: str, width: int, height: int) -> list[QRect]:
    """Normalized-bbox fallback reply -> pixel QRects, clamped to image."""
    try:
        data = json.loads(extract_json(reply))
    except ValueError as e:
        raise OSError(f"AI reply was not JSON: {reply[:120]}") from e
    if not isinstance(data, list):
        raise OSError("AI reply was not a JSON array")
    img = QRect(0, 0, width, height)
    rects: list[QRect] = []
    for box in data:
        if not isinstance(box, dict):
            continue
        try:
            x0 = float(box["x0"]) * width
            y0 = float(box["y0"]) * height
            x1 = float(box["x1"]) * width
            y1 = float(box["y1"]) * height
        except (KeyError, TypeError, ValueError):
            continue
        r = QRect(round(min(x0, x1)), round(min(y0, y1)),
                  round(abs(x1 - x0)), round(abs(y1 - y0))).intersected(img)
        if not r.isEmpty():
            rects.append(r)
    return rects


def redact_regions(image, endpoint: str, api_key: str,
                   model: str) -> list[QRect]:
    """Blocking pipeline (call from AIJob, never the GUI thread)."""
    words = ocr.ocr_words(image)
    if words:
        prompt = SPAN_PROMPT.format(
            words=" ".join(w.text for w in words))
        reply = aiclient.chat(endpoint, api_key, model, prompt, image=image)
        return match_spans(parse_spans(reply), words)
    reply = aiclient.chat(endpoint, api_key, model, BBOX_PROMPT, image=image)
    return parse_bboxes(reply, image.width(), image.height())
