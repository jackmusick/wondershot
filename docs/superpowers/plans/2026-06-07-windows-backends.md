# Windows Backends (WS-E) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working Windows version of wondershot on the win11-pam VM: tray app launches, the global hotkey fires a capture, region/fullscreen/window capture produce correct PNGs in the library, recording produces a playable mp4 — per the definition of done in spec Addendum 3 (`docs/superpowers/specs/2026-06-06-snagit-parity-design.md`).

**Architecture:** Three new Windows backends behind the existing platform seams, selected by `sys.platform` factories so Linux is byte-identical: `WinCaptureManager` (`wondershot/wincapture.py` — mss fullscreen grabs, ctypes `GetForegroundWindow`+`DwmGetWindowAttribute` active-window geometry, an owned frameless Qt region overlay), `WinScreenRecorder` (`wondershot/winrecord.py` — ffmpeg `ddagrab` with `gdigrab` fallback + `dshow` mic, QProcess, same stop/watchdog/salvage semantics as `record.py`), and `WinHotkeyBackend` (in `hotkey.py` — `RegisterHotKey` message loop on a QThread). All Windows API access is lazy and injectable so the Linux suite tests everything headless with fakes; nothing imports `ctypes.windll` or `mss` at module-import time.

**Tech Stack:** Python 3.11 (VM venv), PySide6 6.11.1, mss (staged in `C:/dev/wheels`), ffmpeg 8.1.1 (essentials build on the VM), ctypes. No GStreamer on Windows.

**Execution environment:**
- Worktree **EXISTS**: `/home/jack/GitHub/grabbit-wt/win-port`, branch `session/win-port` (currently at main HEAD). All code changes happen there. Run Linux tests with the repo venv: `cd /home/jack/GitHub/grabbit-wt/win-port && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q` (if the main checkout has no `.venv`, create one: `python -m venv .venv && .venv/bin/pip install -e . pytest numpy`).
- **VM ACCESS (win11-pam, local libvirt, RUNNING):**
  - `export SSHPASS='YoureAbsolutelyRight!1'; sshpass -e ssh -o StrictHostKeyChecking=no developer@192.168.122.175 '<cmd>'`
  - cmd.exe is the default shell; prefix PowerShell as: `powershell.exe -Command "..."` (quoting is treacherous — for anything multiline, write a `.ps1` locally, `sshpass -e scp` it to `C:/dev/`, run with `-ExecutionPolicy Bypass -File`)
  - Repo on VM: `C:\dev\wondershot` with `.venv` (PySide6 6.11.1, numpy, pytest installed OFFLINE). ffmpeg at `C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin` (on User PATH; NOT in plain ssh cmd sessions unless re-login — set PATH explicitly in test commands).
  - **NO INTERNET ON THE VM.** pip installs: download wheels on the HOST (`.venv/bin/pip download -d /tmp/winwheels --platform win_amd64 --python-version 311 --only-binary=:all: <pkg>`), scp to `C:/dev/wheels/`, install with `--no-index --find-links C:\dev\wheels`. **mss is ALREADY staged in `C:/dev/wheels`.**
  - Deploy your branch to the VM: `git archive --format=tar.gz -o /tmp/ws.tar.gz HEAD` (in the worktree), scp to `C:/dev/`, then on VM: `cd C:\dev\wondershot && tar xzf C:\dev\ws.tar.gz` (overwrites tree; `.venv` survives; re-run `pip install -e` if pyproject changed).
  - Suite on VM: `cd C:\dev\wondershot && set QT_QPA_PLATFORM=offscreen&& set PATH=C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin;%PATH%&& .venv\Scripts\python -m pytest tests/ -q` → baseline **329 passed / 16 skipped**.
  - VISUAL verification: the VM has a logged-in desktop session, but ssh sessions are session-0. To touch the interactive desktop use a scheduled task: `schtasks /create /tn probe /tr "..." /sc once /st 00:00 /it /f && schtasks /run /tn probe`. Screenshot with a CopyFromScreen `.ps1`, scp the PNG back, and **Read it** (literally look at it).
  - GUI app launch on the interactive desktop: same schtasks `/it` trick. Check processes with `tasklist`.

Shell prelude used by every VM step below (run once per session in your terminal):

```bash
export SSHPASS='YoureAbsolutelyRight!1'
VM=developer@192.168.122.175
alias vssh="sshpass -e ssh -o StrictHostKeyChecking=no $VM"
alias vscp="sshpass -e scp -o StrictHostKeyChecking=no"
```

