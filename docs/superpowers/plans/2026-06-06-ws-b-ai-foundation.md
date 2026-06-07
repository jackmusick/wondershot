# WS-B: AI Foundation + Redaction + Background Remover

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Give Wondershot an AI layer — settings + a stdlib OpenAI-compatible chat client, an "AI Redact" editor action that pixelates sensitive text non-destructively, and a local-ONNX "Remove Background" editor action behind an optional `wondershot[ai-local]` extra.

**Architecture:** A new `wondershot/aiclient.py` speaks `/v1/chat/completions` over `urllib` (the exact idiom of `share.py`/`msgraph.py` — no new required deps) and provides a generic `AIJob(QRunnable)` mirroring `ShareJob` so all AI work runs off the GUI thread with a cancelable `QProgressDialog`. Redaction is split into pure, headless-testable pieces (`ocr.py` TSV parsing, `redact.py` span/bbox matching) with thin GUI glue in `editor.py` that adds `PixelateItem`s through the existing undo stack. Background removal lives in `wondershot/bgremove.py` behind import guards; the editor applies it via a new `SetBaseImageCommand` (FlattenCommand minus the annotation fold, so annotations survive).

**Tech Stack:** Python ≥3.10, PySide6, stdlib `urllib`/`json`/`base64`/`subprocess`/`shutil`, optional `tesseract` binary (runtime discovery), optional `rembg`+`onnxruntime` (pip extra). Tests: pytest, headless (`QT_QPA_PLATFORM=offscreen`), canned JSON / fake modules — no network, no GUI event loops.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `wondershot/settings.py` | Modify (append after `pin_on_top`, ~line 279) | `ai_endpoint` / `ai_api_key` / `ai_model` QSettings properties |
| `wondershot/aiclient.py` | Create | Endpoint normalization, base64 image content, request build, response parse, `chat()`, `test_connection()`, `ai_configured()`, generic `AIJob(QRunnable)` |
| `wondershot/ocr.py` | Create | `find_tesseract()` (shutil.which), TSV parsing to `Word` boxes, `ocr_words(QImage)` with graceful degradation |
| `wondershot/redact.py` | Create | Prompts, LLM-reply JSON extraction, span→OCR-box matching, normalized-bbox fallback parsing, `redact_regions()` orchestrator |
| `wondershot/bgremove.py` | Create | Import-guarded rembg wrapper: `available()`, `remove_background(QImage) -> QImage` (alpha-preserving) |
| `wondershot/settings_dialog.py` | Modify (tab insertion ~line 198; `apply()` ~line 591) | "AI" tab with endpoint/key/model fields + async Test-connection button |
| `wondershot/editor.py` | Modify (commands after `FlattenCommand` ~line 150; toolbar `_build_toolbar` ~line 441; new methods after `share` section ~line 552) | `SetBaseImageCommand`, "AI Redact" + "Remove BG" toolbar actions, job wiring, `apply_redact_regions()` |
| `pyproject.toml` | Modify | `[project.optional-dependencies] ai-local = ["rembg", "onnxruntime"]` |
| `tests/test_settings_ai.py` | Create | Settings property round-trip against a temp-file QSettings |
| `tests/test_aiclient.py` | Create | URL normalization, request construction (incl. base64 image), response parsing against canned JSON, HTTP error mapping, `AIJob` semantics |
| `tests/test_ocr.py` | Create | TSV parsing (pure), missing-tesseract degradation |
| `tests/test_redact.py` | Create | JSON extraction, span matching, bbox fallback parsing, orchestrator with fakes |
| `tests/test_bgremove.py` | Create | `available()` + `remove_background()` against a fake `rembg` module |
| `tests/test_editor_ai.py` | Create | `apply_redact_regions` adds undoable PixelateItems; `SetBaseImageCommand` undo/redo preserves annotations + alpha; BG action disabled without rembg |
| `tests/test_settings_dialog_ai.py` | Create | AI tab smoke + `apply()` writes the three settings |

