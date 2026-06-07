"""OpenAI-compatible chat client for AI features — stdlib HTTP only.

POST {endpoint}/v1/chat/completions with optional base64 PNG image
content (vision). Works against OpenAI, Ollama, LM Studio, llama.cpp
server, vLLM, etc. The API key is optional (local servers run without
one) and is stored in plaintext QSettings — same precedent as the
S3/Azure credentials in share.py.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from PySide6.QtCore import QBuffer, QIODevice, QObject, QRunnable, Signal


def chat_url(endpoint: str) -> str:
    """Normalize a user-entered base URL to .../v1/chat/completions."""
    base = endpoint.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/chat/completions"


def image_to_base64_png(image) -> str:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return base64.b64encode(bytes(buf.data())).decode()


def build_request(endpoint: str, api_key: str, model: str, prompt: str,
                  image=None, max_tokens: int = 1024):
    """(url, headers, body-bytes) for an OpenAI-style chat completion."""
    if image is not None:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {
                "url": "data:image/png;base64,"
                       + image_to_base64_png(image)}},
        ]
    else:
        content = prompt
    body = {"model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return chat_url(endpoint), headers, json.dumps(body).encode()


def parse_response(body: bytes | str) -> str:
    """Assistant message text out of a chat-completions response."""
    data = json.loads(body)
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise OSError(msg)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OSError("unexpected chat response shape") from e


def chat(endpoint: str, api_key: str, model: str, prompt: str,
         image=None, timeout: int = 120) -> str:
    """One blocking chat round-trip. Raises OSError on any failure."""
    url, headers, body = build_request(endpoint, api_key, model, prompt,
                                       image)
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_response(resp.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read()).get("error", {})
            detail = (err.get("message", "") if isinstance(err, dict)
                      else str(err))
        except (ValueError, AttributeError):
            pass
        raise OSError(f"AI request failed: HTTP {e.code}"
                      + (f" — {detail}" if detail else "")) from e
    except urllib.error.URLError as e:
        raise OSError(f"AI endpoint unreachable: {e.reason}") from e


def test_connection(endpoint: str, api_key: str, model: str) -> str:
    """Tiny text-only round-trip; returns the model's (trimmed) reply."""
    reply = chat(endpoint, api_key, model,
                 "Reply with the single word: ok", timeout=30)
    return reply.strip()


def ai_configured(settings) -> bool:
    """Endpoint + model are required; the key is optional (local LLMs)."""
    return bool(getattr(settings, "ai_endpoint", "")
                and getattr(settings, "ai_model", ""))


# -- background execution (mirror of share.ShareJob) -------------------------


class _AISignal(QObject):
    done = Signal(object, str)  # (result, error) — exactly one is meaningful


class AIJob(QRunnable):
    """Run `fn()` off the GUI thread; emitter.done fires on the GUI thread.

    Setting .cancel discards the outcome (the in-flight HTTP call itself
    is not aborted — it just gets dropped on completion), which is what a
    progress dialog's Cancel button needs.
    """

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel = False
        self.emitter = _AISignal()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001 — surface anything to the UI
            if not self.cancel:
                self.emitter.done.emit(None, str(e))
            return
        if not self.cancel:
            self.emitter.done.emit(result, "")
