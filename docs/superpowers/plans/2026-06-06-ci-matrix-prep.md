# CI Matrix + Cross-Platform Prep (WS-E prep track)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a 3-OS GitHub Actions CI matrix (install + import smoke + pytest), extract a `HotkeyBackend` platform seam from `hotkey.py`, and replace the hardcoded `~/.cache` / `~/.local/share` paths with cross-platform equivalents — so WS-E's Windows/macOS work starts from honest green CI.

**Architecture:** Wondershot is a PySide6-only package (`wondershot/`) whose tests already run headless via `QT_QPA_PLATFORM=offscreen`. This track adds no features: it guards the two Linux-flavored test spots so Windows/macOS jobs skip them honestly, splits `hotkey.py` (56 lines) into a `HotkeyBackend` base + the existing KGlobalAccel impl + a platform factory, and routes two hardcoded XDG paths through `QStandardPaths` (record.py) and a stdlib platform switch (msgraph.py, which is deliberately stdlib-only).

**Tech Stack:** Python >=3.10, PySide6 >=6.6 (only dep), pytest, GitHub Actions.

**Execution environment:** A git worktree branched from `main`. The repo's venv recipe is `python -m venv .venv && .venv/bin/pip install -e . pytest` (from README.md). All test commands below assume `.venv/bin/pytest`; create the venv first if the worktree doesn't have one. Run everything with absolute paths from the worktree root.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `tests/test_record.py` | Modify (top of file, lines 1–10) | Module-level `skipif` on Windows: tests spawn POSIX `true`/`sleep` and rely on SIGINT semantics |
| `tests/test_msgraph.py` | Modify (line 13) | Guard the `0o600` permission assertion to POSIX (chmod is a no-op for mode bits on Windows) |
| `wondershot/record.py` | Modify (lines ~280–285 inside `_launch_gst`) | Recorder log dir via `QStandardPaths.GenericCacheLocation` instead of `XDG_CACHE_HOME`/`~/.cache` |
| `tests/test_record.py` | Modify (append) | Test pinning `record.log_dir()` to the standard cache location |
| `wondershot/msgraph.py` | Modify (lines ~77–82, `token_path`) | Stdlib platform-aware data dir fallback (`LOCALAPPDATA` / `~/Library/Application Support` / `XDG_DATA_HOME`), keeping the `WONDERSHOT_DATA_DIR` override |
| `tests/test_msgraph.py` | Modify (append) | Tests for the per-platform `token_path` fallback |
| `wondershot/hotkey.py` | Rewrite (whole file, 56 lines) | `HotkeyBackend` base (QObject, `pressed` signal, `register()`), `KGlobalAccelBackend` (existing impl, unchanged behavior), `NullHotkeyBackend`, `create_hotkey_backend()` factory |
| `wondershot/app.py` | Modify (line 17 import; lines 96–98 usage) | Use the factory instead of `HotkeyManager` directly |
| `tests/test_hotkey.py` | Create | Factory platform selection + null backend behavior |
| `.github/workflows/ci.yml` | Create | 3-OS × 2-Python matrix: apt Qt deps on Linux, `pip install -e .`, import smoke, pytest, all under `QT_QPA_PLATFORM=offscreen` |

**Out of scope (audited, deliberately left alone):**
- `wondershot/cli.py:92` (`install_desktop`) — installs `.desktop` files into XDG dirs; that *is* the Linux desktop spec, not a portability bug.
- `wondershot/settings.py:12` and `wondershot/editor.py:1150` — `~/Pictures` only as fallback *after* `QStandardPaths.PicturesLocation` returns empty; already correct.
- `wondershot/gallery.py` / `selftest.py` `tempfile` usage — `tempfile` is already cross-platform.
- No new hotkey backends (spec says shape only).
- **Spec WS-E prep constraints 2 & 4 (ffmpeg helper, binary discovery) are owned by the
  other session tracks**: WS-A's plan creates `wondershot/ffmpegutil.py` (ffmpeg PATH
  discovery + single `run_ffmpeg()` + migrates existing call sites) and WS-B's plan
  creates `wondershot/ocr.py` with `shutil.which` tesseract discovery. Do NOT create a
  competing `tools.py` here — it would merge-conflict with those tracks.

