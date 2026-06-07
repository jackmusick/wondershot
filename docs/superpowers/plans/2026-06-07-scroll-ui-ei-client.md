# Track 4b: Scroll-capture UI + EI client

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Promote scroll capture from the `--scroll-spike` CLI harness to a real
mode ("Scrolling capture" in the tray menu and the capture panel), with the
stitched PNG landing in the library through the normal captured path (quick
bar / preview / clipboard all apply), plus a minimal EI (libei) client for the
RECEIVE path so `spikes/inputcapture_probe.py` can complete the EIS handshake
and print pointer-button events with timestamps. NO step-capture product UI —
the interception-semantics question (do apps still get clicks while we
listen?) goes on the manual checklist as the final probe run.

**Architecture:**

- *Scroll mode state machine* — a new `ScrollCaptureController` QObject in
  `wondershot/scrollsource.py` (idle → running → idle): builds a FrameSource
  (injectable factory — tests use a fake) + `ScrollStitcher`, relays frames
  through a QObject slot (so cross-thread delivery from the GStreamer
  streaming thread is QUEUED — this fixes the direct-connection caveat
  documented in scrollsource.py's module docstring), and on `stop()` saves
  the stitched PNG via `capture.unique_path`/`timestamp_name` and emits
  `captured(path)`. Fully testable headless with a fake frame source.
- *Routing* — `app.trigger_capture` gains a `"scroll"` mode entry exactly like
  `"window-auto"`: the existing `gallery.hide_for_capture()` path hides all
  our windows first, then the singleShot fires `_begin_scroll`. The
  controller's `captured` feeds `app._on_captured(path)` — the SAME method
  every screenshot uses — so clipboard/preview/quick-bar/tray-toast behavior
  is inherited, not reimplemented. `failed` feeds `_on_capture_failed`.
- *Stop pill* — `ScrollStopPill` in `wondershot/capture_window.py`: small
  frameless always-on-top "Scrolling — click to finish" button. Like
  `countdown.CountdownOverlay` (read its module docstring), the compositor
  places it; it is short-lived so NO KWin position rule is written. Shown
  when the controller's `started` fires (portal grant complete); clicking it
  (or Esc) stops the capture. The tray "Scrolling capture" entry doubles as
  the SECOND finish path while a session runs (spec: "Ctrl+click tray or
  click Stop to finish") via `_scroll_tray_action`.
- *Gating* — module-level `scroll_capture_available()` in scrollsource.py:
  gi (`_HAVE_GIO`) + GStreamer (`Gst` import) + numpy (`stitch` import).
  Explicitly NOT gated on KDE/kwin_ok — portal ScreenCast is desktop-neutral
  (per spec Addendum 2 Track 4b). `app.scroll_ok` is probed once in
  `GrabbitApp.__init__` and mirrored onto the gallery (same pattern as
  `kwin_ok`), gating the tray action and the capture panel button.
- *Fresh portal pick* — already done (stitch-v2): `ScreenCastFrameSource`
  overrides `_restore_token()`/`_save_restore_token()`. Do not touch.
- *EI client* — snegg is NOT on PyPI (`https://pypi.org/pypi/snegg/json` →
  404, verified 2026-06-07 during plan prep; Task 5 re-verifies with pip).
  So: NO `wondershot[stepcapture]` extra (it would be empty or point at a
  nonexistent dist), and a new `wondershot/ei.py` — a minimal ctypes binding
  against the system `libei.so.1` (Fedora package `libei`, 1.5.0 installed on
  Jack's box), RECEIVE path only: receiver context, backend-fd setup,
  handshake (CONNECT / SEAT_ADDED → bind pointer+button capabilities),
  BUTTON_BUTTON decoding with timestamps. All enum values and exported
  symbols below were verified against libei 1.5.0 `src/libei.h` and
  `nm -D /usr/lib64/libei.so.1`. The wrapper calls the library through a
  `lib` object attribute, so unit tests inject a plain-Python fake "lib" —
  the feasible analogue of the brief's "fake socket" (the wire parsing lives
  in C; what we own and test is the handshake/event state machine).
- *Probe* — `spikes/inputcapture_probe.py` is extended: SetPointerBarriers +
  Enable (events only flow once capture activates), Activated/Deactivated
  signal findings, and `observe_events` tries snegg → `wondershot.ei` →
  raw-read fallback. Manual-run only, as before.

**Files NOT touched:** `stitch.py`, `record.py`, `editor.py`, `hotkey.py`
(read its docstring before touching anything D-Bus: a malformed KGlobalAccel
call aborts KWin — the probe keeps the same defensive posture: portal daemon
only, explicit GLib.Variant types, finite timeouts). Track 4a owns
`editor.py`/`simplify.py` — zero overlap.

**Settings keys:** this plan adds NO new settings keys read during widget
construction (gating is an availability probe, not a setting). Task 8 step 2
verifies this against the duplicated `_Settings` test stubs anyway — that
class of failure crashed the batch-3 merge.

**Tech Stack:** Python 3, PySide6, numpy (`[spike]` extra — the controller
imports `stitch` lazily so the bare package still imports), ctypes + system
libei.so.1 (no pip dep), Gio/GLib via system `gi` for the probe (manual run
with system python only — never in pytest). pytest.

**Execution environment:** The orchestrator will cherry-pick the plan commit into your branch before you start; just verify the plan file exists in your worktree.
Work in the worktree at `/home/jack/GitHub/grabbit-wt/scroll-ei` (branched
from `main`). Set up the venv there:

```bash
cd /home/jack/GitHub/grabbit-wt/scroll-ei
python -m venv .venv
.venv/bin/pip install -e ".[spike]" pytest
```

Run ALL tests with `QT_QPA_PLATFORM=offscreen`:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -x -q
```

## File Structure

```
wondershot/
  scrollsource.py        # MODIFY: + scroll_capture_available(), ScrollCaptureController
  capture_window.py      # MODIFY: + ScrollStopPill; CaptureWindow scroll_mode param/button
  app.py                 # MODIFY: scroll_ok probe, tray action, trigger_capture routing,
                         #         _begin_scroll/_on_scroll_* handlers
  gallery.py             # MODIFY: pass scroll_mode into CaptureWindow (1 line)
  cli.py                 # NO CHANGE (regression test pins --scroll-spike)
  ei.py                  # NEW: ctypes libei RECEIVE-path binding
spikes/
  inputcapture_probe.py  # MODIFY: barriers + Enable + EI event loop via wondershot.ei
tests/
  test_scrollcontroller.py   # NEW
  test_scroll_pill.py        # NEW
  test_scroll_mode.py        # NEW (app routing)
  test_capture_window_mode.py # MODIFY: scroll button cases
  test_cli_scroll_spike.py   # NEW
  test_ei.py                 # NEW
pyproject.toml           # NO CHANGE (no stepcapture extra — snegg not on PyPI; Task 5)
ROADMAP.md               # MODIFY: WS-D findings + EI decision record
docs/superpowers/plans/2026-06-07-desktop-checklist.md  # MODIFY: manual items
```

---

## Task 1: `scroll_capture_available()` + `ScrollCaptureController` (scrollsource.py)

**Files:** `wondershot/scrollsource.py`, `tests/test_scrollcontroller.py`

### Step 1.1: Failing tests for availability + controller

- [x] Create `tests/test_scrollcontroller.py`:

```python
"""ScrollCaptureController: the testable mode state machine behind the
scroll-capture UI. Frames come from an injectable FrameSource (fake
here); stop() stitches and writes a PNG into the library, emitting
captured(path) so the app coordinator can reuse the normal captured
path (quick bar / preview / clipboard)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QImage


@pytest.fixture(scope="session")
def qapp():
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


class FakeSettings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.mic_enabled = False
        self.mic_device = ""
        self.noise_suppression = True
        self.screencast_token = ""


class FakeSource(QObject):
    frame = Signal(QImage)
    started = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.started_calls = 0
        self.stopped = False

    def start(self):
        self.started_calls += 1
        self.started.emit()

    def stop(self):
        self.stopped = True


def _img(color):
    img = QImage(64, 48, QImage.Format_RGB32)
    img.fill(color)
    return img


def make(qapp, tmp_path):
    from wondershot.scrollsource import ScrollCaptureController
    source = FakeSource()
    ctl = ScrollCaptureController(FakeSettings(str(tmp_path)),
                                  source_factory=lambda: source)
    return ctl, source


def test_happy_path_saves_png_and_emits_captured(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    got = []
    ctl.captured.connect(got.append)
    ctl.start()
    assert ctl.running
    source.frame.emit(_img("#336699"))
    qapp.processEvents()  # queued cross-thread delivery in production
    ctl.stop()
    assert source.stopped
    assert len(got) == 1
    path = got[0]
    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path).startswith("ScrollCapture_")
    saved = QImage(path)
    assert (saved.width(), saved.height()) == (64, 48)
    assert not ctl.running


def test_no_frames_emits_failed_and_no_file(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    fails, got = [], []
    ctl.failed.connect(fails.append)
    ctl.captured.connect(got.append)
    ctl.start()
    ctl.stop()
    assert got == []
    assert len(fails) == 1
    assert os.listdir(tmp_path) == []


def test_source_failure_is_forwarded_and_resets(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    fails = []
    ctl.failed.connect(fails.append)
    ctl.start()
    source.failed.emit("portal said no")
    assert fails == ["portal said no"]
    assert not ctl.running


def test_started_signal_is_relayed(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    hits = []
    ctl.started.connect(lambda: hits.append(1))
    ctl.start()
    assert hits == [1]


def test_double_start_is_noop(qapp, tmp_path):
    from wondershot.scrollsource import ScrollCaptureController
    calls = []

    def factory():
        calls.append(1)
        return FakeSource()

    ctl = ScrollCaptureController(FakeSettings(str(tmp_path)),
                                  source_factory=factory)
    ctl.start()
    ctl.start()
    assert calls == [1]


def test_stop_when_idle_is_noop(qapp, tmp_path):
    ctl, source = make(qapp, tmp_path)
    fails, got = [], []
    ctl.failed.connect(fails.append)
    ctl.captured.connect(got.append)
    ctl.stop()
    assert fails == [] and got == []


def test_availability_gate_is_a_function_not_kde(qapp):
    # Gate is gi + Gst + numpy — NOT kwin/KDE. We only pin the contract
    # shape here (callable returning bool); the truthiness depends on
    # what's installed on the box running the suite.
    from wondershot.scrollsource import scroll_capture_available
    assert isinstance(scroll_capture_available(), bool)
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_scrollcontroller.py -x -q`
- [x] Expected failure: `ImportError: cannot import name 'ScrollCaptureController' from 'wondershot.scrollsource'`

### Step 1.2: Implement

- [x] In `wondershot/scrollsource.py`, after the `ScreenCastFrameSource` class
  (before the `run_scroll_spike` section), add:

```python
# -- productized scroll mode ------------------------------------------------

def scroll_capture_available() -> bool:
    """Gate for the scroll-capture UI: gi + GStreamer + numpy.

    Deliberately NOT gated on KDE/kwin — portal ScreenCast is
    desktop-neutral (spec Addendum 2, Track 4b)."""
    if not _HAVE_GIO:
        return False
    try:
        _gst()
    except (ImportError, ValueError):
        return False
    try:
        from . import stitch  # noqa: F401 — needs numpy ([spike] extra)
    except ImportError:
        return False
    return True


class ScrollCaptureController(QObject):
    """Mode state machine behind the scroll-capture UI.

    idle -> running -> idle. start() builds a FrameSource (injectable
    for tests) + ScrollStitcher; frames are relayed through a QObject
    slot, so delivery from the GStreamer streaming thread is QUEUED
    onto the Qt main loop — this retires the direct-connection caveat
    in this module's docstring for the productized path. stop()
    drives the source down, stitches, writes the PNG into the library
    and emits captured(path); the app coordinator feeds that to the
    SAME _on_captured used by every screenshot."""

    started = Signal()       # portal granted; frames flowing
    captured = Signal(str)   # stitched PNG path in the library
    failed = Signal(str)

    def __init__(self, settings, source_factory=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._source_factory = source_factory or (
            lambda: ScreenCastFrameSource(settings, fps=10))
        self._source = None
        self._stitcher = None

    @property
    def running(self) -> bool:
        return self._source is not None

    def start(self) -> None:
        if self.running:
            return
        from .stitch import ScrollStitcher
        self._stitcher = ScrollStitcher()
        self._source = self._source_factory()
        self._source.frame.connect(self._on_frame)
        self._source.started.connect(self.started)
        self._source.failed.connect(self._on_source_failed)
        self._source.start()

    def _on_frame(self, img: QImage) -> None:
        if self._stitcher is not None:
            self._stitcher.add_frame(img)

    def _on_source_failed(self, message: str) -> None:
        self._teardown()
        self.failed.emit(message)

    def stop(self) -> None:
        if not self.running:
            return
        source, stitcher = self._source, self._stitcher
        self._teardown()
        source.stop()  # pipeline -> NULL: callbacks cease before result()
        img = stitcher.result()
        if img.isNull():
            self.failed.emit("no frames captured — nothing to stitch")
            return
        from .capture import timestamp_name, unique_path
        path = unique_path(self.settings.library_dir,
                           timestamp_name("ScrollCapture"))
        img.save(path, "PNG")
        self.captured.emit(path)

    def _teardown(self) -> None:
        if self._source is not None:
            try:
                self._source.frame.disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass  # never connected / already gone
        self._source = None
        self._stitcher = None
```

- [x] `QObject` is needed in the imports: change the QtCore import line to
  `from PySide6.QtCore import QObject, QTimer, Signal`.
- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_scrollcontroller.py tests/test_scrollsource.py -x -q`
- [x] Expected: all pass.
- [x] Commit: `git add -A && git commit -m "Scroll capture: availability gate + ScrollCaptureController state machine"`

---

## Task 2: `ScrollStopPill` (capture_window.py)

**Files:** `wondershot/capture_window.py`, `tests/test_scroll_pill.py`

### Step 2.1: Failing tests

- [x] Create `tests/test_scroll_pill.py`:

```python
"""The scroll-capture stop pill: one affordance (click to finish),
emitted exactly once; Esc also finishes. Frameless/always-on-top
flags are the contract the compositor-placement approach relies on."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_click_emits_stop_once(qapp):
    from wondershot.capture_window import ScrollStopPill
    pill = ScrollStopPill()
    hits = []
    pill.stop_requested.connect(lambda: hits.append(1))
    btn = pill.findChild(QPushButton)
    assert btn is not None
    assert "finish" in btn.text().lower()
    btn.click()
    btn.click()  # double-click must not double-stop
    assert hits == [1]


def test_escape_emits_stop(qapp):
    from wondershot.capture_window import ScrollStopPill
    pill = ScrollStopPill()
    hits = []
    pill.stop_requested.connect(lambda: hits.append(1))
    QTest.keyClick(pill, Qt.Key_Escape)
    assert hits == [1]


def test_window_flags_frameless_on_top(qapp):
    from wondershot.capture_window import ScrollStopPill
    pill = ScrollStopPill()
    flags = pill.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_scroll_pill.py -x -q`
- [x] Expected failure: `ImportError: cannot import name 'ScrollStopPill'`

### Step 2.2: Implement

- [x] In `wondershot/capture_window.py`, after the `CaptureWindow` class (and
  before the quick-bar section), add:

```python
# -- scroll-capture stop pill -------------------------------------------------

class ScrollStopPill(QWidget):
    """Frameless always-on-top pill shown while a scroll capture runs.

    One affordance: click (or Esc) to finish. Short-lived like
    countdown.CountdownOverlay, so the compositor places it — no KWin
    position rule is written (Wayland clients can't self-position;
    bubble.py documents the rule mechanism we deliberately skip).
    Note for the manual checklist: when the user picks a MONITOR (not
    a window) in the portal, the pill itself can appear in captured
    frames; window picks stream the window buffer and exclude it."""

    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle("wondershot scroll stop")
        self._fired = False

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        btn = QPushButton("Scrolling — click to finish")
        btn.setStyleSheet("""
            QPushButton {
                background: #d3382c; color: white; font-weight: bold;
                border-radius: 14px; border: none; padding: 6px 18px;
            }
            QPushButton:hover { background: #e4493d; }
            QPushButton:pressed { background: #b32a20; }
        """)
        btn.clicked.connect(self._fire)
        row.addWidget(btn)
        self.setFixedSize(self.sizeHint())

    def _fire(self) -> None:
        if self._fired:
            return  # a double click must not double-stop
        self._fired = True
        self.stop_requested.emit()

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self._fire()
        else:
            super().keyPressEvent(ev)
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_scroll_pill.py -x -q`
- [x] Expected: pass.
- [x] Commit: `git add -A && git commit -m "Scroll capture: frameless stop pill (compositor-placed)"`

---

## Task 3: Capture-panel button + gallery pass-through

**Files:** `wondershot/capture_window.py`, `wondershot/gallery.py`,
`tests/test_capture_window_mode.py`

### Step 3.1: Failing tests

- [ ] Append to `tests/test_capture_window_mode.py`:

```python
def _scroll_buttons(w):
    return [b for b in w.findChildren(QPushButton)
            if b.text() == "Scrolling"]


def test_scroll_button_present_and_fires_mode(qapp):
    from wondershot.capture_window import CaptureWindow
    w = CaptureWindow(_Settings(), scroll_mode=True)
    btns = _scroll_buttons(w)
    assert len(btns) == 1
    fired = []
    w.capture_requested.connect(fired.append)
    btns[0].click()
    assert fired == ["scroll"]


def test_scroll_button_hidden_without_probe(qapp):
    from wondershot.capture_window import CaptureWindow
    w = CaptureWindow(_Settings())  # default: gi/Gst/numpy not probed OK
    assert not _scroll_buttons(w)
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_capture_window_mode.py -x -q`
- [ ] Expected failure: `TypeError: CaptureWindow.__init__() got an unexpected keyword argument 'scroll_mode'`

### Step 3.2: Implement

- [ ] `wondershot/capture_window.py` — `CaptureWindow.__init__` signature:

```python
    def __init__(self, settings, parent=None, window_mode: bool = False,
                 scroll_mode: bool = False):
```

  and update the docstring comment on the signal:
  `capture_requested = Signal(str)  # "region" | "fullscreen" | "window-auto" | "scroll" | "record"`

- [ ] In the secondary-buttons block, insert the Scrolling entry between
  Window and Record:

```python
        secondary = [("Full screen", "fullscreen")]
        if window_mode:
            secondary.append(("Window", "window-auto"))
        if scroll_mode:
            secondary.append(("Scrolling", "scroll"))
        secondary.append(("Record", "record"))
```

- [ ] `wondershot/gallery.py` — in `_open_capture_window`, pass the gate
  (mirrors `kwin_ok`, which `app.py` sets after construction):

```python
            self._capture_window = CaptureWindow(
                self.settings, window_mode=getattr(self, "kwin_ok", False),
                scroll_mode=getattr(self, "scroll_ok", False))
```

  No other gallery change: `_capture_mode` already passes any non-"record"
  mode through `capture_requested` → `app.trigger_capture`, which is exactly
  the hide-our-windows-first routing scroll needs (study note: this is the
  same path `"window-auto"` rides).
- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_capture_window_mode.py tests/test_hide_for_capture.py -x -q`
- [ ] Expected: pass (hide_for_capture tests prove the panel construction
  still works with the duck-typed `_Settings` stub — no new settings reads).
- [ ] Commit: `git add -A && git commit -m "Capture panel: Scrolling button gated on scroll availability"`

---

## Task 4: app.py routing — tray action, trigger_capture("scroll"), pill lifecycle

**Files:** `wondershot/app.py`, `tests/test_scroll_mode.py`

### Step 4.1: Failing tests

- [ ] Create `tests/test_scroll_mode.py` (make_app pattern copied from
  `tests/test_tray_tooltip.py` — same stub, same monkeypatches):

```python
"""Scroll-mode routing through the app coordinator: tray entry gated on
availability (NOT KDE), trigger_capture('scroll') rides the existing
hide_for_capture path, the stop pill drives controller.stop(), and the
stitched PNG goes through the normal _on_captured path."""
import itertools
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

_counter = itertools.count()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []

    def __getattr__(self, k):
        if k in ("stroke_width", "font_size", "capture_delay",
                 "share_expiry_days", "quick_bar_timeout",
                 "video_blur_strength", "gif_fps", "gif_max_width"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick", "capture_cursor",
                                      "record")) else ""


class FakeController(QObject):
    started = Signal()
    captured = Signal(str)
    failed = Signal(str)
    instances = []

    def __init__(self, settings, source_factory=None, parent=None):
        super().__init__(parent)
        FakeController.instances.append(self)
        self.start_calls = 0
        self.stop_calls = 0
        self.running = False

    def start(self):
        self.start_calls += 1
        self.running = True

    def stop(self):
        self.stop_calls += 1
        self.running = False


def make_app(qapp, tmp_path, monkeypatch, scroll_ok=True):
    import wondershot.app as appmod
    import wondershot.scrollsource as scrollmod
    from wondershot.hotkey import NullHotkeyBackend
    FakeController.instances = []
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-sm-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings",
                        lambda: _Settings(str(tmp_path)))
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    monkeypatch.setattr(appmod, "scroll_capture_available",
                        lambda: scroll_ok)
    monkeypatch.setattr(scrollmod, "ScrollCaptureController",
                        FakeController)
    return appmod.GrabbitApp(qapp)