(If aliases don't expand in your harness, write the full `sshpass -e ssh -o StrictHostKeyChecking=no developer@192.168.122.175 '...'` each time.)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `wondershot/wincapture.py` | **create** | Windows stills backend: `bgra_to_qimage`, `selection_rect`, `RECT`/`active_window_rect` (ctypes, injectable), `grab_fullscreen` (mss, lazy import), `RegionOverlay`, `WinCaptureManager` |
| `wondershot/winrecord.py` | **create** | Windows recorder: `ddagrab_args`/`gdigrab_args` builders, `have_ddagrab` probe, `parse_dshow_audio_devices`/`list_dshow_audio_devices`, `WinScreenRecorder` (QProcess, q-on-stdin stop, watchdog, salvage) |
| `wondershot/capture.py` | modify | add `create_capture_manager()` factory + `window_capture_available()` |
| `wondershot/record.py` | modify | add `create_screen_recorder()` factory |
| `wondershot/hotkey.py` | modify | add `WinHotkeyBackend` + `_WinHotkeyThread`; factory picks it on win32 |
| `wondershot/app.py` | modify | use both factories; portable `server_name()`; window-mode gate via `window_capture_available()` |
| `wondershot/capture_window.py` | modify | disable the "Capture cursor" toggle on Windows with an honest tooltip |
| `pyproject.toml` | modify | `windows = ["mss>=9"]` optional extra |
| `tests/test_wincapture.py` | **create** | pure math, ctypes fakes, manager signal/crop parity (mirrors `test_capture_crop.py`) |
| `tests/test_winoverlay.py` | **create** | RegionOverlay selection via QTest synthetic mouse events (offscreen-safe) |
| `tests/test_winrecord.py` | **create** | args builders, dshow parser, probe, full stop/escalation/salvage lifecycle against a Python stub child |
| `tests/test_win_factories.py` | **create** | factory selection on win32 **and Linux byte-identity pins** |
| `tests/test_hotkey.py` | modify | win32 now yields `WinHotkeyBackend` (was Null); constants/shape tests |
| `tests/test_app_server_name.py` | **create** | `server_name()` works without `os.getuid` |
| `docs/superpowers/plans/2026-06-07-desktop-checklist.md` | modify (Task 14) | append the Windows definition-of-done results |

Design rule enforced everywhere (spec item 5): **no module-level `ctypes.windll`, `ctypes.wintypes`, or `import mss`**. `ctypes.Structure` subclasses with explicit `c_long`/`c_void_p` fields are portable and fine at module level. A dedicated test imports both new modules on Linux.

---

### Task 1: Worktree sanity + VM baseline + mss install

**Files:** none (environment only)

- [x] **Step 1: Confirm the worktree and branch**

```bash
git -C /home/jack/GitHub/grabbit-wt/win-port status --short && git -C /home/jack/GitHub/grabbit-wt/win-port log --oneline -1
```

Expected: clean tree, branch `session/win-port`. If the plan file you're reading isn't in the worktree yet, copy it: `cp /home/jack/GitHub/grabbit/docs/superpowers/plans/2026-06-07-windows-backends.md /home/jack/GitHub/grabbit-wt/win-port/docs/superpowers/plans/`.

- [x] **Step 2: Linux baseline in the worktree**

```bash
cd /home/jack/GitHub/grabbit-wt/win-port && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all pass (note the exact count — it is your Linux pin for every later task).

- [x] **Step 3: VM reachable + baseline suite**

```bash
vssh "cd C:\dev\wondershot && set QT_QPA_PLATFORM=offscreen&& set PATH=C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin;%PATH%&& .venv\Scripts\python -m pytest tests/ -q"
```

Expected: `329 passed, 16 skipped` (or current equivalent).

- [x] **Step 4: Install mss on the VM from staged wheels**

```bash
vssh "C:\dev\wondershot\.venv\Scripts\pip install --no-index --find-links C:\dev\wheels mss"
vssh "C:\dev\wondershot\.venv\Scripts\python -c \"import mss; print(mss.__version__)\""
```

Expected: a version number prints. If the wheel is somehow absent, download on the HOST and scp: `pip download -d /tmp/winwheels --platform win_amd64 --python-version 311 --only-binary=:all: mss && vscp /tmp/winwheels/* developer@192.168.122.175:C:/dev/wheels/`.

- [x] **Step 5: Confirm ffmpeg + ddagrab on the VM**

```bash
vssh "C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg -hide_banner -filters | findstr ddagrab"
vssh "C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg -hide_banner -list_devices true -f dshow -i dummy 2>&1 | findstr audio"
```

Expected: a `ddagrab` line; zero or more dshow audio devices (record the device names — Task 11 uses them; if none, mic recording on the VM is honestly untestable and the mic path verifies as "no devices → records video-only").

---

### Task 2: Portable `server_name()` (Windows has no `os.getuid`)

`app.py:23` calls `os.getuid()` — `AttributeError` on Windows, crashing app startup before the tray appears.

**Files:**
- Modify: `wondershot/app.py:22-23`
- Test: `tests/test_app_server_name.py` (create)

- [x] **Step 1: Write the failing test**

```python
# tests/test_app_server_name.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_server_name_with_getuid():
    from wondershot.app import server_name
    if hasattr(os, "getuid"):
        assert server_name() == f"wondershot-{os.getuid()}"


def test_server_name_without_getuid(monkeypatch):
    """Windows has no os.getuid; startup must not crash (app.py:23)."""
    from wondershot.app import server_name
    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.setenv("USERNAME", "developer")
    name = server_name()
    assert name == "wondershot-developer"
```

- [x] **Step 2: Run it — verify it fails**

```bash
cd /home/jack/GitHub/grabbit-wt/win-port && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_app_server_name.py -v
```

Expected: `test_server_name_without_getuid` FAILS with `AttributeError: ... has no attribute 'getuid'`.

- [x] **Step 3: Implement**

In `wondershot/app.py` replace:

```python
def server_name() -> str:
    return f"wondershot-{os.getuid()}"
```

with:

```python
def server_name() -> str:
    # Windows has no os.getuid; the username scopes the socket the same way.
    uid = os.getuid() if hasattr(os, "getuid") else os.environ.get(
        "USERNAME", "user")
    return f"wondershot-{uid}"
```

- [x] **Step 4: Run the test file, then the whole suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_app_server_name.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: PASS; suite count = baseline + 2.

- [x] **Step 5: Commit**

```bash
cd /home/jack/GitHub/grabbit-wt/win-port && git add wondershot/app.py tests/test_app_server_name.py && git commit -m "fix: portable server_name (Windows has no os.getuid)"
```

---

### Task 3: `wincapture.py` pure core — BGRA conversion, selection math, active-window geometry

**Files:**
- Create: `wondershot/wincapture.py`
- Modify: `pyproject.toml` (windows extra)
- Test: `tests/test_wincapture.py` (create)

- [x] **Step 1: Write the failing tests**

```python
# tests/test_wincapture.py
import ctypes
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# -- import guard (spec item 5) ---------------------------------------------

def test_module_imports_cleanly_on_linux():
    """Nothing at module level may touch ctypes.windll or mss."""
    import wondershot.wincapture  # noqa: F401


# -- bgra_to_qimage -----------------------------------------------------------

def test_bgra_to_qimage_pixel_values(qapp):
    from wondershot.wincapture import bgra_to_qimage
    # one BGRA pixel: blue=10, green=20, red=30, alpha=255
    data = bytes([10, 20, 30, 255])
    img = bgra_to_qimage(data, 1, 1)
    c = img.pixelColor(0, 0)
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (30, 20, 10, 255)


def test_bgra_to_qimage_detaches_from_buffer(qapp):
    """mss frees its buffer after the grab; the QImage must own a copy."""
    from wondershot.wincapture import bgra_to_qimage
    data = bytearray([1, 2, 3, 255] * 4)
    img = bgra_to_qimage(bytes(data), 2, 2)
    del data
    assert img.width() == 2 and img.height() == 2
    img.pixelColor(1, 1)  # must not crash / read freed memory


# -- selection_rect -----------------------------------------------------------

def test_selection_rect_normalizes_any_drag_direction():
    from wondershot.wincapture import selection_rect
    bounds = QRect(0, 0, 200, 100)
    r = selection_rect(QPoint(50, 40), QPoint(10, 20), bounds)
    assert r == QRect(10, 20, 41, 21)  # QRect(p1, p2) is inclusive


def test_selection_rect_clamps_to_bounds():
    from wondershot.wincapture import selection_rect
    bounds = QRect(0, 0, 200, 100)
    r = selection_rect(QPoint(-30, -30), QPoint(500, 500), bounds)
    assert r == bounds


# -- active_window_rect (ctypes fakes, spec: "trivially fakeable") ------------

class FakeUser32:
    def __init__(self, hwnd=1234, win_rect=(5, 6, 105, 86)):
        self.hwnd = hwnd
        self.win_rect = win_rect

    def GetForegroundWindow(self):
        return self.hwnd

    def GetWindowRect(self, hwnd, rect_ref):
        r = rect_ref._obj
        r.left, r.top, r.right, r.bottom = self.win_rect
        return 1


class FakeDwmapi:
    """DwmGetWindowAttribute returning EXTENDED_FRAME_BOUNDS (no shadow)."""

    def __init__(self, rect=(10, 20, 110, 90), hresult=0):
        self.rect = rect
        self.hresult = hresult
        self.calls = []

    def DwmGetWindowAttribute(self, hwnd, attr, rect_ref, size):
        self.calls.append((hwnd, attr, size))
        if self.hresult != 0:
            return self.hresult
        r = rect_ref._obj
        r.left, r.top, r.right, r.bottom = self.rect
        return 0


def test_active_window_rect_uses_extended_frame_bounds():
    from wondershot.wincapture import (
        DWMWA_EXTENDED_FRAME_BOUNDS, RECT, active_window_rect)
    dwm = FakeDwmapi(rect=(10, 20, 110, 90))
    got = active_window_rect(user32=FakeUser32(), dwmapi=dwm)
    assert got == (10, 20, 100, 70)
    hwnd, attr, size = dwm.calls[0]
    assert hwnd == 1234
    assert attr == DWMWA_EXTENDED_FRAME_BOUNDS == 9
    assert size == ctypes.sizeof(RECT)


def test_active_window_rect_falls_back_to_getwindowrect():
    """DWM can fail (e.g. composition quirk); GetWindowRect is the net."""
    from wondershot.wincapture import active_window_rect
    got = active_window_rect(
        user32=FakeUser32(win_rect=(5, 6, 105, 86)),
        dwmapi=FakeDwmapi(hresult=-2147024809))
    assert got == (5, 6, 100, 80)


def test_active_window_rect_none_when_no_foreground_window():
    from wondershot.wincapture import active_window_rect
    assert active_window_rect(
        user32=FakeUser32(hwnd=0), dwmapi=FakeDwmapi()) is None


def test_active_window_rect_none_for_degenerate_rect():
    from wondershot.wincapture import active_window_rect
    assert active_window_rect(
        user32=FakeUser32(), dwmapi=FakeDwmapi(rect=(10, 20, 10, 20))) is None
```

- [x] **Step 2: Run — verify failure**

```bash
cd /home/jack/GitHub/grabbit-wt/win-port && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_wincapture.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wondershot.wincapture'`.

- [x] **Step 3: Implement the module core**

```python
# wondershot/wincapture.py
"""Windows stills backend: mss grabs + ctypes window geometry + an owned
frameless region overlay.

The kwin.py analog for Windows. Import-safe on every platform: nothing
touches ctypes.windll or imports mss at module level; all Windows API
access goes through injectable seams (user32/dwmapi parameters, the
manager's grab function) so the Linux suite tests everything headless.

Cursor capture: mss grabs via BitBlt without the cursor and exposes no
option to include it — capture_cursor is documented unsupported on
Windows and the toggle is disabled in the capture panel.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from .capture import timestamp_name, unique_path
from .kwin import crop_file_to_global_rect, map_global_rect

DWMWA_EXTENDED_FRAME_BOUNDS = 9


class RECT(ctypes.Structure):
    # Defined with portable c_long fields (not ctypes.wintypes) so the
    # Linux suite can build and inspect instances.
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _windll(name: str):
    """Lazy windll accessor — only ever evaluated on Windows."""
    return getattr(ctypes.windll, name)  # pragma: no cover (Windows only)


def bgra_to_qimage(data: bytes, w: int, h: int) -> QImage:
    """mss BGRA bytes -> detached ARGB32 QImage (mss reuses its buffer)."""
    img = QImage(data, w, h, w * 4, QImage.Format_ARGB32)
    return img.copy()


def selection_rect(press: QPoint, current: QPoint, bounds: QRect) -> QRect:
    """Normalized drag rectangle, clamped to the widget bounds."""
    return QRect(press, current).normalized().intersected(bounds)


def active_window_rect(user32=None, dwmapi=None):
    """(x, y, w, h) of the foreground window's visible frame, or None.

    DWMWA_EXTENDED_FRAME_BOUNDS excludes the invisible resize-border /
    drop-shadow that GetWindowRect includes; GetWindowRect is the
    fallback when DWM refuses.
    """
    user32 = user32 if user32 is not None else _windll("user32")
    dwmapi = dwmapi if dwmapi is not None else _windll("dwmapi")
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = RECT()
    res = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect),
        ctypes.sizeof(RECT))
    if res != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    return (rect.left, rect.top, w, h)


def grab_fullscreen():
    """Grab the whole virtual desktop (all monitors).

    Returns (QImage, QRect virtual) where virtual is the desktop union in
    the same physical-pixel space as the image — the crop space for
    _finish (left/top can be negative with monitors left of primary).
    """
    import mss  # lazy: pip extra `wondershot[windows]`
    with mss.mss() as sct:
        mon = sct.monitors[0]
        shot = sct.grab(mon)
        img = bgra_to_qimage(shot.bgra, shot.width, shot.height)
        return img, QRect(mon["left"], mon["top"],
                          mon["width"], mon["height"])
```

Note: `ctypes.byref(rect)._obj` is how the fake reads the structure back — `byref` objects expose `_obj` in CPython; the fakes above rely on it.

- [x] **Step 4: Add the pyproject extra**

In `pyproject.toml` under `[project.optional-dependencies]` add:

```toml
windows = ["mss>=9"]  # WS-E stills backend; Windows-only runtime dep
```

- [x] **Step 5: Run tests, then the suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_wincapture.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add wondershot/wincapture.py tests/test_wincapture.py pyproject.toml && git commit -m "feat: wincapture core — BGRA conversion, selection math, ctypes window geometry"
```

---

### Task 4: `WinCaptureManager` — fullscreen, active-window, delay, pending-crop parity

Mirrors `CaptureManager`'s contract exactly: `captured(str)`/`failed(str)` signals, `capture_region/capture_fullscreen/capture_window/capture_active_window` methods, `_pending_crop` one-shot + `_finish` seam + `_crop_virtual` test seam (study `tests/test_capture_crop.py` — these tests are deliberate near-copies).

**Files:**
- Modify: `wondershot/wincapture.py` (append)
- Test: `tests/test_wincapture.py` (append)

- [x] **Step 1: Write the failing tests** (append to `tests/test_wincapture.py`)

```python
# -- WinCaptureManager --------------------------------------------------------

from PySide6.QtGui import QImage as _QImage  # noqa: E402
from PySide6.QtCore import Qt as _Qt  # noqa: E402


class _Settings:
    capture_cursor = False
    capture_delay = 0

    def __init__(self, library_dir):
        self.library_dir = library_dir


def _fake_grab(w=200, h=100, virtual=None):
    """A grab seam returning a blue frame + its virtual rect."""
    img = _QImage(w, h, _QImage.Format_ARGB32)
    img.fill(_Qt.blue)
    v = virtual or QRect(0, 0, w, h)
    return lambda: (img, v)


def _manager(tmp_path, grab=None, window_rect=None):
    from wondershot.wincapture import WinCaptureManager
    return WinCaptureManager(_Settings(str(tmp_path)),
                             grab=grab or _fake_grab(),
                             window_rect=window_rect or (lambda: None))


def test_fullscreen_saves_png_and_emits_captured(qapp, tmp_path):
    m = _manager(tmp_path)
    got = []
    m.captured.connect(got.append)
    m.capture_fullscreen()
    assert len(got) == 1
    assert got[0].startswith(str(tmp_path))
    assert got[0].endswith(".png")
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (200, 100)


def test_fullscreen_grab_failure_emits_failed(qapp, tmp_path):
    def boom():
        raise OSError("no display")
    m = _manager(tmp_path, grab=boom)
    fails = []
    m.failed.connect(fails.append)
    m.capture_fullscreen()
    assert fails and "no display" in fails[0]


def test_active_window_crops_to_window_rect(qapp, tmp_path):
    m = _manager(tmp_path, window_rect=lambda: (10, 20, 50, 40))
    got = []
    m.captured.connect(got.append)
    m.capture_active_window()
    assert len(got) == 1
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (50, 40)
    assert m._pending_crop is None  # one-shot, like CaptureManager


def test_capture_window_is_active_window_on_windows(qapp, tmp_path):
    """No interactive window picker on Windows; 'window' == active window."""
    m = _manager(tmp_path, window_rect=lambda: (0, 0, 80, 60))
    got = []
    m.captured.connect(got.append)
    m.capture_window()
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (80, 60)


def test_active_window_no_window_emits_failed(qapp, tmp_path):
    m = _manager(tmp_path, window_rect=lambda: None)
    fails = []
    m.failed.connect(fails.append)
    m.capture_active_window()
    assert fails and "window" in fails[0]


def test_finish_emits_uncropped_when_rect_unusable(qapp, tmp_path):
    """Parity with test_capture_crop.py: degrade to the full shot."""
    m = _manager(tmp_path, window_rect=lambda: (9999, 9999, 10, 10))
    got = []
    m.captured.connect(got.append)
    m.capture_active_window()
    assert len(got) == 1
    assert _QImage(got[0]).width() == 200


def test_crop_respects_negative_virtual_origin(qapp, tmp_path):
    """Monitor left of primary: virtual origin is negative; the window
    rect is global. Same mapping rules as kwin.map_global_rect."""
    grab = _fake_grab(300, 100, virtual=QRect(-100, 0, 300, 100))
    m = _manager(tmp_path, grab=grab, window_rect=lambda: (-50, 10, 60, 40))
    got = []
    m.captured.connect(got.append)
    m.capture_active_window()
    out = _QImage(got[0])
    assert (out.width(), out.height()) == (60, 40)


def test_capture_delay_defers_the_grab(qapp, tmp_path):
    m = _manager(tmp_path)
    m.settings.capture_delay = 1
    got = []
    m.captured.connect(got.append)
    m.capture_fullscreen()
    assert got == []  # deferred via QTimer, not synchronous
    deadline = __import__("time").monotonic() + 3
    while not got and __import__("time").monotonic() < deadline:
        qapp.processEvents()
    assert len(got) == 1
```

- [x] **Step 2: Run — verify failure**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_wincapture.py -v
```

Expected: new tests FAIL with `ImportError: cannot import name 'WinCaptureManager'`.

- [x] **Step 3: Implement** (append to `wondershot/wincapture.py`)

```python
class WinCaptureManager(QObject):
    """Windows capture backend with CaptureManager's exact contract.

    Same signals (captured/failed), same public methods, same one-shot
    _pending_crop -> _finish seam. capture_window has no interactive
    picker on Windows and aliases the active-window mode.
    capture_cursor is unsupported (see module docstring).
    """

    captured = Signal(str)
    failed = Signal(str)

    def __init__(self, settings, parent=None, grab=None, window_rect=None):
        super().__init__(parent)
        self.settings = settings
        self._grab = grab or grab_fullscreen          # test seam
        self._window_rect = window_rect or active_window_rect  # test seam
        self._pending_crop = None    # QRect: crop the next capture to this
        self._grab_virtual = None    # QRect of the last grab's desktop union
        self._crop_virtual = None    # test seam; None = use _grab_virtual
        self._overlay = None         # RegionOverlay while picking

    # -- public API (CaptureManager parity) -----------------------------

    def capture_region(self) -> None:
        self._pending_crop = None
        self._delayed(self._do_region)

    def capture_fullscreen(self) -> None:
        self._pending_crop = None
        self._delayed(self._do_fullscreen)

    def capture_window(self) -> None:
        # Windows has no single-window interactive pick; window mode IS
        # the active-window mode (the kwin "window-auto" analog).
        self.capture_active_window()

    def capture_active_window(self) -> None:
        self._pending_crop = None
        self._delayed(self._do_active_window)

    # -- plumbing ----------------------------------------------------------

    def _delayed(self, fn) -> None:
        delay_ms = int(getattr(self.settings, "capture_delay", 0) or 0) * 1000
        if delay_ms:
            QTimer.singleShot(delay_ms, fn)
        else:
            fn()

    def _grab_or_fail(self):
        try:
            img, virtual = self._grab()
        except Exception as e:  # noqa: BLE001 — mss raises ScreenShotError
            self.failed.emit(f"screen grab failed: {e}")
            return None
        self._grab_virtual = virtual
        return img

    def _do_fullscreen(self) -> None:
        img = self._grab_or_fail()
        if img is None:
            return
        self._save_and_finish(img)

    def _do_active_window(self) -> None:
        rect = self._window_rect()
        if rect is None:
            self.failed.emit("window geometry: no active window")
            return
        self._pending_crop = QRect(*rect)
        self._do_fullscreen()

    def _save_and_finish(self, img: QImage) -> None:
        path = unique_path(self.settings.library_dir, timestamp_name())
        if not img.save(path):
            self.failed.emit("could not save screenshot")
            return
        self._finish(path)

    def _finish(self, path: str) -> None:
        """Common tail: apply a pending window crop (CaptureManager seam)."""
        crop, self._pending_crop = self._pending_crop, None
        if crop is not None:
            virtual = self._crop_virtual or self._grab_virtual
            if virtual is not None:
                # False = unusable rect; degrade to the full shot
                crop_file_to_global_rect(path, crop, virtual)
        self.captured.emit(path)
```

- [x] **Step 4: Run tests + suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_wincapture.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS (`_do_region` doesn't exist yet — `capture_region` is untested until Task 5; do NOT reference it in tests yet. If the interpreter complains at definition time it won't — it's resolved at call time).

- [x] **Step 5: Commit**

```bash
git add wondershot/wincapture.py tests/test_wincapture.py && git commit -m "feat: WinCaptureManager — fullscreen/active-window with CaptureManager parity"
```

---

### Task 5: `RegionOverlay` + region capture path

Frameless fullscreen overlay showing the frozen grab; rubber-band selection; `selected(QRect)` in **image pixel** coordinates, `cancelled()` on Esc or a sub-4px drag. The selection→image mapping reuses `kwin.map_global_rect` (same HiDPI math). This is the future owned region picker, kept portable.

**Files:**
- Modify: `wondershot/wincapture.py` (append `RegionOverlay` + `_do_region`)
- Test: `tests/test_winoverlay.py` (create)

- [x] **Step 1: Write the failing tests**

```python
# tests/test_winoverlay.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _image(w=400, h=200):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.darkGreen)
    return img


def _overlay(img=None):
    from wondershot.wincapture import RegionOverlay
    ov = RegionOverlay(img or _image())
    ov.resize(400, 200)  # offscreen: showFullScreen is meaningless; fix size
    ov.show()
    return ov


def test_drag_emits_selected_in_image_pixels(qapp):
    ov = _overlay()
    got = []
    ov.selected.connect(got.append)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(10, 20))
    QTest.mouseMove(ov, QPoint(110, 80))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(110, 80))
    assert len(got) == 1
    # widget == image size here, so coordinates map 1:1 (inclusive QRect)
    assert got[0] == QRect(10, 20, 101, 61)


def test_drag_maps_through_scale_when_image_is_hidpi(qapp):
    """Image is 2x the widget (physical vs logical pixels)."""
    ov = _overlay(_image(800, 400))
    got = []
    ov.selected.connect(got.append)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(10, 20))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(110, 80))
    r = got[0]
    assert (r.x(), r.y()) == (20, 40)
    assert abs(r.width() - 202) <= 2 and abs(r.height() - 122) <= 2


def test_tiny_drag_is_a_cancel(qapp):
    ov = _overlay()
    sel, can = [], []
    ov.selected.connect(sel.append)
    ov.cancelled.connect(can.append)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(51, 51))
    assert sel == [] and len(can) == 1


def test_escape_cancels(qapp):
    ov = _overlay()
    can = []
    ov.cancelled.connect(can.append)
    QTest.keyClick(ov, Qt.Key_Escape)
    assert len(can) == 1


def test_region_capture_saves_selection(qapp, tmp_path):
    """End-to-end through WinCaptureManager with a driven overlay."""
    from wondershot.wincapture import WinCaptureManager

    class S:
        capture_delay = 0
        capture_cursor = False

        def __init__(self, d):
            self.library_dir = d

    img = _image(400, 200)
    m = WinCaptureManager(S(str(tmp_path)),
                          grab=lambda: (img, QRect(0, 0, 400, 200)),
                          window_rect=lambda: None)
    got = []
    m.captured.connect(got.append)
    m.capture_region()
    ov = m._overlay
    assert ov is not None
    ov.resize(400, 200)
    QTest.mousePress(ov, Qt.LeftButton, Qt.NoModifier, QPoint(0, 0))
    QTest.mouseRelease(ov, Qt.LeftButton, Qt.NoModifier, QPoint(99, 49))
    assert len(got) == 1
    out = QImage(got[0])
    assert (out.width(), out.height()) == (100, 50)
    assert m._overlay is None  # released after selection


def test_region_cancel_is_silent(qapp, tmp_path):
    """Esc on the overlay = cancelled picker: no captured, no failed
    (same semantics as a cancelled spectacle pick)."""
    from wondershot.wincapture import WinCaptureManager

    class S:
        capture_delay = 0
        capture_cursor = False

        def __init__(self, d):
            self.library_dir = d

    m = WinCaptureManager(S(str(tmp_path)),
                          grab=lambda: (_image(), QRect(0, 0, 400, 200)),
                          window_rect=lambda: None)
    events = []
    m.captured.connect(lambda p: events.append(("cap", p)))
    m.failed.connect(lambda msg: events.append(("fail", msg)))
    m.capture_region()
    QTest.keyClick(m._overlay, Qt.Key_Escape)
    assert events == []
    assert m._overlay is None
```

- [x] **Step 2: Run — verify failure**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_winoverlay.py -v
```

Expected: FAIL with `ImportError: cannot import name 'RegionOverlay'`.

- [x] **Step 3: Implement** (append to `wondershot/wincapture.py`)

```python
MIN_SELECTION_PX = 4  # smaller than this is a click/slip, not a region


class RegionOverlay(QWidget):
    """Frameless fullscreen rubber-band picker over a frozen grab.

    We own the screen on Windows (no Wayland positioning bans), so the
    overlay covers the desktop, paints the grabbed frame, dims the
    unselected area, and emits selected(QRect) in IMAGE pixel
    coordinates (the grab is physical pixels; the widget is logical —
    map_global_rect does the scaling).
    """

    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self._image = image
        self._press: QPoint | None = None
        self._current: QPoint | None = None
        self._fired = False
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

    def show_on_desktop(self) -> None:
        """Cover the whole virtual desktop (all monitors)."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.virtualGeometry())
        self.show()
        self.raise_()
        self.activateWindow()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.drawImage(self.rect(), self._image)
        dim = QColor(0, 0, 0, 110)
        if self._press is None or self._current is None:
            p.fillRect(self.rect(), dim)
        else:
            sel = selection_rect(self._press, self._current, self.rect())
            for shade in (QRect(0, 0, self.width(), sel.top()),
                          QRect(0, sel.bottom() + 1, self.width(),
                                self.height() - sel.bottom() - 1),
                          QRect(0, sel.top(), sel.left(), sel.height()),
                          QRect(sel.right() + 1, sel.top(),
                                self.width() - sel.right() - 1,
                                sel.height())):
                p.fillRect(shade, dim)
            p.setPen(QPen(QColor("#26a69a"), 2))
            p.drawRect(sel)
        p.end()

    # -- input ----------------------------------------------------------------

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._press = self._current = ev.position().toPoint()
            self.update()

    def mouseMoveEvent(self, ev) -> None:
        if self._press is not None:
            self._current = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton or self._press is None:
            return
        sel = selection_rect(self._press, ev.position().toPoint(),
                             self.rect())
        self._press = self._current = None
        if (sel.width() < MIN_SELECTION_PX
                or sel.height() < MIN_SELECTION_PX):
            self._cancel()
            return
        img_rect = map_global_rect(
            sel, QRect(0, 0, self.width(), self.height()),
            self._image.width(), self._image.height())
        self._fired = True
        self.close()
        self.selected.emit(img_rect)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(ev)

    def _cancel(self) -> None:
        if self._fired:
            return
        self._fired = True
        self.close()
        self.cancelled.emit()
```

Add the missing import at the top of the file: extend the existing `PySide6.QtWidgets` needs — add `from PySide6.QtWidgets import QWidget` below the QtGui import.

Then append the region path to `WinCaptureManager`:

```python
    # -- region mode (the owned picker) --------------------------------------

    def _do_region(self) -> None:
        img = self._grab_or_fail()
        if img is None:
            return
        ov = RegionOverlay(img)
        ov.selected.connect(
            lambda rect: self._region_selected(img, rect))
        ov.cancelled.connect(self._region_cancelled)
        self._overlay = ov
        ov.show_on_desktop()

    def _region_selected(self, img: QImage, rect: QRect) -> None:
        self._overlay = None
        if rect.isEmpty():
            return  # degenerate mapping; treat as cancel
        out = img.copy(rect)
        path = unique_path(self.settings.library_dir, timestamp_name())
        if not out.save(path):
            self.failed.emit("could not save screenshot")
            return
        self.captured.emit(path)

    def _region_cancelled(self) -> None:
        # Cancelled picker: stay silent, exactly like a cancelled
        # spectacle region pick (capture.py _spectacle_done, code 0).
        self._overlay = None
```

- [x] **Step 4: Run tests + suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_winoverlay.py tests/test_wincapture.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS.

- [x] **Step 5: Commit**

```bash
git add wondershot/wincapture.py tests/test_winoverlay.py && git commit -m "feat: owned region overlay + region capture path for Windows"
```

---

### Task 6: Capture factory, app wiring, cursor toggle, Linux pins

**Files:**
- Modify: `wondershot/capture.py` (add `sys` import, `create_capture_manager`, `window_capture_available`)
- Modify: `wondershot/app.py:14,70,90-92` (use factory; window-mode gate)
- Modify: `wondershot/capture_window.py:56-60` (cursor toggle on Windows)
- Test: `tests/test_win_factories.py` (create)

- [x] **Step 1: Write the failing tests**

```python
# tests/test_win_factories.py
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    backend = "spectacle"
    capture_cursor = False
    capture_delay = 0
    mic_enabled = False
    mic_device = ""
    noise_suppression = True
    screencast_token = ""

    def __init__(self, library_dir="/tmp"):
        self.library_dir = library_dir


# -- capture factory ---------------------------------------------------------

def test_capture_factory_linux_is_byte_identical(qapp, monkeypatch):
    """Linux pin: the factory must return EXACTLY CaptureManager."""
    from wondershot import capture
    monkeypatch.setattr(sys, "platform", "linux")
    m = capture.create_capture_manager(_Settings())
    assert type(m) is capture.CaptureManager


def test_capture_factory_windows(qapp, monkeypatch):
    from wondershot import capture
    from wondershot.wincapture import WinCaptureManager
    monkeypatch.setattr(sys, "platform", "win32")
    m = capture.create_capture_manager(_Settings())
    assert type(m) is WinCaptureManager


# -- window-mode gate ---------------------------------------------------------

def test_window_capture_available_on_windows(monkeypatch):
    from wondershot import capture
    monkeypatch.setattr(sys, "platform", "win32")
    assert capture.window_capture_available() is True


def test_window_capture_available_linux_delegates_to_kwin(monkeypatch):
    from wondershot import capture
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("wondershot.kwin.kwin_available", lambda: False)
    assert capture.window_capture_available() is False
    monkeypatch.setattr("wondershot.kwin.kwin_available", lambda: True)
    assert capture.window_capture_available() is True
```

- [x] **Step 2: Run — verify failure**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_win_factories.py -v
```

Expected: FAIL with `AttributeError: module 'wondershot.capture' has no attribute 'create_capture_manager'`.

- [x] **Step 3: Implement the factory** — in `wondershot/capture.py`, add `import sys` to the imports block and append at the end of the file:

```python
# -- platform factory (WS-E seam) --------------------------------------------

def window_capture_available() -> bool:
    """Is no-picker active-window capture possible on this platform?

    Windows: always (ctypes GetForegroundWindow). Linux: KDE only
    (KWin scripting — see kwin.py).
    """
    if sys.platform == "win32":
        return True
    from . import kwin
    return kwin.kwin_available()


def create_capture_manager(settings, parent=None):
    """sys.platform factory mirroring hotkey.create_hotkey_backend.

    Linux behavior is byte-identical: same class, same constructor.
    """
    if sys.platform == "win32":
        from .wincapture import WinCaptureManager
        return WinCaptureManager(settings, parent)
    return CaptureManager(settings, parent)
```

(Note `from . import kwin` + `kwin.kwin_available()` — attribute access, not `from .kwin import kwin_available` — so the test's monkeypatch of `wondershot.kwin.kwin_available` takes effect.)

- [x] **Step 4: Wire app.py**

In `wondershot/app.py` change the import (line 14):

```python
from .capture import create_capture_manager, unique_path, timestamp_name, window_capture_available
```

Change line 70:

```python
        self.capture = create_capture_manager(self.settings, self)
```

Replace lines 90-92:

```python
        from .kwin import kwin_available
        self.kwin_ok = kwin_available()
        self.gallery.kwin_ok = self.kwin_ok  # gates the CaptureWindow button
```

with:

```python
        # "Window" capture works on KDE (KWin scripting) and on Windows
        # (GetForegroundWindow); the attribute keeps its historical name.
        self.kwin_ok = window_capture_available()
        self.gallery.kwin_ok = self.kwin_ok  # gates the CaptureWindow button
```

- [x] **Step 5: Disable the cursor toggle on Windows** — in `wondershot/capture_window.py`, add `import sys` to the imports and replace lines 56-60:

```python
        cursor = toggle("Capture cursor", "capture_cursor",
                        "Include the pointer (Spectacle backend)")
        if sys.platform == "win32":
            # mss grabs via BitBlt and cannot composite the cursor
            cursor.setEnabled(False)
            cursor.setToolTip("Not available on Windows (the capture "
                              "backend cannot include the pointer)")
        elif not shutil.which("spectacle"):
            cursor.setEnabled(False)
            cursor.setToolTip("Needs the Spectacle backend")
```

- [x] **Step 6: Run tests + full suite (the Linux-identity pin)**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_win_factories.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS — especially `test_capture_crop.py`, `test_capture_window_mode.py`, `test_hide_for_capture.py` untouched.

- [x] **Step 7: Commit**

```bash
git add wondershot/capture.py wondershot/app.py wondershot/capture_window.py tests/test_win_factories.py && git commit -m "feat: platform factory for capture; window-mode gate; cursor toggle honest on Windows"
```

---### Task 7: VM MILESTONE A — capture backends verified on the real desktop

**Files:** none committed (throwaway probe scripts under `/tmp` + `C:/dev`)

- [ ] **Step 1: Deploy the branch**

```bash
cd /home/jack/GitHub/grabbit-wt/win-port
git archive --format=tar.gz -o /tmp/ws.tar.gz HEAD
vscp /tmp/ws.tar.gz developer@192.168.122.175:C:/dev/
vssh "cd C:\dev\wondershot && tar xzf C:\dev\ws.tar.gz"
vssh "cd C:\dev\wondershot && .venv\Scripts\pip install -e . --no-deps --no-index"
```

(The `pip install -e` re-run is needed because pyproject changed in Task 3.)

- [ ] **Step 2: Suite on the VM**

```bash
vssh "cd C:\dev\wondershot && set QT_QPA_PLATFORM=offscreen&& set PATH=C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin;%PATH%&& .venv\Scripts\python -m pytest tests/ -q"
```

Expected: baseline + all new tests pass ON WINDOWS (the win tests use fakes, so they pass anywhere; the Linux-only suites keep their honest skips).

- [ ] **Step 3: Write the capture smoke script locally**

```python
# /tmp/smoke_capture.py — runs ON THE VM's interactive desktop
"""Smoke: real mss fullscreen grab + real ctypes active-window capture."""
import os
import sys
import traceback

LOG = r"C:\dev\smoketest\capture.log"
os.makedirs(r"C:\dev\smoketest", exist_ok=True)
log = open(LOG, "w")
try:
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from wondershot.wincapture import WinCaptureManager, active_window_rect

    class S:
        library_dir = r"C:\dev\smoketest"
        capture_delay = 0
        capture_cursor = False

    m = WinCaptureManager(S())
    results = []
    m.captured.connect(lambda p: results.append(("captured", p)))
    m.failed.connect(lambda msg: results.append(("failed", msg)))
    m.capture_fullscreen()
    m.capture_active_window()
    print("active_window_rect:", active_window_rect(), file=log)
    for r in results:
        print(*r, file=log)
    print("DONE", file=log)
except Exception:
    traceback.print_exc(file=log)
finally:
    log.close()
```

- [ ] **Step 4: Run it on the interactive desktop via schtasks**

```bash
vscp /tmp/smoke_capture.py developer@192.168.122.175:C:/dev/
vssh "schtasks /create /tn wsprobe /tr \"C:\dev\wondershot\.venv\Scripts\python.exe C:\dev\smoke_capture.py\" /sc once /st 00:00 /it /f && schtasks /run /tn wsprobe"
sleep 15
vssh "type C:\dev\smoketest\capture.log && dir C:\dev\smoketest"
```

Expected log: an `active_window_rect: (x, y, w, h)` tuple (not None), two `captured C:\dev\smoketest\Screenshot_*.png` lines, `DONE`. Expected dir: two PNGs with plausible sizes (fullscreen ~ hundreds of KB; the window crop smaller).

- [ ] **Step 5: Pull the PNGs back and LOOK at them**

```bash
vssh "dir /b C:\dev\smoketest\*.png"
# scp each listed name:
vscp "developer@192.168.122.175:C:/dev/smoketest/<name>.png" /tmp/
```

Read each `/tmp/<name>.png` with the Read tool. Verify: the fullscreen one shows the actual VM desktop (taskbar, wallpaper); the active-window one is cropped to a single window's frame, not the full desktop and not a black rectangle. If black: the scheduled task likely ran non-interactively — confirm `/it` was present and a user session is logged in (`vssh "query session"`).

- [ ] **Step 6: Clean up the task**

```bash
vssh "schtasks /delete /tn wsprobe /f"
```

- [ ] **Step 7: Record findings** — append a dated note to the worktree's `ROADMAP.md` if anything surprised you (DPI, monitor geometry, mss quirks). Commit only if you wrote notes.

---

### Task 8: `winrecord.py` pure parts — args builders, ddagrab probe, dshow discovery

**Files:**
- Create: `wondershot/winrecord.py`
- Test: `tests/test_winrecord.py` (create)

- [x] **Step 1: Write the failing tests**

```python
# tests/test_winrecord.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_module_imports_cleanly_on_linux():
    import wondershot.winrecord  # noqa: F401


# -- args builders -------------------------------------------------------------

def test_ddagrab_args_use_lavfi_with_hwdownload(tmp_path):
    from wondershot.winrecord import ddagrab_args
    tmp = str(tmp_path / "r.mp4")
    args = ddagrab_args(tmp, fps=30, audio_device="")
    assert args[:2] == ["-y", "-hide_banner"]
    i = args.index("-i")
    assert args[i - 2:i] == ["-f", "lavfi"]
    assert args[i + 1] == "ddagrab=framerate=30,hwdownload,format=bgra"
    assert "libx264" in args and "yuv420p" in args
    assert args[-1] == tmp
    assert "dshow" not in args and "-c:a" not in args


def test_ddagrab_args_with_audio_device(tmp_path):
    from wondershot.winrecord import ddagrab_args
    args = ddagrab_args(str(tmp_path / "r.mp4"), fps=30,
                        audio_device="Microphone (Realtek Audio)")
    i = args.index("dshow")
    assert args[i - 1] == "-f"
    assert args[i + 2] == "audio=Microphone (Realtek Audio)"
    assert "aac" in args


def test_gdigrab_args_fallback(tmp_path):
    from wondershot.winrecord import gdigrab_args
    tmp = str(tmp_path / "r.mp4")
    args = gdigrab_args(tmp, fps=30, audio_device="")
    i = args.index("gdigrab")
    assert args[i - 1] == "-f"
    assert "desktop" in args
    assert "libx264" in args and args[-1] == tmp


# -- dshow device discovery -----------------------------------------------------

DSHOW_OUTPUT = """\
[dshow @ 0000020] "Integrated Camera" (video)
[dshow @ 0000020]   Alternative name "@device_pnp_...."
[dshow @ 0000020] "Microphone (Realtek(R) Audio)" (audio)
[dshow @ 0000020]   Alternative name "@device_cm_...."
[dshow @ 0000020] "Stereo Mix (Realtek(R) Audio)" (audio)
dummy: Immediate exit requested
"""


def test_parse_dshow_audio_devices():
    from wondershot.winrecord import parse_dshow_audio_devices
    assert parse_dshow_audio_devices(DSHOW_OUTPUT) == [
        "Microphone (Realtek(R) Audio)",
        "Stereo Mix (Realtek(R) Audio)",
    ]


def test_parse_dshow_audio_devices_empty():
    from wondershot.winrecord import parse_dshow_audio_devices
    assert parse_dshow_audio_devices("no devices here") == []


def test_pick_audio_device_prefers_settings_match():
    from wondershot.winrecord import pick_audio_device
    devs = ["Microphone (Realtek(R) Audio)", "Stereo Mix (Realtek(R) Audio)"]
    assert pick_audio_device(devs, "Stereo Mix (Realtek(R) Audio)") == \
        "Stereo Mix (Realtek(R) Audio)"
    assert pick_audio_device(devs, "Gone Device") == devs[0]
    assert pick_audio_device(devs, "") == devs[0]
    assert pick_audio_device([], "anything") == ""


# -- ddagrab probe ----------------------------------------------------------------

def test_have_ddagrab_parses_filters_output(monkeypatch):
    import subprocess
    from wondershot import winrecord
    winrecord.reset_probe_cache()

    def fake_run(args, timeout=60):
        return subprocess.CompletedProcess(
            args, 0, stdout=" ... ddagrab          Grab desktop ...", stderr="")

    monkeypatch.setattr(winrecord, "run_ffmpeg", fake_run)
    assert winrecord.have_ddagrab() is True


def test_have_ddagrab_false_without_filter(monkeypatch):
    import subprocess
    from wondershot import winrecord
    winrecord.reset_probe_cache()
    monkeypatch.setattr(
        winrecord, "run_ffmpeg",
        lambda args, timeout=60: subprocess.CompletedProcess(
            args, 0, stdout="gdigrab only here", stderr=""))
    assert winrecord.have_ddagrab() is False


def test_have_ddagrab_false_when_ffmpeg_missing(monkeypatch):
    from wondershot import winrecord
    from wondershot.ffmpegutil import FfmpegMissing
    winrecord.reset_probe_cache()

    def boom(args, timeout=60):
        raise FfmpegMissing()

    monkeypatch.setattr(winrecord, "run_ffmpeg", boom)
    assert winrecord.have_ddagrab() is False
```

- [x] **Step 2: Run — verify failure**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_winrecord.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wondershot.winrecord'`.

- [x] **Step 3: Implement**

```python
# wondershot/winrecord.py
"""Windows screen recorder: ffmpeg ddagrab (Desktop Duplication, hw path)
with gdigrab fallback, dshow microphone, QProcess lifecycle.

Mirrors record.py's ScreenRecorder contract exactly: signals
started/stopping/finished/failed/tick, .rendering tmp + salvage, a
1-second watchdog, and a stop-escalation ladder. The graceful stop is
ffmpeg's own: 'q' on stdin finalizes the mp4 (the SIGINT-as-EOS analog);
escalation is QProcess.terminate() then kill(), and a killed pipeline's
partial file is KEPT (record.py's salvage mandate).

No GStreamer on Windows. Import-safe everywhere; nothing Windows-only
happens at import time.
"""

from __future__ import annotations

import os
import re
import shutil
import time

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .ffmpegutil import FfmpegMissing, ffmpeg_path, run_ffmpeg
from .record import log_dir, sweep_stale_tmp


# -- ffmpeg argument builders (pure) -----------------------------------------

def _encode_args(audio_device: str) -> list[str]:
    args = ["-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p"]
    if audio_device:
        args += ["-c:a", "aac", "-b:a", "160k"]
    return args


def _audio_input(audio_device: str) -> list[str]:
    if not audio_device:
        return []
    return ["-f", "dshow", "-i", f"audio={audio_device}"]


def ddagrab_args(tmp: str, fps: int = 30, audio_device: str = "") -> list[str]:
    """Desktop Duplication grab: hw frames, hwdownload for libx264."""
    return (["-y", "-hide_banner",
             "-f", "lavfi",
             "-i", f"ddagrab=framerate={fps},hwdownload,format=bgra"]
            + _audio_input(audio_device)
            + _encode_args(audio_device)
            + [tmp])


def gdigrab_args(tmp: str, fps: int = 30, audio_device: str = "") -> list[str]:
    """GDI fallback when the ffmpeg build lacks the ddagrab filter."""
    return (["-y", "-hide_banner",
             "-f", "gdigrab", "-framerate", str(fps),
             "-i", "desktop"]
            + _audio_input(audio_device)
            + _encode_args(audio_device)
            + [tmp])


# -- capability probe -----------------------------------------------------------

_ddagrab_cache: bool | None = None


def reset_probe_cache() -> None:
    """Test hook."""
    global _ddagrab_cache
    _ddagrab_cache = None


def have_ddagrab() -> bool:
    """Does this ffmpeg build ship the ddagrab lavfi source?"""
    global _ddagrab_cache
    if _ddagrab_cache is None:
        try:
            cp = run_ffmpeg(["-hide_banner", "-filters"], timeout=15)
            _ddagrab_cache = "ddagrab" in (cp.stdout or "")
        except (FfmpegMissing, OSError):
            _ddagrab_cache = False
    return _ddagrab_cache


# -- dshow microphone discovery ---------------------------------------------------

def parse_dshow_audio_devices(text: str) -> list[str]:
    """Device names from `ffmpeg -list_devices true -f dshow -i dummy`.

    Lines look like:  [dshow @ ...] "Microphone (Realtek)" (audio)
    """
    devices = []
    for line in text.splitlines():
        if "(audio)" not in line:
            continue
        m = re.search(r'"([^"]+)"', line)
        if m:
            devices.append(m.group(1))
    return devices


def list_dshow_audio_devices() -> list[str]:
    try:
        cp = run_ffmpeg(["-hide_banner", "-list_devices", "true",
                         "-f", "dshow", "-i", "dummy"], timeout=15)
    except (FfmpegMissing, OSError):
        return []
    # the device list goes to stderr and the command "fails" by design
    return parse_dshow_audio_devices(cp.stderr or "")


def pick_audio_device(devices: list[str], preferred: str) -> str:
    """settings.mic_device match, else the first device, else ''."""
    if preferred and preferred in devices:
        return preferred
    return devices[0] if devices else ""
```

- [x] **Step 4: Run tests + suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_winrecord.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add wondershot/winrecord.py tests/test_winrecord.py && git commit -m "feat: winrecord pure parts — ddagrab/gdigrab args, probe, dshow discovery"
```

---

### Task 9: `WinScreenRecorder` lifecycle — start, q-stop, escalation, watchdog, salvage

The lifecycle is tested on Linux against a **Python stub child** (QProcess runs `sys.executable stub.py out.mp4`), exercising the exact code paths: graceful 'q' finalize, terminate→kill escalation against a signal-ignoring child, watchdog death detection, and partial-file salvage.

**Files:**
- Modify: `wondershot/winrecord.py` (append the class)
- Test: `tests/test_winrecord.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_winrecord.py`)

```python
# -- WinScreenRecorder lifecycle (Python stub child, runs anywhere) ------------

import sys
import time


class FakeSettings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.mic_enabled = False
        self.mic_device = ""
        self.screencast_token = ""


GRACEFUL_STUB = """\
import sys
out = sys.argv[-1]
with open(out, "wb") as f:
    f.write(b"mp4-header")
    f.flush()
    while True:
        ch = sys.stdin.read(1)
        if ch in ("q", ""):
            f.write(b"-finalized")
            break
sys.exit(0)
"""

WEDGED_STUB = """\
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)  # ignore terminate()
out = sys.argv[-1]
with open(out, "wb") as f:
    f.write(b"partial-footage")
    f.flush()
    while True:
        time.sleep(1)  # never reads stdin, never exits
"""

DYING_STUB = """\
import sys
out = sys.argv[-1]
with open(out, "wb") as f:
    f.write(b"partial-footage")
sys.exit(3)  # immediate death, like a mid-recording encoder error
"""


def _recorder(tmp_path, stub_src):
    from wondershot.winrecord import WinScreenRecorder
    stub = tmp_path / "stub.py"
    stub.write_text(stub_src)
    rec = WinScreenRecorder(
        FakeSettings(str(tmp_path)),
        program=sys.executable,
        args_builder=lambda tmp, fps=30, audio_device="":
            ["-u", str(stub), tmp])
    return rec


def wait_until(qapp, cond, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_start_emits_started_and_creates_tmp(qapp, tmp_path):
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    events = []
    rec.started.connect(lambda: events.append("started"))
    rec.failed.connect(lambda m: events.append(("failed", m)))
    rec.start()
    assert wait_until(qapp, lambda: events, 5)
    assert events[0] == "started"
    assert rec.recording is True
    assert os.path.dirname(rec._tmp).endswith(".rendering")
    rec.stop()
    wait_until(qapp, lambda: not rec.recording, 5)


def test_q_on_stdin_finalizes_and_emits_finished(qapp, tmp_path):
    """The 'q' graceful path is the SIGINT-as-EOS analog: exit 0, the
    finalized file moves out of .rendering into the library."""
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(lambda m: done.append(("failed", m)))
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    rec.stop()
    assert wait_until(qapp, lambda: done, 10)
    path = done[0]
    assert isinstance(path, str) and path.endswith(".mp4")
    assert os.path.dirname(path) == str(tmp_path)  # out of .rendering
    with open(path, "rb") as f:
        assert f.read() == b"mp4-header-finalized"
    assert rec.recording is False and rec._proc is None


def test_stop_emits_stopping_exactly_once(qapp, tmp_path):
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    stops, done = [], []
    rec.stopping.connect(lambda: stops.append(1))
    rec.finished.connect(done.append)
    rec.failed.connect(done.append)
    rec.stop()
    rec.stop()  # tray after toolbar: silent no-op
    assert stops == [1]
    assert wait_until(qapp, lambda: done, 10)


def test_escalation_kills_wedged_pipeline_and_keeps_partial(qapp, tmp_path):
    """ffmpeg can wedge ignoring 'q' (and SIGTERM in the stub, mirroring
    record.py's wedged-EOS forensics): the ladder must end in kill() and
    the partial recording must be KEPT."""
    rec = _recorder(tmp_path, WEDGED_STUB)
    rec.GRACE_MS = 400
    rec.KILL_MS = 900
    results = []
    rec.failed.connect(results.append)
    rec.finished.connect(results.append)
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    out_expected = rec._out
    rec.stop()
    assert wait_until(qapp, lambda: results, 10), \
        "escalation must finalize a stop-ignoring pipeline"
    assert rec.recording is False and rec._proc is None
    assert os.path.exists(out_expected)
    with open(out_expected, "rb") as f:
        assert f.read() == b"partial-footage"
    assert "partial" in results[0]


def test_watchdog_detects_death_and_salvages(qapp, tmp_path):
    """Encoder dies minutes in: failed fires without a stop click and
    the partial footage moves to the library (record.py mandate)."""
    rec = _recorder(tmp_path, DYING_STUB)
    failures = []
    rec.failed.connect(failures.append)
    rec.start()
    started = wait_until(qapp, lambda: rec.recording, 5)
    assert started
    out_expected = rec._out
    assert wait_until(qapp, lambda: failures, 5), \
        "watchdog must emit failed when the pipeline dies"
    assert rec.recording is False
    assert os.path.exists(out_expected)
    assert "partial" in failures[0]


def test_tick_emits_elapsed_while_recording(qapp, tmp_path):
    rec = _recorder(tmp_path, GRACEFUL_STUB)
    rec.start()
    assert wait_until(qapp, lambda: rec.recording, 5)
    rec._started_at = time.monotonic() - 65
    assert rec.elapsed_str() == "1:05"
    ticks = []
    rec.tick.connect(ticks.append)
    assert wait_until(qapp, lambda: ticks, 3)
    assert ticks[0].startswith("1:0")
    rec.stop()
    wait_until(qapp, lambda: not rec.recording, 5)


def test_available_tracks_ffmpeg(monkeypatch, tmp_path):
    from wondershot import ffmpegutil, winrecord
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: None)
    rec = winrecord.WinScreenRecorder(FakeSettings(str(tmp_path)))
    assert rec.available() is False
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert rec.available() is True
    ffmpegutil.reset_cache()


def test_start_without_ffmpeg_emits_failed(qapp, monkeypatch, tmp_path):
    from wondershot import ffmpegutil, winrecord
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: None)
    rec = winrecord.WinScreenRecorder(FakeSettings(str(tmp_path)))
    fails = []
    rec.failed.connect(fails.append)
    rec.start()
    assert fails and "ffmpeg" in fails[0]
    ffmpegutil.reset_cache()
```

- [ ] **Step 2: Run — verify failure**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_winrecord.py -v
```

Expected: new tests FAIL with `ImportError: cannot import name 'WinScreenRecorder'`.

- [ ] **Step 3: Implement** (append to `wondershot/winrecord.py`)

```python
class WinScreenRecorder(QObject):
    """ffmpeg-based Windows recorder with ScreenRecorder's contract."""

    started = Signal()
    stopping = Signal()  # a stop transition began (whichever control asked)
    finished = Signal(str)  # final file path
    failed = Signal(str)
    tick = Signal(str)  # elapsed time ("1:05"), once a second

    # Escalation ladder, mirroring record.py: 'q' (graceful mp4
    # finalize) -> terminate() -> kill(). A killed pipeline's partial
    # file is salvaged, never deleted.
    GRACE_MS = 5000
    KILL_MS = 10000
    FPS = 30

    def __init__(self, settings, parent=None, program=None,
                 args_builder=None):
        super().__init__(parent)
        self.settings = settings
        self.recording = False
        self._busy = False
        self._proc: QProcess | None = None
        self._tmp = self._out = None
        self._stopping = False
        self._watchdog: QTimer | None = None
        self._started_at: float | None = None
        self.log_path = ""
        self._program = program            # test seam; None = ffmpeg_path()
        self._args_builder = args_builder  # test seam; None = probe

    # -- public ------------------------------------------------------------

    def available(self) -> bool:
        from .ffmpegutil import have_ffmpeg
        return have_ffmpeg()

    def start(self) -> None:
        if self.recording or self._busy:
            return
        self._busy = True
        try:
            program = self._program or ffmpeg_path()
        except FfmpegMissing as e:
            self._busy = False
            self.failed.emit(str(e))
            return
        from .capture import timestamp_name, unique_path
        out = unique_path(self.settings.library_dir,
                          timestamp_name("Recording").replace(".png", ".mp4"))
        tmp_dir = os.path.join(self.settings.library_dir, ".rendering")
        os.makedirs(tmp_dir, exist_ok=True)
        sweep_stale_tmp(tmp_dir)
        tmp = os.path.join(tmp_dir, os.path.basename(out))
        self._tmp, self._out = tmp, out

        audio = ""
        if getattr(self.settings, "mic_enabled", False):
            audio = pick_audio_device(
                list_dshow_audio_devices(),
                getattr(self.settings, "mic_device", ""))
        builder = self._args_builder or (
            ddagrab_args if have_ddagrab() else gdigrab_args)
        args = builder(tmp, fps=self.FPS, audio_device=audio)

        logs = log_dir()
        os.makedirs(logs, exist_ok=True)
        self.log_path = os.path.join(logs, "recorder.log")
        try:
            with open(self.log_path, "w") as f:
                f.write(program + " " + " ".join(args) + "\n\n")
        except OSError:
            pass
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setStandardOutputFile(self.log_path, QProcess.Append)
        proc.start(program, args)
        if not proc.waitForStarted(5000):
            self._busy = False
            self._tmp = self._out = None
            self.failed.emit(f"could not start ffmpeg: {program}")
            return
        self._proc = proc
        self._start_watchdog()
        self._busy = False
        self.recording = True
        self._started_at = time.monotonic()
        self.started.emit()

    def stop(self) -> None:
        if self._stopping:
            return  # double-stop (tray + toolbar) must not double-finalize
        if self._proc is None:
            return
        self._stopping = True
        self.stopping.emit()
        if self._proc.state() != QProcess.NotRunning:
            # ffmpeg's interactive quit: finalizes the mp4 moov, exit 0 —
            # the SIGINT-as-EOS analog (no SIGINT across consoles on
            # Windows).
            self._proc.write(b"q")
        # Even if ffmpeg already died, finalize so finished/failed always
        # fires — the UI must never stay "Stopping".
        self._poll_exit(elapsed_ms=0)

    # -- internals ---------------------------------------------------------

    def elapsed_str(self) -> str:
        if not self.recording or self._started_at is None:
            return ""
        s = int(time.monotonic() - self._started_at)
        return f"{s // 60}:{s % 60:02d}"

    def _start_watchdog(self) -> None:
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._check_alive)
        self._watchdog.start()

    def _check_alive(self) -> None:
        if self._stopping:
            return  # _poll_exit owns the exit path now
        if (self._proc is not None
                and self._proc.state() == QProcess.NotRunning):
            self.recording = False
            tmp, out = self._tmp, self._out
            self._cleanup()
            partial = self._salvage_partial(tmp, out)
            self.failed.emit(
                f"recorder died: {self._log_tail()[:160]} "
                f"(full log: {self.log_path}){partial}")
            return
        self.tick.emit(self.elapsed_str())

    def _log_tail(self) -> str:
        try:
            with open(self.log_path, errors="replace") as f:
                lines = [ln for ln in f.read().strip().splitlines()
                         if "rror" in ln or "Invalid" in ln] or ["unknown"]
            return lines[-1]
        except OSError:
            return "unknown"

    @staticmethod
    def _salvage_partial(tmp, out) -> str:
        """KEEP whatever was written (record.py's salvage mandate)."""
        if not tmp or not os.path.exists(tmp):
            return ""
        if out and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            return f"; partial recording kept: {os.path.basename(out)}"
        os.unlink(tmp)  # zero bytes: nothing to salvage
        return ""

    def _poll_exit(self, elapsed_ms: int = 0, nudged: bool = False) -> None:
        if self._proc is None:
            return
        if self._proc.state() != QProcess.NotRunning:
            if elapsed_ms >= self.KILL_MS:
                self._proc.kill()
            elif elapsed_ms >= self.GRACE_MS and not nudged:
                self._proc.terminate()  # WM_CLOSE; some builds ignore it
                nudged = True
            QTimer.singleShot(
                200, lambda: self._poll_exit(elapsed_ms + 200, nudged))
            return
        self.recording = False
        ok = (self._proc.exitStatus() == QProcess.NormalExit
              and self._proc.exitCode() == 0 and self._tmp
              and os.path.exists(self._tmp)
              and os.path.getsize(self._tmp) > 0)
        tmp, out = self._tmp, self._out
        self._cleanup()
        if ok:
            shutil.move(tmp, out)
            self.finished.emit(out)
            return
        partial = self._salvage_partial(tmp, out)
        self.failed.emit(
            f"recording did not finalize: {self._log_tail()[:160]} "
            f"(log: {self.log_path}){partial}")

    def _cleanup(self) -> None:
        self._stopping = False
        if self._watchdog is not None:
            self._watchdog.stop()
            self._watchdog = None
        if self._proc is not None:
            self._proc.deleteLater()
        self._proc = None
        self._tmp = self._out = None
```

- [ ] **Step 4: Run tests + suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_winrecord.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS. The escalation test takes ~2 s (ladder timers shrunk); if `terminate()` on Linux kills the SIGTERM-ignoring stub anyway, the test still passes — the assertion is salvage+finalize, not which rung fired.

- [ ] **Step 5: Commit**

```bash
git add wondershot/winrecord.py tests/test_winrecord.py && git commit -m "feat: WinScreenRecorder — QProcess lifecycle with q-stop, escalation, watchdog, salvage"
```

---

### Task 10: Recorder factory + app wiring + Linux pin

**Files:**
- Modify: `wondershot/record.py` (add `sys` import + factory at end)
- Modify: `wondershot/app.py:74-75`
- Test: `tests/test_win_factories.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_win_factories.py`)

```python
# -- recorder factory ----------------------------------------------------------

def test_recorder_factory_linux_is_byte_identical(qapp, monkeypatch):
    from wondershot import record
    monkeypatch.setattr(sys, "platform", "linux")
    r = record.create_screen_recorder(_Settings())
    assert type(r) is record.ScreenRecorder


def test_recorder_factory_windows(qapp, monkeypatch):
    from wondershot import record
    from wondershot.winrecord import WinScreenRecorder
    monkeypatch.setattr(sys, "platform", "win32")
    r = record.create_screen_recorder(_Settings())
    assert type(r) is WinScreenRecorder


def test_win_recorder_has_screenrecorder_signal_contract(qapp):
    """app.py connects these five names blind; both classes must have them."""
    from wondershot.winrecord import WinScreenRecorder
    rec = WinScreenRecorder(_Settings())
    for name in ("started", "stopping", "finished", "failed", "tick"):
        assert hasattr(rec, name), name
    assert hasattr(rec, "recording") and hasattr(rec, "available")
    assert callable(rec.start) and callable(rec.stop)
    assert callable(rec.elapsed_str)
```

- [ ] **Step 2: Run — verify failure**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_win_factories.py -v
```

Expected: FAIL with `AttributeError: ... no attribute 'create_screen_recorder'`.

- [ ] **Step 3: Implement** — in `wondershot/record.py` add `import sys` to the imports block and append at the end:

```python
# -- platform factory (WS-E seam) ---------------------------------------------

def create_screen_recorder(settings, parent=None):
    """sys.platform factory mirroring create_capture_manager.

    Linux behavior is byte-identical: same class, same constructor.
    """
    if sys.platform == "win32":
        from .winrecord import WinScreenRecorder
        return WinScreenRecorder(settings, parent)
    return ScreenRecorder(settings, parent)
```

In `wondershot/app.py` replace lines 74-75:

```python
        from .record import ScreenRecorder
        self.recorder = ScreenRecorder(self.settings, self)
```

with:

```python
        from .record import create_screen_recorder
        self.recorder = create_screen_recorder(self.settings, self)
```

- [ ] **Step 4: Run tests + full suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_win_factories.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS, including the untouched `test_record.py`.

- [ ] **Step 5: Commit**

```bash
git add wondershot/record.py wondershot/app.py tests/test_win_factories.py && git commit -m "feat: recorder platform factory; app uses it; Linux pinned byte-identical"
```

---

### Task 11: VM MILESTONE B — real ddagrab recording on the desktop

**Files:** none committed (throwaway probe scripts)

- [ ] **Step 1: Deploy + suite**

```bash
cd /home/jack/GitHub/grabbit-wt/win-port
git archive --format=tar.gz -o /tmp/ws.tar.gz HEAD
vscp /tmp/ws.tar.gz developer@192.168.122.175:C:/dev/
vssh "cd C:\dev\wondershot && tar xzf C:\dev\ws.tar.gz"
vssh "cd C:\dev\wondershot && set QT_QPA_PLATFORM=offscreen&& set PATH=C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin;%PATH%&& .venv\Scripts\python -m pytest tests/ -q"
```

Expected: full suite green on Windows.

- [ ] **Step 2: Write the record smoke script locally**

```python
# /tmp/smoke_record.py — runs ON THE VM's interactive desktop
"""Smoke: real ddagrab recording — start, 6 s, stop via 'q', finalize."""
import os
import sys
import traceback

LOG = r"C:\dev\smoketest\record.log"
os.makedirs(r"C:\dev\smoketest", exist_ok=True)
log = open(LOG, "w")
try:
    # ffmpeg dir must be on PATH for ffmpeg_path() discovery
    os.environ["PATH"] = (r"C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin;"
                          + os.environ.get("PATH", ""))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from wondershot.winrecord import (
        WinScreenRecorder, have_ddagrab, list_dshow_audio_devices)
    print("have_ddagrab:", have_ddagrab(), file=log)
    print("dshow audio:", list_dshow_audio_devices(), file=log)

    class S:
        library_dir = r"C:\dev\smoketest"
        mic_enabled = False
        mic_device = ""

    rec = WinScreenRecorder(S())

    def done(tag):
        def _h(arg=""):
            print(tag, arg, file=log, flush=True)
            app.quit()
        return _h

    rec.started.connect(lambda: print("started", file=log, flush=True))
    rec.tick.connect(lambda t: print("tick", t, file=log, flush=True))
    rec.finished.connect(done("finished"))
    rec.failed.connect(done("failed"))
    rec.start()
    QTimer.singleShot(6000, rec.stop)
    QTimer.singleShot(30000, done("timeout"))
    app.exec()
    print("DONE", file=log)
except Exception:
    traceback.print_exc(file=log)
finally:
    log.close()
```

- [ ] **Step 3: Run via schtasks, inspect the log**

```bash
vscp /tmp/smoke_record.py developer@192.168.122.175:C:/dev/
vssh "schtasks /create /tn wsrec /tr \"C:\dev\wondershot\.venv\Scripts\python.exe C:\dev\smoke_record.py\" /sc once /st 00:00 /it /f && schtasks /run /tn wsrec"
sleep 45
vssh "type C:\dev\smoketest\record.log && dir C:\dev\smoketest\*.mp4"
```

Expected: `have_ddagrab: True`, `started`, several `tick 0:0X` lines, `finished C:\dev\smoketest\Recording_*.mp4`, `DONE`. The mp4 exists with size > 100 KB and `.rendering` is empty. If `failed` with a ddagrab error (e.g. no D3D11 device in the VM's GPU): note it, force the fallback by re-running with `rec._args_builder = gdigrab_args` patched into the smoke script (`from wondershot.winrecord import gdigrab_args; rec._args_builder = gdigrab_args`), and record in ROADMAP.md that the VM exercises the gdigrab rung. If `failed` with `width/height not divisible by 2` (odd desktop resolution + libx264/yuv420p): append `,crop=trunc(iw/2)*2:trunc(ih/2)*2` to the ddagrab lavfi graph (and add `-vf crop=trunc(iw/2)*2:trunc(ih/2)*2` to the gdigrab builder), update the args tests to match, and note it in ROADMAP.md.

- [ ] **Step 4: Prove the mp4 is playable** — cmd.exe does NOT glob wildcards for ffprobe, so resolve the exact name first:

```bash
vssh "dir /b C:\dev\smoketest\*.mp4"
# substitute the listed name:
vssh "C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name -of default=nw=1 C:\dev\smoketest\<exact-name>.mp4"
```

Expected: `codec_name=h264`, `duration=` ~5-7 seconds, no errors.

- [ ] **Step 5: Visual spot-check** — extract a frame and look at it:

```bash
vssh "C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg -y -ss 3 -i C:\dev\smoketest\<exact-name>.mp4 -frames:v 1 C:\dev\smoketest\frame.png"
vscp "developer@192.168.122.175:C:/dev/smoketest/frame.png" /tmp/
```

Read `/tmp/frame.png`: it must show the VM desktop (not black, not garbage).

- [ ] **Step 6: Clean up**

```bash
vssh "schtasks /delete /tn wsrec /f"
```

---

### Task 12: `WinHotkeyBackend` — RegisterHotKey message loop

Default binding: **Ctrl+Shift+PrintScreen** (`MOD_CONTROL|MOD_SHIFT` + `VK_SNAPSHOT`) — plain PrintScreen belongs to Windows' own Snipping Tool. The loop runs on a QThread (RegisterHotKey binds to the registering thread, which must pump messages); `pressed` is emitted cross-thread (queued, safe). All windll access happens inside `run()`/`stop()` — never at import or construction time (the Linux suite constructs the backend).

**Files:**
- Modify: `wondershot/hotkey.py`
- Test: `tests/test_hotkey.py` (modify + append)

- [ ] **Step 1: Update/extend the tests** — in `tests/test_hotkey.py`, replace `test_factory_picks_null_elsewhere` and append:

```python
def test_factory_picks_null_on_darwin(monkeypatch):
    from wondershot import hotkey
    monkeypatch.setattr(sys, "platform", "darwin")
    b = hotkey.create_hotkey_backend()
    assert isinstance(b, hotkey.NullHotkeyBackend)


def test_factory_picks_win_backend_on_windows(monkeypatch):
    from wondershot import hotkey
    monkeypatch.setattr(sys, "platform", "win32")
    b = hotkey.create_hotkey_backend()
    assert isinstance(b, hotkey.WinHotkeyBackend)
    assert isinstance(b, hotkey.HotkeyBackend)
    assert hasattr(b, "pressed")


def test_win_backend_constructs_without_windows(monkeypatch):
    """Constructing (NOT registering) must never touch ctypes.windll —
    the factory runs at app startup on every platform under test."""
    from wondershot import hotkey
    b = hotkey.WinHotkeyBackend()
    assert b.active is False


def test_win_hotkey_constants():
    """The documented default binding: Ctrl+Shift+PrintScreen."""
    from wondershot import hotkey
    assert hotkey.MOD_CONTROL == 0x0002
    assert hotkey.MOD_SHIFT == 0x0004
    assert hotkey.MOD_NOREPEAT == 0x4000
    assert hotkey.VK_SNAPSHOT == 0x2C
    assert hotkey.WM_HOTKEY == 0x0312
```

- [ ] **Step 2: Run — verify failure**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_hotkey.py -v
```

Expected: new tests FAIL (`no attribute 'WinHotkeyBackend'`); the old win32→Null test was replaced.

- [ ] **Step 3: Implement** — first adjust the imports at the top of `wondershot/hotkey.py`: change the QtCore import to `from PySide6.QtCore import QObject, QThread, Signal, Slot` and add `import ctypes` and `import threading` to the stdlib imports. Then append to the module:

```python
# -- Windows: RegisterHotKey message loop (WS-E) ------------------------------
#
# Default binding: Ctrl+Shift+PrintScreen. RegisterHotKey is bound to the
# registering thread, which must pump a message loop — so a dedicated
# QThread does both. Nothing here touches ctypes.windll at import or
# construction time; the Linux suite constructs these classes.

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_SNAPSHOT = 0x2C   # PrintScreen
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1


class _MSG(ctypes.Structure):
    # Portable field types (no ctypes.wintypes) so the class definition
    # is importable everywhere.
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


class _WinHotkeyThread(QThread):
    hotkey = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = threading.Event()
        self._ok = False
        self._native_tid = 0

    def wait_registered(self, timeout_ms: int) -> bool:
        self._registered.wait(timeout_ms / 1000)
        return self._ok

    def request_quit(self) -> None:
        if self._native_tid:
            ctypes.windll.user32.PostThreadMessageW(
                self._native_tid, WM_QUIT, 0, 0)

    def run(self) -> None:  # pragma: no cover — Windows only
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._native_tid = kernel32.GetCurrentThreadId()
        self._ok = bool(user32.RegisterHotKey(
            None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
            VK_SNAPSHOT))
        self._registered.set()
        if not self._ok:
            return  # e.g. another app owns the chord; backend stays inactive
        msg = _MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.hotkey.emit()
        user32.UnregisterHotKey(None, HOTKEY_ID)


class WinHotkeyBackend(HotkeyBackend):
    """Global Ctrl+Shift+PrintScreen via user32.RegisterHotKey."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None

    def register(self) -> bool:
        if self._thread is not None:
            return self.active
        self._thread = _WinHotkeyThread(self)
        self._thread.hotkey.connect(self.pressed)
        self._thread.start()
        self.active = self._thread.wait_registered(2000)
        return self.active

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.request_quit()
            self._thread.wait(2000)
            self._thread = None
            self.active = False
```

And update the factory:

```python
def create_hotkey_backend(parent=None) -> HotkeyBackend:
    if sys.platform.startswith("linux"):
        return KGlobalAccelBackend(parent)
    if sys.platform == "win32":
        return WinHotkeyBackend(parent)
    return NullHotkeyBackend(parent)
```

Also extend the module docstring's first paragraph with one line: `On Windows: WinHotkeyBackend — RegisterHotKey, default Ctrl+Shift+PrintScreen.`

- [ ] **Step 4: Run tests + suite**

```bash
/home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/test_hotkey.py -v && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add wondershot/hotkey.py tests/test_hotkey.py && git commit -m "feat: WinHotkeyBackend — RegisterHotKey loop, default Ctrl+Shift+PrintScreen"
```

---

### Task 13: VM MILESTONE C — the full app on the desktop: tray, hotkey, captures

**Files:** none committed (throwaway launch/probe scripts)

- [ ] **Step 1: Deploy + suite** (same as Task 11 Step 1; run both commands, expect green)

- [ ] **Step 2: Launch the app on the interactive desktop**

Write `/tmp/run_app.cmd` locally:

```bat
@echo off
set PATH=C:\dev\ffmpeg\ffmpeg-8.1.1-essentials_build\bin;%PATH%
cd /d C:\dev\wondershot
.venv\Scripts\python.exe -c "import sys; from wondershot.cli import main; sys.exit(main([]))" > C:\dev\smoketest\app.log 2>&1
```

```bash
vscp /tmp/run_app.cmd developer@192.168.122.175:C:/dev/
vssh "schtasks /create /tn wsapp /tr C:\dev\run_app.cmd /sc once /st 00:00 /it /f && schtasks /run /tn wsapp"
sleep 20
vssh "tasklist | findstr python"
vssh "type C:\dev\smoketest\app.log"
```

Expected: a python.exe process is running; app.log is empty or free of tracebacks. (Any traceback here is a port bug — fix it in the worktree, redeploy, relaunch before continuing.)

- [ ] **Step 3: Screenshot the desktop and LOOK**

Write `/tmp/shot.ps1` locally:

```powershell
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save("C:\dev\shot.png")
```

```bash
vscp /tmp/shot.ps1 developer@192.168.122.175:C:/dev/
vssh "schtasks /create /tn wsshot /tr \"powershell.exe -ExecutionPolicy Bypass -File C:\dev\shot.ps1\" /sc once /st 00:00 /it /f && schtasks /run /tn wsshot"
sleep 8
vscp "developer@192.168.122.175:C:/dev/shot.png" /tmp/
```

Read `/tmp/shot.png`. Expected: the gallery window is visible (cli with no args shows it) and/or the wondershot tray icon sits in the system tray (it may be in the tray overflow — if unsure, that's acceptable; the hotkey test below is the functional proof).

- [ ] **Step 4: Fire the hotkey from the interactive desktop**

Write `/tmp/hotkey.ps1` locally:

```powershell
# SendKeys CANNOT send PrintScreen ({PRTSC} is documented "reserved for
# future use" and is a no-op) — synthesize the chord with keybd_event,
# which goes through the input queue and DOES trigger RegisterHotKey.
$sig = '[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);'
$k = Add-Type -MemberDefinition $sig -Name K -Namespace Win -PassThru
Start-Sleep -Seconds 2
$k::keybd_event(0x11, 0, 0, [UIntPtr]::Zero)  # Ctrl down
$k::keybd_event(0x10, 0, 0, [UIntPtr]::Zero)  # Shift down
$k::keybd_event(0x2C, 0, 0, [UIntPtr]::Zero)  # PrintScreen down (VK_SNAPSHOT)
$k::keybd_event(0x2C, 0, 2, [UIntPtr]::Zero)  # up (KEYEVENTF_KEYUP)
$k::keybd_event(0x10, 0, 2, [UIntPtr]::Zero)
$k::keybd_event(0x11, 0, 2, [UIntPtr]::Zero)
Start-Sleep -Seconds 3
```

```bash
vssh "dir /b C:\Users\developer\Pictures\Screenshots 2>nul"   # note current library contents (settings.py _default_library = <Pictures>/Screenshots; confirm against app.log if a stored QSettings value overrides it)
vscp /tmp/hotkey.ps1 developer@192.168.122.175:C:/dev/
vssh "schtasks /create /tn wskey /tr \"powershell.exe -ExecutionPolicy Bypass -File C:\dev\hotkey.ps1\" /sc once /st 00:00 /it /f && schtasks /run /tn wskey"
sleep 12
vssh "dir /b C:\Users\developer\Pictures\Screenshots"
```

Expected: the hotkey triggers a **region** capture (app.py wires pressed→region), so the region overlay is now covering the VM desktop. Take another screenshot (rerun the wsshot task, scp, Read): you should SEE the dimmed frozen-frame overlay. Then complete a drag with PowerShell mouse_event or — simpler and sufficient — press Esc via SendKeys (`[System.Windows.Forms.SendKeys]::SendWait("{ESC}")` in a new ps1 via the same schtasks trick) and instead verify the *fullscreen* path end-to-end by sending the app a CLI command through the single-instance socket:

```bash
vssh "cd C:\dev\wondershot && .venv\Scripts\python.exe -c \"import sys; from wondershot.cli import main; sys.exit(main(['--fullscreen']))\""
sleep 5
vssh "dir /b C:\Users\developer\Pictures\Screenshots"
```

Expected: a new `Screenshot_*.png` appears in the library. scp it back and Read it — it must show the desktop. (Note: `--fullscreen` over ssh works because the *running* app in the interactive session does the grab; the ssh process only delivers the socket command. This is the same trick Jack's Linux hotkeys use.)

If the overlay appeared in the screenshot in the first part of this step, region+hotkey are BOTH proven (hotkey fired → overlay shown). For a full region drag, drive the mouse on the interactive desktop with a ps1 using `[System.Windows.Forms.Cursor]::Position` + user32 `mouse_event` via Add-Type P/Invoke — do this in Task 14's checklist where it's required.

- [ ] **Step 5: Clean up tasks; leave the app running for Task 14**

```bash
vssh "schtasks /delete /tn wsshot /f & schtasks /delete /tn wskey /f"
```

- [ ] **Step 6: Fix-and-iterate** — any failure in steps 2-4 is a port bug: reproduce in a Linux test if at all possible (extend the fakes), fix in the worktree, commit, redeploy, rerun the failing step. Do not advance with a red milestone.

---

### Task 14: Definition of done — the Addendum 3 checklist, executed on the VM

Run every line of the spec's definition of done on the VM, record evidence, and update the consolidated checklist doc. The app from Task 13 should still be running (relaunch via the `wsapp` task if not).

**Files:**
- Modify: `docs/superpowers/plans/2026-06-07-desktop-checklist.md` (append a "Windows (win11-pam VM)" section with results)
- Modify: `ROADMAP.md` (WS-E status + any landmines found)

- [ ] **Step 1: Suite green on Windows** — rerun the VM suite command; record the counts. All Windows skips must be *honest* (POSIX-subprocess recorder tests, portal/D-Bus tests — nothing else newly skipped).

- [ ] **Step 2: App launches with tray** — evidence from Task 13 steps 2-3 (screenshot read). Re-verify `tasklist | findstr python` shows it running now.

- [ ] **Step 3: Hotkey fires a capture** — rerun Task 13 step 4's hotkey ps1; screenshot; Read: overlay visible. Esc to dismiss.

- [ ] **Step 4: Region capture produces a correct PNG** — drive a real drag. Write `/tmp/drag.ps1` locally:

```powershell
Add-Type -AssemblyName System.Windows.Forms
$sig = @'
[DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
'@
$m = Add-Type -MemberDefinition $sig -Name U32 -Namespace Win -PassThru
# fire the hotkey via keybd_event (SendKeys cannot send PrintScreen —
# {PRTSC} is "reserved for future use"), wait for the overlay, then
# drag 200,200 -> 600,500
foreach ($vk in 0x11, 0x10, 0x2C) { $m::keybd_event($vk, 0, 0, [UIntPtr]::Zero) }
foreach ($vk in 0x2C, 0x10, 0x11) { $m::keybd_event($vk, 0, 2, [UIntPtr]::Zero) }
Start-Sleep -Seconds 2
[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(200, 200)
$m::mouse_event(0x0002, 0, 0, 0, 0)   # left down
Start-Sleep -Milliseconds 300
foreach ($i in 1..10) {
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point((200 + $i * 40), (200 + $i * 30))
    Start-Sleep -Milliseconds 50
}
$m::mouse_event(0x0004, 0, 0, 0, 0)   # left up
Start-Sleep -Seconds 3
```

Run via schtasks (`/tn wsdrag`, `/it`, same pattern as before). Then `dir /b` the library, scp the newest PNG, Read it: it must be a ~400x300 crop of the desktop region, not the full screen. Delete the task.

- [ ] **Step 5: Fullscreen + window capture produce correct PNGs** — fullscreen: rerun `--fullscreen` via the running app's socket (Task 13 step 4). Window mode has no CLI flag, so prove the engine instead: rerun Task 7's `smoke_capture.py` via schtasks `/it` (real `WinCaptureManager.capture_active_window()` on the interactive desktop) — that is exactly the object and method the tray "Window" action calls (wired through `create_capture_manager`, covered by the factory tests). scp + Read both PNGs.

- [ ] **Step 6: Recording produces a playable mp4** — evidence from Task 11 (ffprobe + frame Read). Rerun if the recorder changed since. ALSO exercise the in-app path: with the app running, schtasks a python one-liner on the desktop is overkill — instead verify via the gallery Record button manually-adjacent path: rerun `smoke_record.py` and accept it as the engine proof (the app wires the same object through `create_screen_recorder` — covered by factory tests).

- [ ] **Step 7: Editor annotates + sidecar persists** — scripted, offscreen is fine (no desktop needed):

```bash
vssh "cd C:\dev\wondershot && set QT_QPA_PLATFORM=offscreen&& .venv\Scripts\python -m pytest tests/test_editor.py tests/test_sidecar.py tests/test_editor_sidecar.py tests/test_items_serialize.py -q"
```

Expected: green — these suites are the sidecar/editor behavior executed on Windows paths (case-insensitivity, backslashes).

- [ ] **Step 8: Update the checklist doc + ROADMAP** — append to `docs/superpowers/plans/2026-06-07-desktop-checklist.md` a `## Windows (win11-pam VM) — WS-E definition of done` section listing each item above with PASS/FAIL + the evidence (file names, suite counts, which screenshots were read). Update `ROADMAP.md`'s WS-E entry: what shipped, the documented gaps (no cursor in captures; window mode = active window only; mic depends on dshow devices; scroll capture not on Windows — needs a FrameSource; step capture follow-up; packaging out of scope). Per Addendum 3 sequencing item 4, also update the `windev` skill if anything about driving this VM changed (paths, staged wheels, the schtasks/keybd_event recipes). Commit:

```bash
cd /home/jack/GitHub/grabbit-wt/win-port && git add docs/superpowers/plans/2026-06-07-desktop-checklist.md ROADMAP.md && git commit -m "docs: Windows port definition-of-done results + WS-E roadmap status"
```

- [ ] **Step 9: Stop the app on the VM, clean up scheduled tasks**

```bash
vssh "schtasks /delete /tn wsapp /f & schtasks /delete /tn wsprobe /f 2>nul & schtasks /delete /tn wsdrag /f 2>nul & taskkill /im python.exe /f"
```

- [ ] **Step 10: Final Linux suite in the worktree** (the byte-identity gate before handoff):

```bash
cd /home/jack/GitHub/grabbit-wt/win-port && /home/jack/GitHub/grabbit/.venv/bin/python -m pytest tests/ -q
```

Expected: green. The branch is ready for review/merge (use superpowers:finishing-a-development-branch).

---

## Known constraints & documented gaps (carry into ROADMAP)

- **Cursor capture**: unsupported on Windows (mss/BitBlt); the toggle is disabled with a tooltip (Task 6).
- **Window mode**: active-window only — Windows has no compositor window-picker; the tray/panel "Window" entries work via `GetForegroundWindow`.
- **Recording**: ddagrab preferred, gdigrab fallback (probed once per process via `-filters`). Pause/resume, region recording: not ported (same status as Linux).
- **Scroll capture**: gated off on Windows (`scroll_capture_available()` requires GStreamer); the WS-D FrameSource seam is the future port path — do NOT attempt it here.
- **Hotkey**: fixed default Ctrl+Shift+PrintScreen; no rebinding UI (matches Linux, where the binding lives in System Settings).
- **Packaging/installer/signing/autostart**: out of scope per Addendum 3 (runs from the checkout + venv).