---

## Task 1: Cross-platform pytest guards

The recorder tests (`tests/test_record.py`) spawn `subprocess.Popen(["true"])` and `["sleep", "10"]` and exercise `ScreenRecorder.stop()`, which sends `signal.SIGINT` for gst EOS (`wondershot/record.py:126`). None of that exists on Windows, and the recorder itself is Linux-only (portal → PipeWire → gst). `tests/test_msgraph.py:13` asserts the token file is mode `0o600`, which `os.chmod` cannot produce on Windows (mode bits other than read-only are ignored). Guard both honestly: skip with a reason, don't xfail.

**Files:**
- Modify: `tests/test_record.py` (lines 1–10, the import block)
- Modify: `tests/test_msgraph.py` (line 13)
- Test: these files are themselves the deliverable; verification = full suite still runs un-skipped on Linux

**Steps:**

- [x] **Add module-level Windows skip to `tests/test_record.py`.** This is a test-infrastructure change, not feature code, so there is no failing-test-first step — the verification is that the Linux suite still collects and passes every recorder test (no accidental skips on Linux). The file currently starts:
  ```python
  import os
  import subprocess
  import time

  import pytest

  os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

  from PySide6.QtWidgets import QApplication
  ```
  Change it to:
  ```python
  import os
  import subprocess
  import sys
  import time

  import pytest

  os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

  from PySide6.QtWidgets import QApplication

  pytestmark = pytest.mark.skipif(
      sys.platform == "win32",
      reason="recorder tests drive POSIX subprocesses (true/sleep, SIGINT-as-EOS);"
             " the recorder itself is Linux-only (portal/PipeWire/gst)",
  )
  ```
  Gotcha: `pytestmark` must be module-level and assigned after `pytest` is imported. With this skip active, Windows never imports `wondershot.record` from this file (the heavy imports are inside test helpers, e.g. `make_recorder`), which is fine — `record.py` is import-safe everywhere anyway (`gi` is in try/except).

- [x] **Guard the permission assertion in `tests/test_msgraph.py`.** Line 13 currently reads:
  ```python
      assert oct(os.stat(msgraph.token_path()).st_mode & 0o777) == "0o600"
  ```
  Replace with:
  ```python
      if os.name == "posix":
          assert oct(os.stat(msgraph.token_path()).st_mode & 0o777) == "0o600"
  ```
  Only the one assertion is gated — the rest of `test_token_cache_roundtrip` (save/load/account) still runs on Windows.

- [x] **Run the full suite on Linux and confirm nothing got skipped here:**
  ```bash
  .venv/bin/pytest tests/ -v
  ```
  Expected: all tests pass, `tests/test_record.py` shows `PASSED` (not `SKIPPED`) for all 4 recorder tests, `test_token_cache_roundtrip` passes.

- [x] **Commit:**
  ```bash
  git add tests/test_record.py tests/test_msgraph.py
  git commit -m "tests: honest Windows skips for POSIX-only recorder/perm assertions"
  ```

---

## Task 2: Path audit fixes — recorder log dir and Graph token path

Two real findings from the audit. (1) `wondershot/record.py:281–285` builds the recorder log dir from `XDG_CACHE_HOME`/`~/.cache` by hand; on Windows/macOS that's wrong. `record.py` already imports PySide6, so use `QStandardPaths.GenericCacheLocation` (which itself honors `XDG_CACHE_HOME` on Linux — behavior there is unchanged). (2) `wondershot/msgraph.py:77–81` (`token_path`) falls back to `~/.local/share` — but `msgraph.py` is documented "stdlib only" (its module docstring), so the fix is a stdlib platform switch, NOT a PySide6 import.

**Files:**
- Modify: `wondershot/record.py` (add `log_dir()` near the top after imports; use it at lines ~281–285 in `_launch_gst`)
- Modify: `wondershot/msgraph.py` (add `import sys` to the import block at lines ~13–20; replace `token_path` at lines ~77–81)
- Test: `tests/test_record.py` (append), `tests/test_msgraph.py` (append)