def _menu_texts(app):
    return [a.text() for a in app.tray.contextMenu().actions()]


def test_tray_has_scroll_entry_when_available(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch, scroll_ok=True)
    assert "Scrolling capture" in _menu_texts(app)
    assert app.gallery.scroll_ok is True


def test_tray_entry_absent_when_unavailable(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch, scroll_ok=False)
    assert "Scrolling capture" not in _menu_texts(app)
    assert app.gallery.scroll_ok is False


def _start_scroll(qapp, app):
    app.trigger_capture("scroll")
    # nothing visible -> hide_for_capture returns 0 -> singleShot(0)
    for _ in range(20):
        qapp.processEvents()
        if FakeController.instances:
            ctl = FakeController.instances[-1]
            if ctl.start_calls:
                return ctl
    raise AssertionError("controller never started")


def test_trigger_scroll_hides_windows_and_starts_controller(
        qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    app.gallery.show()
    app.trigger_capture("scroll")
    assert not app.gallery.isVisible()  # hide_for_capture ran first
    for _ in range(50):
        qapp.processEvents()
        if FakeController.instances and \
                FakeController.instances[-1].start_calls:
            break
    else:
        raise AssertionError("controller never started after the delay")


def test_started_shows_pill_and_pill_stops_controller(
        qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    pill = app._scroll_pill
    assert pill is not None and pill.isVisible()
    pill.stop_requested.emit()
    assert ctl.stop_calls == 1


def test_captured_routes_through_normal_captured_path(
        qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    seen = []
    monkeypatch.setattr(app, "_on_captured", seen.append)
    png = tmp_path / "ScrollCapture_x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nx")
    ctl.captured.emit(str(png))
    assert seen == [str(png)]
    assert app._scroll is None          # controller released
    assert app._scroll_pill is None     # pill closed


def test_failed_routes_through_capture_failed(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    seen = []
    monkeypatch.setattr(app, "_on_capture_failed", seen.append)
    ctl.failed.emit("portal said no")
    assert seen == ["portal said no"]
    assert app._scroll is None
    assert app._scroll_pill is None


def test_second_trigger_while_running_is_noop(qapp, tmp_path, monkeypatch):
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    app.trigger_capture("scroll")
    for _ in range(20):
        qapp.processEvents()
    assert len(FakeController.instances) == 1
    assert ctl.start_calls == 1


def test_tray_action_finishes_running_scroll(qapp, tmp_path, monkeypatch):
    # Spec Addendum 2 Track 4b: the tray is the second finish path
    # ("Ctrl+click tray or click Stop to finish").
    app = make_app(qapp, tmp_path, monkeypatch)
    ctl = _start_scroll(qapp, app)
    ctl.started.emit()
    action = next(a for a in app.tray.contextMenu().actions()
                  if a.text() == "Scrolling capture")
    action.trigger()
    assert ctl.stop_calls == 1
    assert app._scroll_pill is None  # pill closed by the finish path
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_scroll_mode.py -x -q`
- [ ] Expected failure: `AttributeError: <module 'wondershot.app'> has no attribute 'scroll_capture_available'` (the monkeypatch target doesn't exist yet).

### Step 4.2: Implement

- [ ] `wondershot/app.py` — add to the module imports:

```python
from .scrollsource import scroll_capture_available
```

  (scrollsource only imports PySide6 + the gi-guarded `record`, so this is
  headless-safe; the heavy gi/Gst/numpy probes run inside the function.)

- [ ] In `GrabbitApp.__init__`, right after the `kwin_ok` block:

```python
        self.scroll_ok = scroll_capture_available()
        self.gallery.scroll_ok = self.scroll_ok  # gates the panel button
        self._scroll = None        # ScrollCaptureController while running
        self._scroll_pill = None   # ScrollStopPill while running
```

  NOTE: `__init__` calls `_build_tray()` AFTER this point already (the
  existing `self.tray = self._build_tray()` line comes later) — verify the
  insertion sits above it, since the tray menu reads `self.scroll_ok`.

- [ ] In `_build_tray`, after the `kwin_ok` "Capture window" block:

```python
        if self.scroll_ok:
            a = QAction("Scrolling capture", menu)
            a.setToolTip("Scroll a window; Wondershot stitches one tall "
                         "image — trigger again while scrolling to finish")
            a.triggered.connect(self._scroll_tray_action)
            menu.addAction(a)
```

- [ ] In `trigger_capture`, add the mode entry:

```python
        fn = {
            "region": self.capture.capture_region,
            "fullscreen": self.capture.capture_fullscreen,
            "window": self.capture.capture_window,
            "window-auto": self.capture.capture_active_window,
            "scroll": self._begin_scroll,
        }[mode]
```

- [ ] Add the scroll section after `_share_from_bar` (before the recording
  section):

```python
    # -- scroll capture --------------------------------------------------------

    def _scroll_tray_action(self) -> None:
        # The tray entry is the SECOND finish path (spec Addendum 2
        # Track 4b: "Ctrl+click tray or click Stop to finish"): while a
        # scroll session runs, triggering it again finishes the capture.
        # Deliberately NOT routed through trigger_capture, which would
        # clobber _gallery_was_visible mid-session.
        if self._scroll is not None:
            self._finish_scroll()
        else:
            self.trigger_capture("scroll")

    def _begin_scroll(self) -> None:
        if self._scroll is not None:
            return  # one scroll session at a time
        from .scrollsource import ScrollCaptureController
        ctl = ScrollCaptureController(self.settings, parent=self)
        ctl.started.connect(self._on_scroll_started)
        ctl.captured.connect(self._on_scroll_captured)
        ctl.failed.connect(self._on_scroll_failed)
        self._scroll = ctl
        ctl.start()

    def _on_scroll_started(self) -> None:
        from .capture_window import ScrollStopPill
        pill = ScrollStopPill()
        pill.setAttribute(Qt.WA_DeleteOnClose, True)
        pill.stop_requested.connect(self._finish_scroll)
        self._scroll_pill = pill
        pill.show()

    def _finish_scroll(self) -> None:
        self._close_scroll_pill()
        if self._scroll is not None:
            self._scroll.stop()

    def _close_scroll_pill(self) -> None:
        pill, self._scroll_pill = self._scroll_pill, None
        if pill is not None:
            try:
                pill.close()
            except RuntimeError:
                pass  # already deleted (WA_DeleteOnClose)

    def _release_scroll(self) -> None:
        self._close_scroll_pill()
        ctl, self._scroll = self._scroll, None
        if ctl is not None:
            ctl.deleteLater()

    def _on_scroll_captured(self, path: str) -> None:
        self._release_scroll()
        self._on_captured(path)  # the normal captured path: clipboard,
        # rescan/select, preview-or-quick-bar, tray toast — all inherited.

    def _on_scroll_failed(self, message: str) -> None:
        self._release_scroll()
        self._on_capture_failed(message)
```

  Note: `_begin_scroll` imports `ScrollCaptureController` from
  `.scrollsource` at call time, so the test monkeypatch on the scrollsource
  module attribute takes effect.

- [ ] Run the new tests plus every existing GrabbitApp-constructing suite
  (they exercise the new `__init__`/tray code against the duck-typed stubs):
  `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_scroll_mode.py tests/test_tray_tooltip.py tests/test_countdown.py tests/test_record_sync.py tests/test_quickbar.py -x -q`
- [ ] Expected: all pass. (If a stub-based test crashes on a missing settings
  attribute, you have accidentally read a new settings key — see the
  shared-stub rule in Task 8 step 2 and fix EVERY stub.)
- [ ] Commit: `git add -A && git commit -m "Scroll capture mode: tray entry, trigger_capture routing, stop-pill lifecycle"`

---

## Task 5: CLI flag regression + snegg verdict (no pyproject change)

**Files:** `tests/test_cli_scroll_spike.py`, evidence only for pyproject

### Step 5.1: Failing-by-construction regression test for --scroll-spike

The flag already exists (`cli.py` line 48 + dispatch at line 62); this test
pins it so later CLI churn can't silently drop the debugging harness.

- [ ] Create `tests/test_cli_scroll_spike.py`:

```python
"""--scroll-spike must stay: it is the scroll-capture debugging harness
(spec Addendum 2 Track 4b: 'Keep the CLI flag'). No Qt needed — main()
dispatches to run_scroll_spike before any QApplication exists."""


def test_scroll_spike_flag_dispatches(monkeypatch):
    import wondershot.scrollsource as scrollmod
    from wondershot.cli import main
    monkeypatch.setattr(scrollmod, "run_scroll_spike", lambda: 42)
    assert main(["--scroll-spike"]) == 42
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_cli_scroll_spike.py -x -q`
- [ ] Expected: PASSES immediately (the flag exists). This is a pin, not TDD
  — justification: no production change is being made to cli.py; the test
  exists to make removal a visible failure.
- [ ] Commit: `git add -A && git commit -m "Pin --scroll-spike CLI flag with a regression test"`

### Step 5.2: snegg availability verdict (evidence step, no code)

- [ ] Run: `.venv/bin/pip install snegg`
- [ ] Expected output: `ERROR: No matching distribution found for snegg`
  (plan-prep verification 2026-06-07: `https://pypi.org/pypi/snegg/json`
  returns HTTP 404 — snegg lives on gitlab.freedesktop.org/libinput/snegg
  and is not published to PyPI).
- [ ] Decision (already reflected in this plan): do NOT add a
  `wondershot[stepcapture]` extra — an extra pointing at a non-existent PyPI
  dist breaks `pip install wondershot[stepcapture]` outright, and an empty
  extra is a lie. The EI client ships as `wondershot/ei.py` (Task 6) using
  stdlib ctypes against the system `libei.so.1` (Fedora package `libei`;
  1.5.0 is installed on Jack's box) — zero pip dependencies. Record the
  verdict + pip error line in ROADMAP (Task 8 step 3).
- [ ] If, against expectation, the install SUCCEEDS: stop, add
  `stepcapture = ["snegg"]` to `[project.optional-dependencies]`, prefer
  snegg in the probe (it is already the first branch in `observe_events`),
  and SKIP Task 6 — note the deviation in the final report.

---

## Task 6: `wondershot/ei.py` — ctypes libei RECEIVE-path binding

**Files:** `wondershot/ei.py`, `tests/test_ei.py`

All constants/symbols below were verified during plan prep against libei
1.5.0: enum values from `src/libei.h` (CONNECT=1, DISCONNECT=2, SEAT_ADDED=3,
SEAT_REMOVED=4, DEVICE_ADDED=5, DEVICE_REMOVED=6, DEVICE_PAUSED=7,
DEVICE_RESUMED=8, BUTTON_BUTTON=500; CAP_POINTER=1<<0, CAP_BUTTON=1<<5) and
exported symbols via `nm -D /usr/lib64/libei.so.1` (ei_new_receiver,
ei_configure_name, ei_setup_backend_fd, ei_get_fd, ei_dispatch, ei_get_event,
ei_event_get_type, ei_event_get_seat, ei_event_get_time,
ei_event_button_get_button, ei_event_button_get_is_press, ei_event_unref,
ei_seat_bind_capabilities, ei_unref — all present).

### Step 6.1: Failing tests

- [ ] Create `tests/test_ei.py`:

```python
"""EI receive-path state machine against a fake 'lib' (the feasible
analogue of a fake socket: the wire parsing is C's job inside libei;
what we own — and test — is the handshake/event handling around it).

The wrapper passes ctypes-wrapped args to variadic/pointer calls, so
the fake unwraps `.value` where needed."""
import ctypes

import pytest

from wondershot.ei import (
    EI_DEVICE_CAP_BUTTON,
    EI_DEVICE_CAP_POINTER,
    EI_EVENT_BUTTON_BUTTON,
    EI_EVENT_CONNECT,
    EI_EVENT_DEVICE_ADDED,
    EI_EVENT_DEVICE_RESUMED,
    EI_EVENT_DISCONNECT,
    EI_EVENT_SEAT_ADDED,
    ButtonEvent,
    EiButtonReader,
)


class FakeLib:
    """Scripted libei: hands out the queued events once, records what
    the wrapper does (binds, unrefs)."""

    def __init__(self, events=(), setup_rc=0):
        self._events = list(events)  # (type, payload dict) per event
        self._handed = 0
        self._setup_rc = setup_rc
        self.bound = []        # (seat, [vararg values]) per bind call
        self.unreffed = []     # event handles released
        self.ctx_unreffed = 0
        self.dispatch_calls = 0
        self.backend_fd = None
        self.name = None

    # context ---------------------------------------------------------
    def ei_new_receiver(self, user_data):
        return 0xC0FFEE

    def ei_configure_name(self, ctx, name):
        self.name = name

    def ei_setup_backend_fd(self, ctx, fd):
        self.backend_fd = fd
        return self._setup_rc

    def ei_get_fd(self, ctx):
        return 99

    def ei_unref(self, ctx):
        self.ctx_unreffed += 1

    # event pump ------------------------------------------------------
    def ei_dispatch(self, ctx):
        self.dispatch_calls += 1

    def ei_get_event(self, ctx):
        if self._handed >= len(self._events):
            return None
        self._handed += 1
        return self._handed  # handle = 1-based index into the script

    def _ev(self, handle):
        return self._events[handle - 1]

    def ei_event_get_type(self, h):
        return self._ev(h)[0]

    def ei_event_get_seat(self, h):
        return self._ev(h)[1]["seat"]

    def ei_event_get_time(self, h):
        return self._ev(h)[1]["time"]

    def ei_event_button_get_button(self, h):
        return self._ev(h)[1]["button"]

    def ei_event_button_get_is_press(self, h):
        return self._ev(h)[1]["press"]

    def ei_event_unref(self, h):
        self.unreffed.append(h)

    # seat ------------------------------------------------------------
    def ei_seat_bind_capabilities(self, seat, *varargs):
        self.bound.append((seat.value,
                           [a.value for a in varargs]))


def test_setup_wires_fd_and_name():
    lib = FakeLib()
    r = EiButtonReader(7, name=b"ws-probe", lib=lib)
    assert lib.backend_fd == 7
    assert lib.name == b"ws-probe"
    assert r.fd == 99


def test_setup_failure_raises_and_unrefs():
    lib = FakeLib(setup_rc=-22)
    with pytest.raises(OSError):
        EiButtonReader(7, lib=lib)
    assert lib.ctx_unreffed == 1


def test_handshake_binds_pointer_and_button_with_null_sentinel():
    lib = FakeLib(events=[
        (EI_EVENT_CONNECT, {}),
        (EI_EVENT_SEAT_ADDED, {"seat": 0xBEEF}),
    ])
    r = EiButtonReader(7, lib=lib)
    assert r.dispatch() == []
    assert r.connected
    assert len(lib.bound) == 1
    seat, args = lib.bound[0]
    assert seat == 0xBEEF
    assert args[:-1] == [EI_DEVICE_CAP_POINTER, EI_DEVICE_CAP_BUTTON]
    assert args[-1] is None  # NULL sentinel (variadic terminator)


def test_button_events_decode_with_timestamps():
    lib = FakeLib(events=[
        (EI_EVENT_CONNECT, {}),
        (EI_EVENT_SEAT_ADDED, {"seat": 1}),
        (EI_EVENT_DEVICE_ADDED, {}),
        (EI_EVENT_DEVICE_RESUMED, {}),
        (EI_EVENT_BUTTON_BUTTON,
         {"time": 1111, "button": 0x110, "press": True}),
        (EI_EVENT_BUTTON_BUTTON,
         {"time": 2222, "button": 0x110, "press": False}),
    ])
    r = EiButtonReader(7, lib=lib)
    events = r.dispatch()
    assert events == [
        ButtonEvent(time_us=1111, button=0x110, is_press=True),
        ButtonEvent(time_us=2222, button=0x110, is_press=False),
    ]


def test_every_event_handle_is_released():
    lib = FakeLib(events=[
        (EI_EVENT_CONNECT, {}),
        (EI_EVENT_SEAT_ADDED, {"seat": 1}),
        (EI_EVENT_BUTTON_BUTTON,
         {"time": 1, "button": 0x110, "press": True}),
    ])
    r = EiButtonReader(7, lib=lib)
    r.dispatch()
    assert lib.unreffed == [1, 2, 3]


def test_disconnect_sets_flag():
    lib = FakeLib(events=[(EI_EVENT_DISCONNECT, {})])
    r = EiButtonReader(7, lib=lib)
    r.dispatch()
    assert r.disconnected


def test_close_unrefs_context_once():
    lib = FakeLib()
    r = EiButtonReader(7, lib=lib)
    r.close()
    r.close()
    assert lib.ctx_unreffed == 1


def test_open_libei_loads_real_library_if_present():
    # Integration smoke: only meaningful where libei is installed
    # (Jack's Fedora box has libei-1.5.0). Skipped elsewhere.
    from wondershot.ei import open_libei
    try:
        lib = open_libei()
    except OSError:
        pytest.skip("libei.so.1 not installed on this box")
    for sym in ("ei_new_receiver", "ei_setup_backend_fd", "ei_dispatch",
                "ei_get_event", "ei_event_get_type", "ei_event_unref",
                "ei_seat_bind_capabilities", "ei_unref"):
        assert getattr(lib, sym) is not None
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ei.py -x -q`
- [ ] Expected failure: `ModuleNotFoundError: No module named 'wondershot.ei'`

### Step 6.2: Implement

- [ ] Create `wondershot/ei.py`:

```python
"""Minimal ctypes binding for the libei RECEIVE path (EI client).

Step capture needs to OBSERVE pointer-button events coming over the
InputCapture portal's EIS fd. snegg (freedesktop's Python libei
binding) is NOT on PyPI (verified 2026-06-07: pypi.org/pypi/snegg/json
returns 404), so this is a hand-rolled binding against the system
libei.so.1 (Fedora package `libei`) covering ONLY what the receive
path needs: receiver context, backend-fd setup, the handshake
(CONNECT / SEAT_ADDED -> bind pointer+button capabilities) and
BUTTON_BUTTON decoding with timestamps. No sender support, no
emulation, no keyboard/touch.

Enum values verified against libei 1.5.0 src/libei.h; every symbol
used here verified exported by `nm -D /usr/lib64/libei.so.1`.

Sole consumer today: spikes/inputcapture_probe.py. The interception-
semantics question (do apps still receive clicks while we observe?)
cannot be answered in code — it is a manual checklist item.

Stdlib-only on purpose (no gi, no Qt): the probe runs under the
SYSTEM python, and unit tests inject a plain-Python fake `lib`.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass

# enum ei_event_type (libei.h, 1.5.0)
EI_EVENT_CONNECT = 1
EI_EVENT_DISCONNECT = 2
EI_EVENT_SEAT_ADDED = 3
EI_EVENT_SEAT_REMOVED = 4
EI_EVENT_DEVICE_ADDED = 5
EI_EVENT_DEVICE_REMOVED = 6
EI_EVENT_DEVICE_PAUSED = 7
EI_EVENT_DEVICE_RESUMED = 8
EI_EVENT_BUTTON_BUTTON = 500

# enum ei_device_capability (libei.h, 1.5.0)
EI_DEVICE_CAP_POINTER = 1 << 0
EI_DEVICE_CAP_BUTTON = 1 << 5


@dataclass(frozen=True)
class ButtonEvent:
    time_us: int    # microseconds; FRAME-derived, monotonic domain
    button: int     # evdev BTN_* code (BTN_LEFT = 0x110)
    is_press: bool


def open_libei() -> ctypes.CDLL:
    """Load libei.so.1 and declare the receive-path prototypes.

    Raises OSError when the library is not installed."""
    name = ctypes.util.find_library("ei") or "libei.so.1"
    lib = ctypes.CDLL(name)
    p = ctypes.c_void_p
    lib.ei_new_receiver.restype = p
    lib.ei_new_receiver.argtypes = [p]
    lib.ei_configure_name.restype = None
    lib.ei_configure_name.argtypes = [p, ctypes.c_char_p]
    lib.ei_setup_backend_fd.restype = ctypes.c_int
    lib.ei_setup_backend_fd.argtypes = [p, ctypes.c_int]
    lib.ei_get_fd.restype = ctypes.c_int
    lib.ei_get_fd.argtypes = [p]
    lib.ei_dispatch.restype = None
    lib.ei_dispatch.argtypes = [p]
    lib.ei_get_event.restype = p
    lib.ei_get_event.argtypes = [p]
    lib.ei_event_get_type.restype = ctypes.c_int
    lib.ei_event_get_type.argtypes = [p]
    lib.ei_event_get_seat.restype = p
    lib.ei_event_get_seat.argtypes = [p]
    lib.ei_event_get_time.restype = ctypes.c_uint64
    lib.ei_event_get_time.argtypes = [p]
    lib.ei_event_button_get_button.restype = ctypes.c_uint32
    lib.ei_event_button_get_button.argtypes = [p]
    lib.ei_event_button_get_is_press.restype = ctypes.c_bool
    lib.ei_event_button_get_is_press.argtypes = [p]
    lib.ei_event_unref.restype = p
    lib.ei_event_unref.argtypes = [p]
    lib.ei_unref.restype = p
    lib.ei_unref.argtypes = [p]
    # ei_seat_bind_capabilities is VARIADIC with a NULL sentinel —
    # declaring argtypes would break the varargs call; leave it bare
    # and wrap every argument in a ctypes type at the call site.
    lib.ei_seat_bind_capabilities.restype = None
    return lib


class EiButtonReader:
    """RECEIVE-path EI client: handshake + pointer-button events only.

    Drive it from a select() loop: when `.fd` is readable, call
    dispatch(); it returns the ButtonEvents decoded since the last
    call. SEAT_ADDED is answered with a pointer+button capability
    bind (NULL-terminated varargs, per libei's sentinel contract);
    devices resume on their own; everything else is consumed and
    released. `lib` is injectable so tests run without libei."""

    def __init__(self, fd: int, name: bytes = b"wondershot", lib=None):
        self._lib = lib if lib is not None else open_libei()
        self._ctx = self._lib.ei_new_receiver(None)
        if not self._ctx:
            raise OSError("ei_new_receiver failed")
        self._lib.ei_configure_name(self._ctx, name)
        rc = self._lib.ei_setup_backend_fd(self._ctx, fd)
        if rc != 0:
            self._lib.ei_unref(self._ctx)
            self._ctx = None
            raise OSError(f"ei_setup_backend_fd failed (rc={rc})")
        self.connected = False
        self.disconnected = False

    @property
    def fd(self) -> int:
        return self._lib.ei_get_fd(self._ctx)

    def dispatch(self) -> list[ButtonEvent]:
        self._lib.ei_dispatch(self._ctx)
        out: list[ButtonEvent] = []
        while True:
            ev = self._lib.ei_get_event(self._ctx)
            if not ev:
                return out
            try:
                kind = self._lib.ei_event_get_type(ev)
                if kind == EI_EVENT_CONNECT:
                    self.connected = True
                elif kind == EI_EVENT_DISCONNECT:
                    self.disconnected = True
                elif kind == EI_EVENT_SEAT_ADDED:
                    seat = self._lib.ei_event_get_seat(ev)
                    self._lib.ei_seat_bind_capabilities(
                        ctypes.c_void_p(seat),
                        ctypes.c_int(EI_DEVICE_CAP_POINTER),
                        ctypes.c_int(EI_DEVICE_CAP_BUTTON),
                        ctypes.c_void_p(None))
                elif kind == EI_EVENT_BUTTON_BUTTON:
                    out.append(ButtonEvent(
                        time_us=int(self._lib.ei_event_get_time(ev)),
                        button=int(
                            self._lib.ei_event_button_get_button(ev)),
                        is_press=bool(
                            self._lib.ei_event_button_get_is_press(ev))))
                # DEVICE_ADDED/RESUMED/etc.: nothing to do on the
                # receive path — consumed and released.
            finally:
                self._lib.ei_event_unref(ev)

    def close(self) -> None:
        if self._ctx:
            self._lib.ei_unref(self._ctx)
            self._ctx = None
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ei.py -x -q`
- [ ] Expected: all pass (the integration smoke passes on Jack's box, skips
  where libei is absent).
- [ ] Commit: `git add -A && git commit -m "ei.py: ctypes libei receive-path binding (snegg not on PyPI)"`

---

## Task 7: Extend `spikes/inputcapture_probe.py` — barriers, Enable, EI event loop

**Files:** `spikes/inputcapture_probe.py`

GUI/portal glue, manual-run only (it needs a live portal + compositor and a
human moving the pointer) — no pytest coverage, same as the original probe;
the protocol logic it exercises IS unit-tested via `tests/test_ei.py`.
Justification for skipping failing-test steps: every code path here either
talks to the session bus or blocks on human input; the original WS-D plan
established this script as explicitly manual.

Why the new portal calls: without `SetPointerBarriers` + `Enable`, capture
never ACTIVATES and the EIS fd stays silent (the current probe's closing
finding says exactly this). Keep the defensive D-Bus posture from the module
docstring (hotkey.py landmine history): portal daemon only, explicit
GLib.Variant types, finite timeouts, GLib.Error caught per step.

### Step 7.1: Store the first zone, add barrier + Enable steps

- [ ] In `Probe.__init__`, add `self.zone: tuple | None = None`.
- [ ] In `get_zones`, after `zones = results.get("zones") or []`, add:

```python
        if zones:
            self.zone = zones[0]  # (uint32 w, uint32 h, int32 x, int32 y)
```

- [ ] Add two methods after `get_zones`:

```python
    def set_barriers(self) -> bool:
        """One barrier along the LEFT edge of the first zone: shoving
        the pointer against the left screen edge activates capture."""
        if self.zone is None or self.zone_set is None:
            finding("no zones/zone_set — skipping SetPointerBarriers")
            return False
        w, h, x, y = self.zone
        token = self._token()
        barrier = {
            "barrier_id": GLib.Variant("u", 1),
            # vertical barrier: x1 == x2 (portal spec)
            "position": GLib.Variant("(iiii)", (x, y, x, y + h - 1)),
        }
        results = self._call_with_response(
            "SetPointerBarriers",
            GLib.Variant("(oa{sv}aa{sv}u)", (
                self.session,
                {"handle_token": GLib.Variant("s", token)},
                [barrier],
                self.zone_set)),
            token)
        if results is None:
            finding("SetPointerBarriers FAILED")
            return False
        failed = list(results.get("failed_barriers") or [])
        finding(f"SetPointerBarriers OK (failed_barriers={failed})")
        return 1 not in failed

    def enable(self) -> bool:
        """Enable is a plain method (no Request/Response dance)."""
        try:
            self.conn.call_sync(
                BUS, PATH, IFACE, "Enable",
                GLib.Variant("(oa{sv})", (self.session, {})),
                None, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
        except GLib.Error as e:
            finding(f"Enable FAILED: {e.message}")
            return False
        finding("Enable OK — PUSH THE POINTER AGAINST THE LEFT SCREEN "
                "EDGE to activate capture")
        return True

    def watch_activation(self) -> None:
        """Print Activated/Deactivated findings as they happen."""
        def on_signal(_c, _s, _p, _i, member, params):
            finding(f"{member}: {params.unpack()}")

        for member in ("Activated", "Deactivated", "Disabled"):
            self.conn.signal_subscribe(
                BUS, IFACE, member, PATH, None,
                Gio.DBusSignalFlags.NONE, on_signal)
```

### Step 7.2: EI event loop in observe_events

- [ ] Replace the body of `observe_events` so the fallback chain is
  snegg → `wondershot.ei` → raw read. Keep the snegg branch verbatim, and
  replace the current `except ImportError:` raw-read block with:

```python
        try:
            import snegg.ei  # python libei bindings, if installed
            have_snegg = True
        except ImportError:
            have_snegg = False
        if have_snegg:
            # ... (existing snegg branch, unchanged) ...
            return

        # snegg is not on PyPI (verified 2026-06-07) — use the ctypes
        # binding shipped with wondershot (wondershot/ei.py).
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        try:
            from wondershot.ei import EiButtonReader
            reader = EiButtonReader(fd, name=b"ws-probe")
        except OSError as e:
            finding(f"libei unusable ({e}) — falling back to raw read")
            os.set_blocking(fd, False)
            r, _, _ = select.select([fd], [], [], 3.0)
            if r:
                data = os.read(fd, 4096)
                finding(f"raw read got {len(data)} bytes without a "
                        "handshake (unexpected — investigate)")
            else:
                finding("raw fd silent without EI handshake (expected); "
                        "fd plumbing itself works")
            return

        finding("ctypes libei (wondershot.ei) loaded — observing for "
                "15s; ACTIVATE CAPTURE (left edge) AND CLICK NOW")
        deadline = GLib.get_monotonic_time() + 15_000_000
        saw = 0
        while GLib.get_monotonic_time() < deadline:
            r, _, _ = select.select([reader.fd], [], [], 0.5)
            if not r:
                continue
            for ev in reader.dispatch():
                saw += 1
                finding(f"pointer BUTTON event: button={ev.button:#x} "
                        f"press={ev.is_press} t={ev.time_us}us")
            if reader.connected and saw == 0:
                pass  # handshake done; waiting on activation + clicks
            if reader.disconnected:
                finding("EIS disconnected us")
                break
        finding(f"EIS handshake completed (connected={reader.connected}); "
                f"observed {saw} button events")
        if saw:
            finding("MANUAL CHECK REQUIRED: while those clicks were "
                    "observed, did the app under the pointer ALSO "
                    "receive them? (interception semantics — record "
                    "the answer in ROADMAP WS-D findings)")
        reader.close()
```

- [ ] In `main()`, wire the new steps between `get_zones` and `connect_eis`:

```python
        probe.get_zones()
        probe.watch_activation()
        probe.set_barriers()
        fd = probe.connect_eis()
        if fd >= 0:
            probe.enable()
            probe.observe_events(fd)
            os.close(fd)
```

- [ ] Sanity check (no portal calls — just import/compile):
  `python3 -m py_compile spikes/inputcapture_probe.py && python3 -c "import ast; ast.parse(open('spikes/inputcapture_probe.py').read())"`
- [ ] Run the FULL suite to prove nothing regressed:
  `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`
- [ ] Expected: all green. The probe itself is NOT run here — it is the final
  manual checklist item.
- [ ] Commit: `git add -A && git commit -m "Probe: barriers + Enable + ctypes-EI event loop (handshake + buttons w/ timestamps)"`

---

## Task 8: Shared-stub audit, ROADMAP + manual checklist, final verification

**Files:** `tests/*` (audit only), `ROADMAP.md`,
`docs/superpowers/plans/2026-06-07-desktop-checklist.md`

### Step 8.1: Full suite

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`
- [ ] Expected: everything green (main had 277 tests; this plan adds ~25).

### Step 8.2: Shared settings-stub audit (mandatory — crashed the batch-3 merge)

- [ ] Run: `grep -rln "class _Settings\|class _FakeSettings\|class FakeSettings" tests/`
- [ ] For EVERY file that grep lists — on main today that is 13 files
  (`test_capture_crop`, `test_capture_window_mode`, `test_scrollsource`,
  `test_quickbar`, `test_gallery_sidecar`, `test_editor_sidecar`,
  `test_tray_tooltip`, `test_settings_dialog_ai`, `test_record`,
  `test_countdown`, `test_hide_for_capture`, `test_gallery_trash`,
  `test_record_sync`) plus this plan's `test_scrollcontroller` and
  `test_scroll_mode` — confirm this
  plan added NO settings attribute read during widget construction. It
  shouldn't have — scroll gating is `scroll_capture_available()`, not a
  setting; the controller only reads `settings.library_dir` at stop() time
  (already in every stub). If any stub-based test failed in 8.1 on a missing
  attribute, extend EVERY stub in that list, not just the failing one.

### Step 8.3: ROADMAP updates (APPEND-ONLY — shared file)

ROADMAP.md is shared with Track 4a this batch: **do not edit or reflow any
existing line** (append-only confinement; same rule batch 3 used). Append a
new dated subsection at the END of the file instead of rewriting the
existing WS-D findings prose.

- [ ] Append to the end of `ROADMAP.md` (substitute the actual run date
  for the dates below):

```
### Track 4b findings (scroll UI + EI client)

- Scroll capture: PRODUCTIZED — "Scrolling capture" in the
  tray menu + capture panel, gated on gi/GStreamer/numpy availability
  (NOT KDE; portal ScreenCast is desktop-neutral). Fresh portal pick
  per session (stitch-v2 token hooks), frameless stop pill
  (compositor-placed), stitched PNG lands through the normal captured
  path (quick bar / preview / clipboard). ScrollCaptureController
  relays frames through a QObject slot, so Gst-streaming-thread
  delivery is queued — the spike's direct-connection caveat is
  retired for the product path. --scroll-spike kept as the debug
  harness (pinned by test). Tray entry doubles as the finish control
  while a scroll session runs.
- EI client: snegg is NOT on PyPI ("No matching distribution found
  for snegg", re-checked at execution time per Task 5), so no
  [stepcapture] extra;
  wondershot/ei.py is a stdlib-ctypes binding against the system
  libei.so.1 (RECEIVE path only: handshake + pointer-button events,
  values verified against libei 1.5.0). inputcapture_probe.py now
  does SetPointerBarriers + Enable and prints button events with
  timestamps via that binding. Interception semantics (do apps still
  get clicks while we observe?) = pending the final manual probe run;
  step-capture UI stays blocked on that verdict.
```

### Step 8.4: Manual checklist additions

- [ ] Append to `docs/superpowers/plans/2026-06-07-desktop-checklist.md`
  (keep its numbering style):

```
## Scroll capture UI (Track 4b)

- Tray menu shows "Scrolling capture" (box has gi+GStreamer+numpy);
  capture panel shows a "Scrolling" secondary button.
- Trigger from the tray with the gallery open: all Wondershot windows
  vanish BEFORE the portal picker appears.
- The portal picker MUST appear every time (fresh pick — no restore
  token reuse), and a normal recording afterwards must NOT re-ask
  (scroll didn't clobber the recorder's token).
- While scrolling, a small "Scrolling — click to finish" pill is
  visible on top; clicking it (or Esc with focus) finishes.
- Alternate finish path: while scrolling, the tray "Scrolling capture"
  entry finishes the session instead of starting a new one.
- The stitched PNG lands in the library; with preview off the
  quick-action bar appears and Edit/Copy/Share/Trash act on it.
- Pick a MONITOR (not a window) once: note whether the stop pill
  appears in the stitched output (window picks exclude it; monitor
  picks may not — record what KWin does).
- Scroll-fail path: cancel the portal picker — tray shows a capture
  failed toast, windows restore, no stuck pill.

## InputCapture probe — FINAL RUN (interception semantics)

- Run: python3 spikes/inputcapture_probe.py
  Expect FINDING lines for: portal version/caps, CreateSession,
  GetZones, SetPointerBarriers OK, ConnectToEIS fd, Enable OK,
  Activated after shoving the pointer against the LEFT screen edge,
  then "pointer BUTTON event: button=0x110 press=True t=...us" lines
  while clicking.
- THE question: while the probe prints button events, do the apps
  under the pointer still receive the clicks (observe) or not
  (intercept)? Click on a text editor and watch whether the caret
  moves. Record the verdict in ROADMAP WS-D findings — step capture's
  design is gated on it.
```

### Step 8.5: Final verification + commit

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` — green.
- [ ] Run: `.venv/bin/python -c "import wondershot.ei, wondershot.scrollsource, wondershot.app"` — imports clean.
- [ ] Commit: `git add -A && git commit -m "Track 4b: ROADMAP EI/scroll verdicts + manual checklist items"`
