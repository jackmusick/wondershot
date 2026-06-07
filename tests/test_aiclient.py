import base64
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session", autouse=True)
def qapp():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def test_chat_url_normalization():
    from wondershot.aiclient import chat_url
    assert chat_url("https://api.openai.com") == \
        "https://api.openai.com/v1/chat/completions"
    assert chat_url("http://localhost:11434/") == \
        "http://localhost:11434/v1/chat/completions"
    assert chat_url("http://localhost:11434/v1") == \
        "http://localhost:11434/v1/chat/completions"
    assert chat_url("https://x.example/v1/chat/completions") == \
        "https://x.example/v1/chat/completions"


def test_build_request_text_only():
    from wondershot.aiclient import build_request
    url, headers, body = build_request(
        "https://api.openai.com", "sk-k", "gpt-4o-mini", "hello")
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-k"
    assert headers["Content-Type"] == "application/json"
    payload = json.loads(body)
    assert payload["model"] == "gpt-4o-mini"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]


def test_build_request_no_key_omits_auth():
    from wondershot.aiclient import build_request
    _, headers, _ = build_request("http://localhost:11434", "", "llava", "hi")
    assert "Authorization" not in headers


def test_build_request_with_image():
    from PySide6.QtGui import QColor, QImage
    from wondershot.aiclient import build_request
    img = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    _, _, body = build_request("http://x", "", "llava", "what is this?",
                               image=img)
    content = json.loads(body)["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "what is this?"}
    data_url = content[1]["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    png = base64.b64decode(data_url.split(",", 1)[1])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_parse_response_extracts_content():
    from wondershot.aiclient import parse_response
    canned = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant",
                                 "content": "the answer"}}],
        "usage": {"total_tokens": 5},
    }).encode()
    assert parse_response(canned) == "the answer"


def test_parse_response_surfaces_api_error():
    from wondershot.aiclient import parse_response
    canned = json.dumps({"error": {"message": "invalid model",
                                   "type": "invalid_request_error"}}).encode()
    with pytest.raises(OSError, match="invalid model"):
        parse_response(canned)


def test_parse_response_rejects_garbage_shape():
    from wondershot.aiclient import parse_response
    with pytest.raises(OSError):
        parse_response(b'{"choices": []}')


def test_chat_round_trip_with_canned_http(monkeypatch):
    """chat() builds the request and parses the canned response —
    urlopen is replaced, no network."""
    import wondershot.aiclient as aiclient

    seen = {}

    class _Resp:
        def read(self):
            return json.dumps({"choices": [{"message": {
                "role": "assistant", "content": "ok"}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        seen["auth"] = req.get_header("Authorization")
        return _Resp()

    monkeypatch.setattr(aiclient.urllib.request, "urlopen", fake_urlopen)
    out = aiclient.chat("http://localhost:11434", "k1", "llava", "ping")
    assert out == "ok"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["body"]["model"] == "llava"
    assert seen["auth"] == "Bearer k1"


def test_chat_maps_http_error_to_oserror(monkeypatch):
    import io
    import urllib.error
    import wondershot.aiclient as aiclient

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {},
            io.BytesIO(json.dumps(
                {"error": {"message": "bad key"}}).encode()))

    monkeypatch.setattr(aiclient.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(OSError, match="HTTP 401.*bad key"):
        aiclient.chat("http://x", "k", "m", "p")


def test_ai_configured():
    from wondershot.aiclient import ai_configured

    class _S:
        ai_endpoint = ""
        ai_api_key = ""
        ai_model = ""

    s = _S()
    assert not ai_configured(s)
    s.ai_endpoint = "http://x"
    assert not ai_configured(s)          # model still missing
    s.ai_model = "llava"
    assert ai_configured(s)              # key optional (local servers)