**Gotchas for someone new to this codebase:**
- Tests run headless. GUI-touching tests need a `QApplication` (see `tests/test_editor.py` lines 1–16: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` BEFORE Qt imports, then a session-scoped `qapp` fixture). Pure-QImage tests only need `QGuiApplication` (see `tests/test_imageops.py`).
- `Settings.__init__` opens the real user config (`~/.config/wondershot/wondershot.conf`). Never instantiate it normally in tests — use `Settings.__new__(Settings)` and inject a temp-file `QSettings` (Task 1 shows how).
- `QSettings.value()` returns strings; existing int properties wrap in `int(...)`, bools compare against `(True, "true")`. Follow that exactly.
- `PixelateItem(base_provider, rect)` takes a zero-arg callable returning the base `QImage` — in the editor that is `lambda: self.base_image` (see `editor.py` `_apply_pixelate`, ~line 1099).
- `FlattenCommand` (editor.py ~line 128) removes all annotations on redo — that is correct for crop but WRONG for background removal. Task 8 adds `SetBaseImageCommand` that swaps only the base image.
- `editor._act(text, icon, shortcut, checkable)` is the action factory (~line 401). The toolbar is built in `_build_toolbar` (~line 408); the share button + spacer block starts at ~line 465 — insert AI actions before the spacer.
- All worker results must cross to the GUI thread via a `Signal` on a `QObject` member (`emitter`), exactly like `ShareJob`/`_ShareSignal` in `share.py` lines 183–203.
- Run all test commands from the repo root of the worktree. Full suite: `python -m pytest tests/ -q`.

---

## Task 1: Settings keys `ai_endpoint` / `ai_api_key` / `ai_model`

**Files**
- Modify: `wondershot/settings.py` (append properties at end of class, after `pin_on_top` setter, ~line 279)
- Test: `tests/test_settings_ai.py` (create)

- [x] Write the failing test:

```python
# tests/test_settings_ai.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    """A Settings whose backing store is a throwaway ini file.

    Settings.__init__ opens the real user config (and runs a migration),
    so bypass it and inject a temp QSettings instead.
    """
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_ai_settings_default_empty(tmp_path):
    s = make_settings(tmp_path)
    assert s.ai_endpoint == ""
    assert s.ai_api_key == ""
    assert s.ai_model == ""


def test_ai_settings_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.ai_endpoint = "http://localhost:11434"
    s.ai_api_key = "sk-test"
    s.ai_model = "llava"
    assert s.ai_endpoint == "http://localhost:11434"
    assert s.ai_api_key == "sk-test"
    assert s.ai_model == "llava"
```

- [x] Run it and confirm the failure: `python -m pytest tests/test_settings_ai.py -q` — expect `AttributeError: 'Settings' object has no attribute 'ai_endpoint'`.
- [x] Implement: in `wondershot/settings.py`, append at the end of the `Settings` class (after the `pin_on_top` setter):

```python
    # -- AI (OpenAI-compatible chat endpoint) -------------------------------
    # NOTE: the API key is stored in plaintext QSettings, same as the
    # S3/Azure credentials; the AI tab warns about this.

    @property
    def ai_endpoint(self) -> str:
        """Base URL, e.g. https://api.openai.com or http://localhost:11434."""
        return self._s.value("ai_endpoint", "")

    @ai_endpoint.setter
    def ai_endpoint(self, value: str) -> None:
        self._s.setValue("ai_endpoint", value)

    @property
    def ai_api_key(self) -> str:
        return self._s.value("ai_api_key", "")

    @ai_api_key.setter
    def ai_api_key(self, value: str) -> None:
        self._s.setValue("ai_api_key", value)

    @property
    def ai_model(self) -> str:
        return self._s.value("ai_model", "")

    @ai_model.setter
    def ai_model(self, value: str) -> None:
        self._s.setValue("ai_model", value)
```

- [x] Run tests: `python -m pytest tests/test_settings_ai.py -q` — expect 2 passed.
- [x] Commit: `git add wondershot/settings.py tests/test_settings_ai.py && git commit -m "WS-B: ai_endpoint/ai_api_key/ai_model settings keys"`

---

## Task 2: `aiclient.py` — request construction + response parsing

**Files**
- Create: `wondershot/aiclient.py`
- Test: `tests/test_aiclient.py` (create)

- [x] Write the failing tests (pure functions first — no network, no job yet):

```python
# tests/test_aiclient.py
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
```

- [x] Run them and confirm the failure: `python -m pytest tests/test_aiclient.py -q` — expect `ModuleNotFoundError: No module named 'wondershot.aiclient'`.
- [x] Implement `wondershot/aiclient.py`:

```python
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
```

- [x] Run tests: `python -m pytest tests/test_aiclient.py -q` — expect 10 passed.
- [x] Commit: `git add wondershot/aiclient.py tests/test_aiclient.py && git commit -m "WS-B: aiclient — stdlib OpenAI-compatible chat with vision content"`

---

## Task 3: `AIJob` — generic cancelable QRunnable (ShareJob pattern)

**Files**
- Modify: `wondershot/aiclient.py` (append at end of file)
- Test: `tests/test_aiclient.py` (append)

- [ ] Write the failing tests (append to `tests/test_aiclient.py`):

```python
def test_aijob_emits_result(qapp):
    from wondershot.aiclient import AIJob
    got = []
    job = AIJob(lambda: 42)
    job.emitter.done.connect(lambda result, error: got.append((result, error)))
    job.run()  # synchronous call — direct connection delivers immediately
    assert got == [(42, "")]


def test_aijob_emits_error_string(qapp):
    from wondershot.aiclient import AIJob
    got = []
    job = AIJob(lambda: (_ for _ in ()).throw(OSError("boom")))
    job.emitter.done.connect(lambda result, error: got.append((result, error)))
    job.run()
    assert got == [(None, "boom")]


def test_aijob_cancel_suppresses_emit(qapp):
    from wondershot.aiclient import AIJob
    got = []
    job = AIJob(lambda: 1)
    job.emitter.done.connect(lambda result, error: got.append((result, error)))
    job.cancel = True
    job.run()
    assert got == []
```

- [ ] Run and confirm failure: `python -m pytest tests/test_aiclient.py -q` — expect `ImportError: cannot import name 'AIJob'`.
- [ ] Implement — append to `wondershot/aiclient.py`:

```python
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
```

- [ ] Run tests: `python -m pytest tests/test_aiclient.py -q` — expect 13 passed.
- [ ] Commit: `git add wondershot/aiclient.py tests/test_aiclient.py && git commit -m "WS-B: AIJob — cancelable QRunnable mirroring ShareJob"`

---

## Task 4: "AI" tab in the settings dialog with Test-connection

**Files**
- Modify: `wondershot/settings_dialog.py` — add tab after line 198 (`tabs.addTab(self._build_share_tab(), "Sharing")`), new methods after `_build_share_tab` (~line 267), three writes in `apply()` (~line 611)
- Test: `tests/test_settings_dialog_ai.py` (create)

- [ ] Write the failing test:

```python
# tests/test_settings_dialog_ai.py
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    """Plain attribute bag covering everything SettingsDialog reads."""

    def __init__(self, tmp):
        self.library_dir = str(tmp)
        self.extra_dirs = []
        self.backend = "auto"
        self.camera_device = ""
        self.mic_device = ""
        self.mic_enabled = True
        self.noise_suppression = True
        self.copy_after_capture = True
        self.show_gallery_after_capture = True
        self.share_provider = ""
        self.share_expiry_days = 7
        self.s3_endpoint = self.s3_region = self.s3_bucket = ""
        self.s3_access_key = self.s3_secret_key = ""
        self.azure_account = self.azure_container = self.azure_key = ""
        self.graph_client_id = ""
        self.graph_drive_id = ""
        self.graph_drive_label = ""
        self.ai_endpoint = "http://localhost:11434"
        self.ai_api_key = ""
        self.ai_model = "llava"


def test_ai_tab_fields_and_apply(qapp, tmp_path, monkeypatch):
    # keep msgraph token lookups away from the real home dir
    monkeypatch.setenv("WONDERSHOT_DATA_DIR", str(tmp_path))
    from wondershot.settings_dialog import SettingsDialog
    s = _FakeSettings(tmp_path)
    dlg = SettingsDialog(s)
    assert dlg.ai_endpoint.text() == "http://localhost:11434"
    assert dlg.ai_model.text() == "llava"
    dlg.ai_endpoint.setText("https://api.openai.com ")
    dlg.ai_api_key.setText(" sk-new ")
    dlg.ai_model.setText("gpt-4o-mini")
    dlg.apply()
    assert s.ai_endpoint == "https://api.openai.com"
    assert s.ai_api_key == "sk-new"
    assert s.ai_model == "gpt-4o-mini"


def test_ai_test_button_requires_endpoint_and_model(qapp, tmp_path,
                                                    monkeypatch):
    monkeypatch.setenv("WONDERSHOT_DATA_DIR", str(tmp_path))
    from wondershot.settings_dialog import SettingsDialog
    s = _FakeSettings(tmp_path)
    s.ai_endpoint = ""
    s.ai_model = ""
    dlg = SettingsDialog(s)
    dlg._ai_test()  # must not start a job / touch the network
    assert "endpoint" in dlg.ai_test_status.text()
```

- [ ] Run and confirm failure: `python -m pytest tests/test_settings_dialog_ai.py -q` — expect `AttributeError: 'SettingsDialog' object has no attribute 'ai_endpoint'`.
- [ ] Implement. In `wondershot/settings_dialog.py`, directly after the line `tabs.addTab(self._build_share_tab(), "Sharing")` (~line 198) add:

```python
        tabs.addTab(self._build_ai_tab(), "AI")
```

  Then add these methods after `_build_share_tab` (i.e., just before the `# -- OneDrive / SharePoint` section, ~line 269):

```python
    # -- AI (OpenAI-compatible endpoint) -----------------------------------

    def _build_ai_tab(self) -> QWidget:
        s = self.settings
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()

        self.ai_endpoint = QLineEdit(s.ai_endpoint)
        self.ai_endpoint.setPlaceholderText(
            "https://api.openai.com  or  http://localhost:11434")
        form.addRow("Endpoint:", self.ai_endpoint)

        self.ai_api_key = QLineEdit(s.ai_api_key)
        self.ai_api_key.setEchoMode(QLineEdit.Password)
        self.ai_api_key.setPlaceholderText("optional for local servers")
        form.addRow("API key:", self.ai_api_key)

        self.ai_model = QLineEdit(s.ai_model)
        self.ai_model.setPlaceholderText("e.g. gpt-4o-mini, llava")
        form.addRow("Model:", self.ai_model)
        v.addLayout(form)

        test_row = QHBoxLayout()
        self.ai_test_btn = QPushButton("Test connection")
        self.ai_test_btn.clicked.connect(self._ai_test)
        self.ai_test_status = QLabel("")
        test_row.addWidget(self.ai_test_btn)
        test_row.addWidget(self.ai_test_status, 1)
        v.addLayout(test_row)

        hint = QLabel(
            "Any OpenAI-compatible chat endpoint works (OpenAI, Ollama, "
            "LM Studio, llama.cpp server). AI Redact needs a model that "
            "accepts images. The key is stored unencrypted in "
            "Wondershot's config file — use a scoped key.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        v.addWidget(hint)
        v.addStretch(1)
        return w

    def _ai_test(self) -> None:
        from PySide6.QtCore import QThreadPool
        from . import aiclient
        endpoint = self.ai_endpoint.text().strip()
        model = self.ai_model.text().strip()
        if not endpoint or not model:
            self.ai_test_status.setText("enter an endpoint and a model first")
            return
        key = self.ai_api_key.text().strip()
        self.ai_test_btn.setEnabled(False)
        self.ai_test_status.setText("testing…")
        job = aiclient.AIJob(
            lambda: aiclient.test_connection(endpoint, key, model))
        job.emitter.done.connect(self._ai_test_done)
        self._ai_test_job = job  # keep the signal emitter alive
        QThreadPool.globalInstance().start(job)

    def _ai_test_done(self, reply, error: str) -> None:
        self.ai_test_btn.setEnabled(True)
        if error:
            self.ai_test_status.setText(f"<i>{error}</i>")
        else:
            self.ai_test_status.setText(f"OK — replied: {str(reply)[:40]}")
```

  Finally, in `apply()` add these three lines just before `return moved` (~line 612):

```python
        self.settings.ai_endpoint = self.ai_endpoint.text().strip()
        self.settings.ai_api_key = self.ai_api_key.text().strip()
        self.settings.ai_model = self.ai_model.text().strip()
```

- [ ] Run tests: `python -m pytest tests/test_settings_dialog_ai.py -q` — expect 2 passed. Also run `python -m pytest tests/ -q` to confirm nothing else broke.
- [ ] Commit: `git add wondershot/settings_dialog.py tests/test_settings_dialog_ai.py && git commit -m "WS-B: AI settings tab with async test-connection"`

---

## Task 5: `ocr.py` — tesseract discovery + TSV word boxes

**Files**
- Create: `wondershot/ocr.py`
- Test: `tests/test_ocr.py` (create)

- [ ] Write the failing tests:

```python
# tests/test_ocr.py
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
```

- [ ] Run and confirm failure: `python -m pytest tests/test_ocr.py -q` — expect `ModuleNotFoundError: No module named 'wondershot.ocr'`.
- [ ] Implement `wondershot/ocr.py`:

```python
"""Optional local OCR via the tesseract binary — word boxes for AI redact.

Discovery uses shutil.which (no hardcoded paths, per WS-E constraints).
Everything degrades gracefully: no tesseract, OCR failure, or garbage
output all yield an empty word list and the caller falls back to the
LLM-bbox path.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int
    conf: float


def find_tesseract() -> str | None:
    return shutil.which("tesseract")


def parse_tsv(tsv: str) -> list[Word]:
    """Word boxes out of `tesseract ... tsv` output (level-5 rows)."""
    lines = tsv.splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    idx = {name: i for i, name in enumerate(header)}
    required = {"left", "top", "width", "height", "conf", "text"}
    if not required <= idx.keys():
        return []
    words: list[Word] = []
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) != len(header):
            continue
        text = cols[idx["text"]].strip()
        if not text:
            continue
        try:
            conf = float(cols[idx["conf"]])
            if conf < 0:  # -1 marks structural (non-word) rows
                continue
            words.append(Word(
                text=text,
                x=int(cols[idx["left"]]), y=int(cols[idx["top"]]),
                w=int(cols[idx["width"]]), h=int(cols[idx["height"]]),
                conf=conf))
        except ValueError:
            continue
    return words


def ocr_words(image, binary: str | None = None) -> list[Word]:
    """Run tesseract over a QImage; [] when unavailable or failing."""
    binary = binary or find_tesseract()
    if not binary:
        return []
    from PySide6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    try:
        out = subprocess.run([binary, "stdin", "stdout", "tsv"],
                             input=bytes(buf.data()),
                             capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    return parse_tsv(out.stdout.decode("utf-8", "replace"))
```

- [ ] Run tests: `python -m pytest tests/test_ocr.py -q` — expect 4 passed.
- [ ] Commit: `git add wondershot/ocr.py tests/test_ocr.py && git commit -m "WS-B: optional tesseract OCR helper with graceful degradation"`

---

## Task 6: `redact.py` — prompts, span matching, bbox fallback, orchestrator

**Files**
- Create: `wondershot/redact.py`
- Test: `tests/test_redact.py` (create)

- [ ] Write the failing tests:

```python
# tests/test_redact.py
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
```

- [ ] Run and confirm failure: `python -m pytest tests/test_redact.py -q` — expect `ModuleNotFoundError: No module named 'wondershot.redact'`.
- [ ] Implement `wondershot/redact.py`:

```python
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


def extract_json(reply: str) -> str:
    """Models love to wrap JSON in ``` fences and chatter — unwrap it."""
    text = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text


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
```

- [ ] Run tests: `python -m pytest tests/test_redact.py -q` — expect 9 passed.
- [ ] Commit: `git add wondershot/redact.py tests/test_redact.py && git commit -m "WS-B: redaction pipeline — OCR span matching + bbox fallback"`

---

## Task 7: Editor "AI Redact" action — non-destructive PixelateItems

**Files**
- Modify: `wondershot/editor.py` — toolbar insertion in `_build_toolbar` before the spacer block (~line 465), new methods after `_share_done` (~line 552)
- Test: `tests/test_editor_ai.py` (create)

- [ ] Write the failing test:

```python
# tests/test_editor_ai.py
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_editor(qapp, w=400, h=300):
    from wondershot.editor import EditorWindow
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("white"))
    return EditorWindow(image=img)


def test_apply_redact_regions_adds_pixelate_items(qapp):
    from wondershot.items import PixelateItem
    ed = make_editor(qapp)
    n = ed.apply_redact_regions([QRect(10, 10, 100, 20),
                                 QRect(50, 100, 80, 16)])
    assert n == 2
    patches = [i for i in ed.scene.items() if isinstance(i, PixelateItem)]
    assert len(patches) == 2
    # non-destructive: base image untouched, single undo removes them all
    assert ed.base_image.pixelColor(15, 15) == QColor("white")
    ed.undo_stack.undo()
    patches = [i for i in ed.scene.items() if isinstance(i, PixelateItem)]
    assert patches == []


def test_apply_redact_regions_clamps_and_skips_tiny(qapp):
    from wondershot.items import PixelateItem
    ed = make_editor(qapp, 400, 300)
    n = ed.apply_redact_regions([
        QRect(390, 290, 100, 100),   # mostly off-canvas -> clamped, kept
        QRect(0, 0, 2, 2),           # degenerate -> skipped
        QRect(500, 500, 50, 50),     # fully off-canvas -> skipped
    ])
    assert n == 1
    patches = [i for i in ed.scene.items() if isinstance(i, PixelateItem)]
    assert len(patches) == 1
    assert patches[0].rect().right() <= 400


def test_redact_action_exists_on_toolbar(qapp):
    ed = make_editor(qapp)
    assert ed.redact_action.text() == "AI Redact"
```

- [ ] Run and confirm failure: `python -m pytest tests/test_editor_ai.py -q` — expect `AttributeError: 'EditorWindow' object has no attribute 'apply_redact_regions'`.
- [ ] Implement. In `wondershot/editor.py` `_build_toolbar`, insert immediately BEFORE the `from PySide6.QtWidgets import QMenu, QSizePolicy, QToolButton, QWidget` / spacer block (~line 465):

```python
        tb.addSeparator()
        self.redact_action = self._act("AI Redact", "view-private")
        self.redact_action.setToolTip(
            "Find and pixelate sensitive text (Settings → AI)")
        self.redact_action.triggered.connect(self.ai_redact)
        tb.addAction(self.redact_action)
```

  Then add these methods after `_share_done` (~line 552), before `_build_statusbar`:

```python
    # -- AI actions -----------------------------------------------------------

    def _start_ai_job(self, fn, label: str, on_done) -> None:
        """Run `fn` on the thread pool behind a cancelable progress dialog."""
        from PySide6.QtCore import QThreadPool
        from PySide6.QtWidgets import QProgressDialog
        from .aiclient import AIJob
        job = AIJob(fn)
        dlg = QProgressDialog(label, "Cancel", 0, 0, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.canceled.connect(lambda: setattr(job, "cancel", True))
        job.emitter.done.connect(
            lambda result, error: (dlg.close(), on_done(result, error)))
        self._ai_job = job  # keep the signal emitter alive
        QThreadPool.globalInstance().start(job)

    def ai_redact(self) -> None:
        from .aiclient import ai_configured
        from . import redact
        if not (self.settings and ai_configured(self.settings)):
            self.statusBar().showMessage(
                "Configure an AI endpoint in Settings → AI first", 6000)
            return
        s = self.settings
        image = self.base_image.copy()  # snapshot off the GUI thread's state
        endpoint, key, model = s.ai_endpoint, s.ai_api_key, s.ai_model
        self._start_ai_job(
            lambda: redact.redact_regions(image, endpoint, key, model),
            "Finding sensitive text…", self._redact_done)

    def _redact_done(self, rects, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Wondershot",
                                f"AI Redact failed: {error}")
            return
        self.apply_redact_regions(rects or [])

    def apply_redact_regions(self, rects) -> int:
        """Add a PixelateItem per region — non-destructive, one undo step."""
        img_rect = QRect(0, 0, self.base_image.width(),
                         self.base_image.height())
        clamped = []
        for r in rects:
            c = QRect(r).intersected(img_rect)
            if c.width() >= 4 and c.height() >= 4:
                clamped.append(c)
        if clamped:
            self.undo_stack.beginMacro("AI redact")
            try:
                for c in clamped:
                    item = PixelateItem(lambda: self.base_image, QRectF(c))
                    self.undo_stack.push(
                        AddItemCommand(self, item, "AI redact"))
            finally:
                self.undo_stack.endMacro()
        msg = (f"AI Redact: pixelated {len(clamped)} region(s) — review, "
               "adjust, then save" if clamped
               else "AI Redact: nothing sensitive found")
        self.statusBar().showMessage(msg, 8000)
        return len(clamped)
```

  Note: `ai_redact`/`_start_ai_job`/`_redact_done` are GUI glue (thread pool + modal dialog) and are exercised only via the headless-safe `apply_redact_regions` test — stated explicitly here; do not try to unit-test the progress dialog.
- [ ] Run tests: `python -m pytest tests/test_editor_ai.py tests/test_editor.py -q` — expect all passed (3 new + 17 existing).
- [ ] Commit: `git add wondershot/editor.py tests/test_editor_ai.py && git commit -m "WS-B: AI Redact editor action — non-destructive PixelateItems"`

---

## Task 8: `wondershot[ai-local]` extra + `bgremove.py`

**Files**
- Modify: `pyproject.toml` (add optional-dependencies table after `[project.scripts]`)
- Create: `wondershot/bgremove.py`
- Test: `tests/test_bgremove.py` (create)

- [ ] Write the failing tests:

```python
# tests/test_bgremove.py
import importlib.machinery
import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def qapp():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def _png_bytes(w, h, color, alpha=255):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format_ARGB32)
    c = QColor(color)
    c.setAlpha(alpha)
    img.fill(c)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


@pytest.fixture
def fake_rembg(monkeypatch):
    """A stand-in rembg whose remove() returns a half-transparent PNG."""
    mod = types.ModuleType("rembg")
    mod.__spec__ = importlib.machinery.ModuleSpec("rembg", None)
    mod.calls = []

    def remove(data: bytes) -> bytes:
        mod.calls.append(data[:8])
        return _png_bytes(4, 4, "blue", alpha=128)

    mod.remove = remove
    monkeypatch.setitem(sys.modules, "rembg", mod)
    return mod


def test_available_false_without_rembg(monkeypatch):
    import wondershot.bgremove as bgremove
    monkeypatch.setitem(sys.modules, "rembg", None)  # forces ImportError path
    monkeypatch.setattr(bgremove.importlib.util, "find_spec",
                        lambda name: None)
    assert bgremove.available() is False


def test_remove_background_raises_without_rembg(monkeypatch):
    import wondershot.bgremove as bgremove
    from PySide6.QtGui import QColor, QImage
    monkeypatch.setattr(bgremove.importlib.util, "find_spec",
                        lambda name: None)
    img = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    with pytest.raises(OSError, match="ai-local"):
        bgremove.remove_background(img)


def test_remove_background_with_fake_rembg(fake_rembg):
    import wondershot.bgremove as bgremove
    from PySide6.QtGui import QColor, QImage
    assert bgremove.available() is True
    img = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("red"))
    out = bgremove.remove_background(img)
    # rembg was fed PNG bytes of our image
    assert fake_rembg.calls == [b"\x89PNG\r\n\x1a\n"]
    # output preserves alpha in premultiplied format
    assert out.format() == QImage.Format_ARGB32_Premultiplied
    assert out.hasAlphaChannel()
    assert 100 < out.pixelColor(1, 1).alpha() < 160   # the fake's alpha=128
```

- [ ] Run and confirm failure: `python -m pytest tests/test_bgremove.py -q` — expect `ModuleNotFoundError: No module named 'wondershot.bgremove'`.
- [ ] Implement `wondershot/bgremove.py`:

```python
"""Local background removal via rembg/U²-Net ONNX — optional extra.

Installed with `pip install wondershot[ai-local]`. Per the design spec,
background removal is ALWAYS local ONNX, never the LLM endpoint (chat
APIs don't return alpha mattes). All rembg imports are guarded so the
core app never requires onnxruntime.
"""

from __future__ import annotations

import importlib.util


def available() -> bool:
    return importlib.util.find_spec("rembg") is not None


def remove_background(image):
    """QImage -> QImage with the background made transparent.

    Round-trips through PNG bytes (rembg's native interface); the result
    comes back ARGB32_Premultiplied so the editor's checkerboard mat and
    flatten path handle the alpha untouched.
    """
    if not available():
        raise OSError("Background removal needs the optional extra: "
                      "pip install wondershot[ai-local]")
    import rembg
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    out_bytes = rembg.remove(bytes(buf.data()))
    out = QImage.fromData(out_bytes, "PNG")
    if out.isNull():
        raise OSError("background removal produced no image")
    return out.convertToFormat(QImage.Format_ARGB32_Premultiplied)
```

- [ ] Add the extra to `pyproject.toml` — insert after the `[project.scripts]` table:

```toml
[project.optional-dependencies]
ai-local = ["rembg>=2.0", "onnxruntime>=1.16"]
```

- [ ] Run tests: `python -m pytest tests/test_bgremove.py -q` — expect 3 passed. Sanity-check packaging metadata parses: `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))" && echo OK` — expect `OK`.
- [ ] Commit: `git add wondershot/bgremove.py pyproject.toml tests/test_bgremove.py && git commit -m "WS-B: bgremove — import-guarded rembg wrapper + ai-local extra"`

---

## Task 9: Editor "Remove Background" — `SetBaseImageCommand` + action

**Files**
- Modify: `wondershot/editor.py` — new command class after `FlattenCommand` (insert after line ~150, before `GripCommand`); toolbar action next to the AI Redact action added in Task 7; methods after `apply_redact_regions`
- Test: `tests/test_editor_ai.py` (append)

- [ ] Write the failing tests (append to `tests/test_editor_ai.py`):

```python
def test_set_base_image_command_swaps_and_keeps_annotations(qapp):
    from PySide6.QtCore import QRectF
    from wondershot.editor import SetBaseImageCommand
    from wondershot.items import RectItem
    ed = make_editor(qapp, 400, 300)
    note = RectItem(QRectF(10, 10, 50, 50), QColor("red"), 4)
    ed.scene.addItem(note)
    new = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
    new.fill(QColor(0, 0, 0, 0))  # fully transparent (alpha preserved)
    ed.undo_stack.push(SetBaseImageCommand(ed, new, "remove background"))
    assert ed.base_image.pixelColor(5, 5).alpha() == 0
    assert note.scene() is ed.scene          # annotations survive (≠ Flatten)
    ed.undo_stack.undo()
    assert ed.base_image.pixelColor(5, 5) == QColor("white")
    assert note.scene() is ed.scene


def test_remove_bg_action_disabled_without_rembg(qapp, monkeypatch):
    import wondershot.bgremove as bgremove
    monkeypatch.setattr(bgremove, "available", lambda: False)
    ed = make_editor(qapp)
    assert not ed.bg_action.isEnabled()
    assert "ai-local" in ed.bg_action.toolTip()


def test_remove_bg_action_enabled_with_rembg(qapp, monkeypatch):
    import wondershot.bgremove as bgremove
    monkeypatch.setattr(bgremove, "available", lambda: True)
    ed = make_editor(qapp)
    assert ed.bg_action.isEnabled()


def test_bg_done_pushes_undoable_swap(qapp):
    ed = make_editor(qapp, 400, 300)
    new = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
    new.fill(QColor(0, 255, 0, 255))
    ed._bg_done(new, "")
    assert ed.base_image.pixelColor(5, 5) == QColor(0, 255, 0)
    ed.undo_stack.undo()
    assert ed.base_image.pixelColor(5, 5) == QColor("white")
```

- [ ] Run and confirm failure: `python -m pytest tests/test_editor_ai.py -q` — expect `ImportError: cannot import name 'SetBaseImageCommand'`.
- [ ] Implement. In `wondershot/editor.py`, add after the `FlattenCommand` class (after its `undo`, ~line 150):

```python
class SetBaseImageCommand(QUndoCommand):
    """Swap only the base image, keeping annotations on the scene.

    FlattenCommand minus the annotation fold — Remove Background changes
    the pixels underneath but must not eat the user's markup.
    """

    def __init__(self, editor: "EditorWindow", new_image: QImage, text: str):
        super().__init__(text)
        self.editor = editor
        self.old_image = editor.base_image
        self.new_image = new_image

    def redo(self):
        self.editor.set_base_image(self.new_image)

    def undo(self):
        self.editor.set_base_image(self.old_image)
```

  In `_build_toolbar`, extend the AI block added in Task 7 (right after `tb.addAction(self.redact_action)`):

```python
        from . import bgremove
        self.bg_action = self._act("Remove BG", "edit-clear-all")
        self.bg_action.triggered.connect(self.remove_background)
        tb.addAction(self.bg_action)
        if not bgremove.available():
            self.bg_action.setEnabled(False)
            self.bg_action.setToolTip(
                "Needs the optional extra: pip install wondershot[ai-local]")
        else:
            self.bg_action.setToolTip(
                "Make the background transparent (local ONNX)")
```

  Gotcha: `_act` creates the QAction with `QIcon.fromTheme` — a missing theme icon is fine (text-under-icon style still shows the label). Also note `tb.addAction(a)` does NOT auto-disable on missing icons; the explicit `setEnabled(False)` above is the only gate.

  Add the methods after `apply_redact_regions` (from Task 7):

```python
    def remove_background(self) -> None:
        from . import bgremove
        if not bgremove.available():
            return  # action should be disabled anyway
        image = self.base_image.copy()
        self._start_ai_job(lambda: bgremove.remove_background(image),
                           "Removing background…", self._bg_done)

    def _bg_done(self, image, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Wondershot",
                                f"Remove Background failed: {error}")
            return
        self.undo_stack.push(
            SetBaseImageCommand(self, image, "remove background"))
        self.statusBar().showMessage(
            "Background removed — save as PNG to keep transparency", 8000)
```

  Note: `remove_background()` itself (thread-pool + progress dialog) is GUI glue covered indirectly; `_bg_done` and `SetBaseImageCommand` carry the logic and are unit-tested above.
- [ ] Run tests: `python -m pytest tests/test_editor_ai.py tests/test_editor.py -q` — expect all passed (7 in test_editor_ai + 17 existing).
- [ ] Run the FULL suite to close out the workstream: `python -m pytest tests/ -q` — expect 0 failures.
- [ ] Commit: `git add wondershot/editor.py tests/test_editor_ai.py && git commit -m "WS-B: Remove Background editor action with SetBaseImageCommand undo"`

---

## Verification (after all tasks)

- [ ] `python -m pytest tests/ -q` — entire suite green, headless.
- [ ] `python -c "import wondershot.aiclient, wondershot.ocr, wondershot.redact, wondershot.bgremove; print('imports ok')"` — no rembg/onnx required for core imports.
- [ ] Manual smoke (optional, needs a display + an Ollama/OpenAI endpoint): `wondershot`, open Settings → AI, fill endpoint/model, Test connection; open an image in the editor, hit AI Redact, confirm pixelate regions appear selected/adjustable and a single Ctrl+Z removes them; Remove BG stays greyed out with the install tooltip unless `pip install -e .[ai-local]` was run.