**Steps:**

- [ ] **Write the failing test for `record.log_dir()`.** Append to `tests/test_record.py`:
  ```python
  def test_log_dir_uses_standard_cache_location():
      """recorder.log must live under the platform cache dir, not ~/.cache."""
      from PySide6.QtCore import QStandardPaths
      from wondershot.record import log_dir
      base = QStandardPaths.writableLocation(
          QStandardPaths.GenericCacheLocation)
      assert log_dir() == os.path.join(base, "wondershot")
  ```
  (Note: this lands under the Task 1 `pytestmark`, so it is skipped on Windows along with the module — acceptable; the macOS CI job exercises it off-Linux.)

- [ ] **Run it and watch it fail:**
  ```bash
  .venv/bin/pytest tests/test_record.py::test_log_dir_uses_standard_cache_location -v
  ```
  Expected failure: `ImportError: cannot import name 'log_dir' from 'wondershot.record'`.

- [ ] **Implement `log_dir()` in `wondershot/record.py`.** Add after the module's import block (after the `try: import gi ...` block):
  ```python
  def log_dir() -> str:
      """Per-platform cache dir for recorder logs (honors XDG on Linux)."""
      from PySide6.QtCore import QStandardPaths
      base = QStandardPaths.writableLocation(
          QStandardPaths.GenericCacheLocation)
      return os.path.join(base, "wondershot")
  ```
  Then in `_launch_gst` (currently lines ~281–285), replace:
  ```python
          log_dir = os.path.join(
              os.environ.get("XDG_CACHE_HOME",
                             os.path.expanduser("~/.cache")), "wondershot")
          os.makedirs(log_dir, exist_ok=True)
          self.log_path = os.path.join(log_dir, "recorder.log")
  ```
  with:
  ```python
          logs = log_dir()
          os.makedirs(logs, exist_ok=True)
          self.log_path = os.path.join(logs, "recorder.log")
  ```
  Gotcha: the old local variable is named `log_dir` — it MUST be renamed (to `logs`) or it shadows the new module-level function.

- [ ] **Run the record tests:**
  ```bash
  .venv/bin/pytest tests/test_record.py -v
  ```
  Expected: all pass, including the new test.

- [ ] **Write the failing tests for `msgraph.token_path` platform fallbacks.** Append to `tests/test_msgraph.py`:
  ```python
  def test_token_path_env_override(monkeypatch, tmp_path):
      from wondershot import msgraph
      monkeypatch.setenv("WONDERSHOT_DATA_DIR", str(tmp_path))
      assert msgraph.token_path() == str(tmp_path / "graph_token.json")


  def test_token_path_windows_fallback(monkeypatch, tmp_path):
      import sys
      from wondershot import msgraph
      monkeypatch.delenv("WONDERSHOT_DATA_DIR", raising=False)
      monkeypatch.setattr(sys, "platform", "win32")
      monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
      assert msgraph.token_path() == os.path.join(
          str(tmp_path), "wondershot", "graph_token.json")


  def test_token_path_macos_fallback(monkeypatch):
      import sys
      from wondershot import msgraph
      monkeypatch.delenv("WONDERSHOT_DATA_DIR", raising=False)
      monkeypatch.setattr(sys, "platform", "darwin")
      assert msgraph.token_path() == os.path.join(
          os.path.expanduser("~/Library/Application Support"),
          "wondershot", "graph_token.json")


  def test_token_path_linux_fallback(monkeypatch, tmp_path):
      import sys
      from wondershot import msgraph
      monkeypatch.delenv("WONDERSHOT_DATA_DIR", raising=False)
      monkeypatch.setattr(sys, "platform", "linux")
      monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
      assert msgraph.token_path() == os.path.join(
          str(tmp_path), "wondershot", "graph_token.json")
  ```
  (`monkeypatch.setattr(sys, "platform", ...)` works because the implementation reads `sys.platform` at call time, and monkeypatch restores it after each test. `tests/test_msgraph.py` already has `import os` at the top — check; if not, add it.)

- [ ] **Run them and watch the three fallback tests fail:**
  ```bash
  .venv/bin/pytest tests/test_msgraph.py -v
  ```
  Expected: `test_token_path_env_override` passes already (the env override exists today); the other three fail — `test_token_path_windows_fallback` and `test_token_path_macos_fallback` with assertion errors showing the `~/.local/share` path, and `test_token_path_linux_fallback` because the current code hardcodes `expanduser("~/.local/share")` and ignores `XDG_DATA_HOME` (the test sets it to `tmp_path`). Confirm all three fail before implementing.

- [ ] **Implement in `wondershot/msgraph.py`** — stdlib only, per the module's docstring contract. Add `import sys` to the import block (it currently imports `base64, hashlib, json, os, secrets, time, urllib.error, urllib.parse, ...`). Then replace `token_path` (currently):
  ```python
  def token_path() -> str:
      base = os.environ.get(
          "WONDERSHOT_DATA_DIR",
          os.path.join(os.path.expanduser("~/.local/share"), "wondershot"))
      return os.path.join(base, "graph_token.json")
  ```
  with:
  ```python
  def _data_home() -> str:
      """Per-platform user data dir — stdlib only (this module's contract)."""
      if sys.platform == "win32":
          return os.environ.get(
              "LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
      if sys.platform == "darwin":
          return os.path.expanduser("~/Library/Application Support")
      return os.environ.get(
          "XDG_DATA_HOME", os.path.expanduser("~/.local/share"))


  def token_path() -> str:
      base = os.environ.get(
          "WONDERSHOT_DATA_DIR", os.path.join(_data_home(), "wondershot"))
      return os.path.join(base, "graph_token.json")
  ```

- [ ] **Run the whole suite:**
  ```bash
  .venv/bin/pytest tests/ -v
  ```
  Expected: all pass (existing `test_share.py`/`test_msgraph.py` tests set `WONDERSHOT_DATA_DIR`, so they are unaffected).

- [ ] **Commit:**
  ```bash
  git add wondershot/record.py wondershot/msgraph.py tests/test_record.py tests/test_msgraph.py
  git commit -m "paths: recorder log via QStandardPaths; per-platform Graph token dir"
  ```

---

## Task 3: HotkeyBackend seam

`wondershot/hotkey.py` is one 56-line class, `HotkeyManager`, that listens (signal-match only — read the module docstring, there's a KWin-crash landmine documented there; do NOT add method calls into kglobalaccel) for KGlobalAccel presses over QtDBus. Extract the shape: a `HotkeyBackend` base, the existing impl renamed `KGlobalAccelBackend` (behavior byte-for-byte identical), a `NullHotkeyBackend` that registers nothing, and a `create_hotkey_backend()` factory keyed on `sys.platform`. The only consumer is `wondershot/app.py` lines 17 and 96–98.

**Gotcha:** you cannot mix `abc.ABC` with `QObject` (metaclass conflict between `ABCMeta` and Shiboken's type). The base is a plain `QObject` subclass whose `register()` raises `NotImplementedError`.

**Files:**
- Modify: `wondershot/hotkey.py` (full rewrite, preserving the docstring and the KGlobalAccel listener code verbatim)
- Modify: `wondershot/app.py` (line 17 import; line 96 construction)
- Test: Create `tests/test_hotkey.py`

**Steps:**

- [ ] **Write the failing tests.** Create `tests/test_hotkey.py`:
  ```python
  import os
  import sys

  import pytest

  os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


  def test_factory_picks_kglobalaccel_on_linux(monkeypatch):
      from wondershot import hotkey
      monkeypatch.setattr(sys, "platform", "linux")
      b = hotkey.create_hotkey_backend()
      assert isinstance(b, hotkey.KGlobalAccelBackend)
      assert isinstance(b, hotkey.HotkeyBackend)


  @pytest.mark.parametrize("platform", ["win32", "darwin"])
  def test_factory_picks_null_elsewhere(monkeypatch, platform):
      from wondershot import hotkey
      monkeypatch.setattr(sys, "platform", platform)
      b = hotkey.create_hotkey_backend()
      assert isinstance(b, hotkey.NullHotkeyBackend)


  def test_null_backend_register_is_inert():
      from wondershot import hotkey
      b = hotkey.NullHotkeyBackend()
      assert b.register() is False
      assert b.active is False
      assert hasattr(b, "pressed")  # the signal every backend must expose


  def test_base_register_is_abstract():
      from wondershot import hotkey
      with pytest.raises(NotImplementedError):
          hotkey.HotkeyBackend().register()
  ```
  (QObject construction without a QApplication is fine; no qapp fixture needed. `KGlobalAccelBackend.register()` is never called in tests — on a CI box with no session D-Bus it would just return False, but we don't rely on that.)

- [ ] **Run and watch them fail:**
  ```bash
  .venv/bin/pytest tests/test_hotkey.py -v
  ```
  Expected failure: `AttributeError: module 'wondershot.hotkey' has no attribute 'create_hotkey_backend'` (and friends).

- [ ] **Rewrite `wondershot/hotkey.py`.** Keep the existing module docstring (lines 1–13, the KWin landmine note) verbatim at the top, then:
  ```python
  from __future__ import annotations

  import sys

  from PySide6.QtCore import QObject, Signal, Slot

  COMPONENT = "grabbit"
  ACTION = "capture-region"
  SERVICE = "org.kde.kglobalaccel"


  class HotkeyBackend(QObject):
      """Platform seam for global capture hotkeys.

      Plain QObject base (abc.ABCMeta conflicts with Shiboken's metaclass);
      subclasses implement register().
      """

      pressed = Signal()

      def __init__(self, parent=None):
          super().__init__(parent)
          self.active = False

      def register(self) -> bool:
          raise NotImplementedError


  class NullHotkeyBackend(HotkeyBackend):
      """No global-hotkey integration on this platform yet (WS-E adds real
      Windows/macOS backends later)."""

      def register(self) -> bool:
          return False


  class KGlobalAccelBackend(HotkeyBackend):
      def register(self) -> bool:
          """Listen for KGlobalAccel presses of a 'grabbit' component.

          Never makes method calls into the shortcut daemon (see module
          docstring); adding a signal match rule is harmless on any desktop.
          """
          from PySide6.QtCore import SLOT
          from PySide6.QtDBus import QDBusConnection

          bus = QDBusConnection.sessionBus()
          if not bus.isConnected():
              return False
          ok = bus.connect(
              SERVICE,
              f"/component/{COMPONENT}",
              "org.kde.kglobalaccel.Component",
              "globalShortcutPressed",
              self,
              SLOT("_on_pressed(QString,QString,qlonglong)"),
          )
          self.active = bool(ok)
          return self.active

      @Slot(str, str, "qlonglong")
      def _on_pressed(self, component: str, action: str,
                      _timestamp: int) -> None:
          if component == COMPONENT and action == ACTION:
              self.pressed.emit()


  def create_hotkey_backend(parent=None) -> HotkeyBackend:
      if sys.platform.startswith("linux"):
          return KGlobalAccelBackend(parent)
      return NullHotkeyBackend(parent)
  ```
  Behavior notes: the KGlobalAccel logic is the existing code moved, with two deliberate changes — the QtDBus import moves inside `register()` (so importing `wondershot.hotkey` never touches QtDBus off-Linux), and `__init__`/`active` live on the base. There is no `HotkeyManager` name anymore; the only consumer is updated next step.

- [ ] **Update `wondershot/app.py`.** Line 17:
  ```python
  from .hotkey import HotkeyManager
  ```
  becomes:
  ```python
  from .hotkey import create_hotkey_backend
  ```
  Lines 96–98:
  ```python
          self.hotkey = HotkeyManager(self)
          self.hotkey.pressed.connect(lambda: self.trigger_capture("region"))
          self.hotkey.register()
  ```
  becomes:
  ```python
          self.hotkey = create_hotkey_backend(self)
          self.hotkey.pressed.connect(lambda: self.trigger_capture("region"))
          self.hotkey.register()
  ```
  (GUI glue — covered by the import-smoke + existing suite, not a new unit test; `app.py` has no headless test harness today.)

- [ ] **Run the full suite (regressions in app import path would surface via gallery/editor tests):**
  ```bash
  .venv/bin/pytest tests/ -v && .venv/bin/python -c "import wondershot.app, wondershot.hotkey; print('ok')"
  ```
  Expected: all tests pass; `ok` printed.

- [ ] **Commit:**
  ```bash
  git add wondershot/hotkey.py wondershot/app.py tests/test_hotkey.py
  git commit -m "hotkey: extract HotkeyBackend seam with platform factory (no new backends)"
  ```

---

## Task 4: GitHub Actions CI matrix

No CI exists (`.github/` is absent). Matrix: {ubuntu, windows, macos}-latest × Python {3.10, 3.13}. Linux needs Qt's offscreen-platform shared libs — PySide6's `libQt6Gui` links EGL/xkbcommon even offscreen; `libegl1` is the one that actually breaks import on a bare `ubuntu-latest` (24.04). `QT_QPA_PLATFORM=offscreen` is set job-wide (harmless on Windows/macOS, required on Linux). Tasks 1–3 made the suite honest off-Linux, so `pytest` runs un-filtered on all three OSes; `tests/test_record.py` self-skips on Windows via its `pytestmark`.

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: a YAML-parse check plus a local dry run of the exact CI commands (Linux leg); full-matrix verification happens on the first push

**Steps:**

- [ ] **Create `.github/workflows/ci.yml`:**
  ```yaml
  name: CI

  on:
    push:
      branches: [main]
    pull_request:

  jobs:
    test:
      strategy:
        fail-fast: false
        matrix:
          os: [ubuntu-latest, windows-latest, macos-latest]
          python: ["3.10", "3.13"]
      runs-on: ${{ matrix.os }}
      env:
        QT_QPA_PLATFORM: offscreen
      steps:
        - uses: actions/checkout@v4

        - uses: actions/setup-python@v5
          with:
            python-version: ${{ matrix.python }}

        - name: Install Qt offscreen runtime deps (Linux)
          if: runner.os == 'Linux'
          run: |
            sudo apt-get update
            sudo apt-get install -y --no-install-recommends \
              libegl1 libgl1 libxkbcommon0 libdbus-1-3 \
              libfontconfig1 libxcb-cursor0

          # libegl1 is the hard requirement for importing PySide6 offscreen
          # on ubuntu-latest; the rest are cheap insurance for QtGui/QtWidgets.

        - name: Install package
          run: python -m pip install -e . pytest

        - name: Import smoke
          run: python -c "import wondershot; print(wondershot.__version__)"

        - name: Tests
          run: python -m pytest tests/ -v
  ```
  Notes for the executor: keep the import smoke to `import wondershot` only (per spec) — deeper module imports are exercised by pytest itself, which imports `wondershot.editor`, `wondershot.gallery`, `wondershot.imageops`, `wondershot.msgraph`, `wondershot.share`, `wondershot.video`, and (Linux/macOS only) `wondershot.record` and the new `wondershot.hotkey`. Do NOT add `xvfb` — offscreen platform makes it unnecessary.

- [ ] **Validate the YAML parses (no actions runner locally):**
  ```bash
  .venv/bin/pip install pyyaml >/dev/null && .venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"
  ```
  Expected output: `yaml ok`.

- [ ] **Run the exact CI commands locally as a dry run (Linux leg):**
  ```bash
  QT_QPA_PLATFORM=offscreen .venv/bin/python -c "import wondershot; print(wondershot.__version__)" && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -v
  ```
  Expected: `0.1.0` printed, all tests pass.

- [ ] **Commit:**
  ```bash
  git add .github/workflows/ci.yml
  git commit -m "ci: 3-OS x py3.10/3.13 matrix — install, import smoke, pytest"
  ```

---

## Done criteria

- `.venv/bin/pytest tests/ -v` fully green on Linux with zero skips.
- `git log` shows 4 commits (one per task).
- `grep -rn '\.cache\|\.local/share' wondershot/` shows hits only in `cli.py` (desktop-file install, intentional), `msgraph.py`'s `_data_home` Linux branch (XDG fallback, intentional), and docstrings/comments.
- First push exercises the matrix; Windows job shows `tests/test_record.py` as skipped with the POSIX reason, everything else passing.
