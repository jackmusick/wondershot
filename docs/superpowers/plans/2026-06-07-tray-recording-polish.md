# Track 3a: Tray-Stop Bug + Recording Polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Fix the "tray Stop does nothing" recording bug so that *either* control (tray menu item or gallery toolbar button) stops a recording and *both* controls reset — driven by recorder signals, not per-control click handlers. Then polish: recording duration in the tray tooltip, an optional countdown-before-start (0–10 s, default off), a timeboxed pause/resume feasibility spike behind an explicit gate, and ROADMAP notes for region-only recording.

**Architecture:** `wondershot/record.py` owns a `ScreenRecorder` (QObject) that drives a `gst-launch-1.0 -e` subprocess fed by a portal/PipeWire screencast; it emits `started` / `finished(str)` / `failed(str)` / `tick(str)` signals. `wondershot/app.py` (`GrabbitApp`) owns the tray icon + tray `record_action` and connects recorder signals to UI resets; `wondershot/gallery.py` (`GalleryWindow`) owns the toolbar `record_action`. Today each control mutates UI in its own click handler. This plan adds a `stopping` signal to the recorder as the single source of truth for stop-state, a `record_requested` signal on the gallery so all record *starts* funnel through the app coordinator (which is where the countdown gate lives), and an escalation ladder in the recorder's finalize loop for wedged EOS.

**Tech Stack:** Python 3.14, PySide6 (Qt 6), GStreamer via `gst-launch-1.0` subprocess, xdg-desktop-portal ScreenCast via PyGObject/Gio, pytest with `QT_QPA_PLATFORM=offscreen`.

**Execution environment:** Work in a git worktree off `main` (e.g. `git worktree add ../grabbit-wt/track-3a main && cd ../grabbit-wt/track-3a`). Create the venv: `python -m venv .venv && .venv/bin/pip install -e ".[spike]" pytest` — the `spike` extra pulls numpy, which is needed for test *collection* (stitch tests import it). Run all tests as `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`.

---

## Diagnosis (mandatory context — read before Task 1)

Reported symptom (Jack, confirmed): *tray-menu Stop does not stop a recording; toolbar stop works.*

### What was verified NOT to be the cause (tested 2026-06-07 on Jack's live KDE box)

- **Tray QAction wiring** (`app.py:127-129`): `record_action.triggered → toggle_recording` fires correctly. Verified offscreen with the real `GrabbitApp`: `record_action.trigger()` on a faked in-flight recording delivered SIGINT to the child and emitted `finished`/`failed`.
- **Menu garbage collection**: the parentless `QMenu()` in `_build_tray` (`app.py:114`) survives GC; `tray.contextMenu()` stays valid and actions still trigger.
- **SNI/DBusMenu layer**: a faithful replica *and* the real `GrabbitApp` tray were registered on the live Plasma session bus and driven with Plasma's exact click protocol (`com.canonical.dbusmenu` `AboutToShow` + `Event(id, "clicked")`). Start and stop both worked, item ids stayed stable across the per-second `setText` ticks, and `dbus-monitor` showed the ticks emit only benign `ItemsPropertiesUpdated` (no layout rebuild).

### The actual defect (file:line evidence)

The stop-state machine is per-control and silently non-reentrant, and the finalize window it has to cover is **unbounded**:

1. **Each control mutates only the UI it knows about, in its own click handler.**
   - Tray path `app.py:238-243` (`toggle_recording`): sets the tray action to "Stopping…"+disabled AND calls `gallery.set_stopping()` — both controls reset.
   - Toolbar path `gallery.py:922-928` (`_toggle_record`): calls only `self.set_stopping()` (`gallery.py:938-941`). **The tray action is never touched** — after a toolbar-initiated stop the tray item stays *enabled* with a stale "Stop recording (N:NN)" label for the entire finalize window (the elapsed ticks freeze because `record.py:343-344` `_check_alive` early-returns once `_stopping` is set).

2. **A second Stop click is a silent no-op.** `record.py:127-131` `stop()` returns immediately when `self._stopping` is already true or `self._proc is None` — correct against double-finalize, but it gives zero feedback. Clicking the stale, still-enabled tray "Stop recording" item during a toolbar-initiated finalize does *literally nothing*: no state change, no toast, no UI change. That is the dead control.

3. **The finalize window is not brief — gst-launch's EOS wait can wedge indefinitely.** Hard forensics from Jack's machine, 2026-06-06: four orphaned tmp files in `<library>/.rendering/` (15:47, 15:57, 16:15, 16:25 — recordings that never finalized), and the journal shows `pipewire-pulse … [gst-launch-1.0] overrun recover` spam at 16:28 — a gst process still wedged **3+ minutes** after EOS was requested for the 16:25 recording. While EOS is wedged the only resolution is `_poll_exit`'s 15-second SIGKILL (`record.py:357-364`), after which `record.py:375-379` **deletes the partial recording** and emits a failure that doesn't even include the gst log tail (`record.py:378-379`). Net user experience: "Stop did nothing" — the recording keeps going (or vanishes), and whichever Stop control was pressed second is dead by (2).

### The fix shape

- `ScreenRecorder` gains a `stopping` signal — emitted exactly once when a stop transition begins. ALL stop-side UI (tray + toolbar) subscribes to it; the click handlers shrink to `recorder.stop()` / start-request only. Either control stops; both always reset on `stopping`→`finished`/`failed`.
- The finalize loop escalates instead of waiting 15 s: SIGINT (EOS) → after `GRACE_MS` a **second SIGINT** (gst-launch aborts a wedged EOS wait on the second interrupt) → after `KILL_MS` SIGKILL. Failure messages include the gst log tail.
- Stale `.rendering` leftovers (the four orphans exist today) are swept on the next launch.

---

## File Structure

```
wondershot/
  record.py          # Task 1: stopping signal, escalation ladder, log tail in failure, sweep_stale_tmp
  app.py             # Task 2: signal-driven stop UI, record_requested wiring; Task 3: tray tooltip; Task 5: countdown gate
  gallery.py         # Task 2: record_requested signal, _toggle_record simplification, stopping→set_stopping
  settings.py        # Task 4: record_countdown property
  settings_dialog.py # Task 4: countdown spinbox (recording settings live on the General tab — there is no separate Recording tab)
  countdown.py       # Task 5: NEW — frameless always-on-top CountdownOverlay
tests/
  test_record.py            # Task 1: new recorder-level tests appended
  test_record_sync.py       # Task 2: NEW — both-ways stop sync regression (the tray-stop bug test)
  test_tray_tooltip.py      # Task 3: NEW
  test_settings_recording.py        # Task 4: NEW
  test_settings_dialog_recording.py # Task 4: NEW
  test_countdown.py         # Task 5: NEW — overlay + app wiring
ROADMAP.md           # Tasks 6, 7: pause/resume findings, region-only note
spikes/
  pause_resume_probe.md     # Task 6: NEW — spike transcript
```

### Cross-track file coordination (batch 3 runs in parallel — read before editing)

- **`gallery.py` is owned by Track 3b (sidecar persistence).** This track's edits are confined to three small, non-overlapping regions: the class-level signal block (~line 334-337, one added line), the recorder-signal block in `__init__` (~line 454-457, one added line), and `_toggle_record`/`set_stopping` (~lines 922-941). Track 3b's work is in the editor-open/save/trash paths — no contact. Do NOT touch anything else in gallery.py; if a conflict appears at merge time, this track's gallery.py diff is small enough to rebase trivially.
- **`settings.py` / `settings_dialog.py` are known-shared across batch-3 tracks** (Track 3c adds blur/GIF settings). Task 4 is append-only: one new property after `noise_suppression` (settings.py), one new spinbox row after the `noise_check` row plus one line in `apply()` (settings_dialog.py). Keep it to exactly those insertions.
- **`ROADMAP.md` is known-shared.** Tasks 6-7 append to the recording section only; expect merge-time conflicts to be append/append and resolve by keeping both.
- `record.py`, `app.py`, `countdown.py`, and all new test files are exclusively this track's.

---

## Task 1: Recorder — `stopping` signal, EOS-hang escalation, log tail in failures, stale-tmp sweep

**Files:**
- `wondershot/record.py`
- `tests/test_record.py`

### Step 1.1: Failing tests

- [x] Append to `tests/test_record.py` (it already has `qapp`, `FakeSettings`, `make_recorder`, `wait_until`, `dead_proc` helpers at lines 19-50 — reuse them):

```python
def test_stop_emits_stopping_exactly_once(qapp, tmp_path):
    """Both UIs key their 'Stopping…' state off this signal; a second
    stop click (tray after toolbar) must not re-emit."""
    rec = make_recorder(tmp_path)
    proc = subprocess.Popen(["sleep", "30"])
    rec._proc = proc
    rec.recording = True
    rec._tmp = str(tmp_path / ".rendering" / "r.mp4")
    rec._out = str(tmp_path / "r.mp4")
    stops = []
    rec.stopping.connect(lambda: stops.append(1))
    done = []
    rec.failed.connect(lambda m: done.append(m))
    rec.finished.connect(lambda p: done.append(p))
    rec.stop()
    rec.stop()  # the second control's click: silent no-op, no re-emit
    assert stops == [1]
    assert wait_until(qapp, lambda: done, 5)
    proc.poll() is not None or (proc.kill(), proc.wait())


def test_stop_escalates_when_eos_wait_wedges(qapp, tmp_path):
    """2026-06-06 forensics: gst-launch wedged in 'Waiting for EOS' for
    3+ minutes (journal pulse overruns, orphaned .rendering tmp). The
    finalize loop must escalate: SIGINT -> second SIGINT -> SIGKILL."""
    rec = make_recorder(tmp_path)
    # a child that ignores SIGINT entirely == a wedged EOS wait
    proc = subprocess.Popen(["bash", "-c", 'trap "" INT; sleep 60'])
    rec._proc = proc
    rec.recording = True
    rec._tmp = str(tmp_path / ".rendering" / "r.mp4")
    rec._out = str(tmp_path / "r.mp4")
    rec.GRACE_MS = 400   # speed the ladder up for the test
    rec.KILL_MS = 900
    log = tmp_path / "recorder.log"
    log.write_text("gst output\nERROR: from element mux: wedged\n")
    rec.log_path = str(log)
    results = []
    rec.failed.connect(lambda m: results.append(m))
    rec.finished.connect(lambda p: results.append(p))
    rec.stop()
    assert wait_until(qapp, lambda: results, 8), \
        "escalation must finalize a SIGINT-ignoring pipeline"
    assert rec.recording is False
    assert rec._proc is None
    assert "ERROR" in results[0], \
        "the did-not-finalize message must surface the gst log tail"
    proc.poll() is not None or (proc.kill(), proc.wait())


def test_sweep_stale_tmp_removes_old_orphans_only(tmp_path):
    """Four orphaned mp4s sat in .rendering on 2026-06-06 (EOS wedges +
    app restarts). Old files are dead; fresh ones may be live."""
    import time as _time
    from wondershot.record import sweep_stale_tmp
    d = tmp_path / ".rendering"
    d.mkdir()
    old = d / "Recording_old.mp4"
    old.write_bytes(b"x")
    os.utime(old, (_time.time() - 7200, _time.time() - 7200))
    fresh = d / "Recording_fresh.mp4"
    fresh.write_bytes(b"x")
    sweep_stale_tmp(str(d))
    assert not old.exists()
    assert fresh.exists()
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record.py -q`
      Expected: the three new tests FAIL — `AttributeError: 'ScreenRecorder' object has no attribute 'stopping'`, `AttributeError ... GRACE_MS`, and `ImportError: cannot import name 'sweep_stale_tmp'`. The 7 pre-existing tests still pass.

### Step 1.2: Implementation

- [x] In `wondershot/record.py`, add the signal and ladder constants to `ScreenRecorder` (currently lines 81-84):

```python
    started = Signal()
    stopping = Signal()  # a stop transition began (whichever control asked)
    finished = Signal(str)  # final file path
    failed = Signal(str)
    tick = Signal(str)  # elapsed time ("1:05"), once a second while recording

    # Finalize escalation ladder. gst-launch -e can wedge in "Waiting for
    # EOS" indefinitely (observed 2026-06-06: pipeline still draining-
    # failing 3+ min after SIGINT — journal pipewire-pulse overruns,
    # orphaned .rendering tmp). A SECOND SIGINT makes gst-launch abort
    # the EOS wait and exit; SIGKILL is the last resort.
    GRACE_MS = 5000
    KILL_MS = 10000
```

- [x] Replace `stop()` (record.py lines 127-138) with:

```python
    def stop(self) -> None:
        if self._stopping:
            return  # double-stop (tray + toolbar) must not double-finalize
        if self._proc is None:
            return
        self._stopping = True
        self.stopping.emit()
        if self._proc.poll() is None:
            # -e turns SIGINT into EOS: the mp4 finalizes, then exits.
            self._proc.send_signal(signal.SIGINT)
        # Even if the pipeline already died (mux error etc.), finalize so
        # finished/failed always fires — the UI must never stay "Stopping".
        self._poll_exit(elapsed_ms=0)
```

- [x] Replace `_poll_exit()` (record.py lines 357-379) with:

```python
    def _poll_exit(self, elapsed_ms: int = 0, nudged: bool = False) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            if elapsed_ms >= self.KILL_MS:
                self._proc.kill()
            elif elapsed_ms >= self.GRACE_MS and not nudged:
                # second interrupt: gst-launch gives up waiting for EOS
                self._proc.send_signal(signal.SIGINT)
                nudged = True
            QTimer.singleShot(
                200, lambda: self._poll_exit(elapsed_ms + 200, nudged))
            return
        self.recording = False
        ok = (self._proc.returncode == 0 and self._tmp
              and os.path.exists(self._tmp)
              and os.path.getsize(self._tmp) > 0)
        tmp, out = self._tmp, self._out
        self._cleanup()
        if ok:
            shutil.move(tmp, out)
            self.finished.emit(out)
        else:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
            self.failed.emit(
                f"recording did not finalize: {self._log_tail()[:160]} "
                f"(log: {getattr(self, 'log_path', '?')})")
```

      Note: the old signature was `_poll_exit(self, timeout_ms)` counting *down*; the only caller is `stop()`, updated above. `test_stop_with_dead_pipeline_emits_signal` calls `stop()`, not `_poll_exit`, so it keeps passing.

- [x] Add `sweep_stale_tmp` as a module-level function (place it just above `class ScreenRecorder`, after `mic_pulse_device`):

```python
def sweep_stale_tmp(tmp_dir: str, max_age_s: int = 3600) -> None:
    """Remove finalize leftovers from crashed/quit-while-recording runs.

    2026-06-06 forensics: four orphaned mp4s in <library>/.rendering.
    A live recording's tmp has a fresh mtime (filesink writes
    continuously), so anything older than max_age_s is dead.
    """
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        return
    now = time.time()
    for name in names:
        path = os.path.join(tmp_dir, name)
        try:
            if now - os.path.getmtime(path) > max_age_s:
                os.unlink(path)
        except OSError:
            pass
```

- [x] Call it in `_launch_gst` right after the tmp dir is created (record.py line 295 `os.makedirs(tmp_dir, exist_ok=True)`):

```python
        os.makedirs(tmp_dir, exist_ok=True)
        sweep_stale_tmp(tmp_dir)
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record.py -q`
      Expected: all tests pass (10 total in this file).

- [x] Run the full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`
      Expected: green (186 pre-existing + 3 new).

- [x] Commit: `git add -A && git commit -m "record: stopping signal, EOS-wedge escalation, log tail in failures, stale tmp sweep"`

---

## Task 2: Both-ways stop sync — either control stops, both reset (THE tray-stop fix)

**Files:**
- `wondershot/app.py`
- `wondershot/gallery.py`
- `tests/test_record_sync.py` (new)

### Step 2.1: Failing regression test

This test encodes Jack's exact bug: stop from one control, the *other* control must immediately reflect "stopping" and both must reset afterwards.

**Gotcha — these tests construct the real `GrabbitApp`, which (a) listens on the single-instance socket and (b) reads real `Settings()`. Both MUST be patched or the test suite will hijack the live Wondershot instance's socket and real config on a dev box.**

- [x] Create `tests/test_record_sync.py`:

```python
"""Either record control (tray menu / gallery toolbar) must stop a
recording, and BOTH must reset — recorder signals drive all stop UI.

Regression for: tray Stop did nothing after a toolbar-initiated stop —
the toolbar path never touched the tray action (stale enabled 'Stop
recording'), and the second stop() was a silent no-op (record.py)."""
import itertools
import os
import subprocess
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="drives POSIX subprocesses")

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
                 "share_expiry_days", "quick_bar_timeout"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick", "capture_cursor",
                                      "record")) else ""


def make_app(qapp, tmp_path, monkeypatch):
    import wondershot.app as appmod
    from wondershot.hotkey import NullHotkeyBackend
    # NEVER touch the real single-instance socket or real QSettings.
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-test-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings",
                        lambda: _Settings(str(tmp_path)))
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    return appmod.GrabbitApp(qapp)


def fake_recording(a, tmp_path):
    """Put the real recorder into an in-flight state around a live proc."""
    proc = subprocess.Popen(["sleep", "30"])
    rec = a.recorder
    rec._proc = proc
    rec.recording = True
    d = tmp_path / ".rendering"
    d.mkdir(exist_ok=True)
    rec._tmp = str(d / "r.mp4")
    rec._out = str(tmp_path / "r.mp4")
    (d / "r.mp4").write_bytes(b"x")
    a._on_recording_started()  # what recorder.started would have done
    return proc


def wait_until(qapp, cond, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_toolbar_stop_resets_tray_action(qapp, tmp_path, monkeypatch):
    """Jack's bug: after a TOOLBAR stop, the tray item stayed enabled and
    stale; clicking it did nothing."""
    a = make_app(qapp, tmp_path, monkeypatch)
    proc = fake_recording(a, tmp_path)
    try:
        a.gallery._toggle_record()  # toolbar Stop
        # the TRAY action must immediately show the stop is in flight
        assert not a.record_action.isEnabled()
        assert a.record_action.text() == "Stopping…"
        assert not a.gallery.record_action.isEnabled()
        # sleep exits on SIGINT (rc != 0) -> failed path; BOTH reset
        assert wait_until(qapp, lambda: a.record_action.isEnabled(), 8)
        assert a.record_action.text() == "Record screen…"
        assert a.gallery.record_action.isEnabled()
        assert a.gallery.record_action.text() == "Record"
    finally:
        proc.poll() is not None or (proc.kill(), proc.wait())


def test_tray_stop_resets_toolbar_action(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    proc = fake_recording(a, tmp_path)
    try:
        a.toggle_recording()  # tray Stop
        assert not a.gallery.record_action.isEnabled()
        assert a.gallery.record_action.text() == "Stopping…"
        assert not a.record_action.isEnabled()
        assert wait_until(qapp, lambda: a.record_action.isEnabled(), 8)
        assert a.gallery.record_action.text() == "Record"
        assert a.record_action.text() == "Record screen…"
    finally:
        proc.poll() is not None or (proc.kill(), proc.wait())


def test_toolbar_record_start_routes_through_app(qapp, tmp_path,
                                                 monkeypatch):
    """Starts funnel through the app coordinator (where the countdown
    gate will live), from every entry point."""
    a = make_app(qapp, tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a.gallery._toggle_record()       # toolbar Record while idle
    assert started == [1]
    a.toggle_recording()             # tray Record while idle
    assert started == [1, 1]
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_sync.py -q`
      Expected: `test_toolbar_stop_resets_tray_action` FAILS at `assert not a.record_action.isEnabled()` (the tray action is untouched by the toolbar path — the bug). `test_toolbar_record_start_routes_through_app` FAILS (gallery calls `recorder.start()` directly today). `test_tray_stop_resets_toolbar_action` passes already (the tray path does call `gallery.set_stopping()`); keep it as the mirror regression.

### Step 2.2: Implementation

- [x] `wondershot/gallery.py` — add the start-request signal to `GalleryWindow`'s signal block (lines 334-337):

```python
class GalleryWindow(QMainWindow):
    quit_requested = Signal()
    settings_applied = Signal()
    oauth_callback = Signal(str)  # wondershot://auth?... redirect URL
    capture_requested = Signal(str)  # routed through app.trigger_capture
    record_requested = Signal()  # start a recording (app owns countdown/start)
```

- [x] `wondershot/gallery.py` — in `__init__`, extend the existing recorder-signal block (lines 454-457) so the toolbar's stopping state is recorder-driven:

```python
        if self.recorder is not None:
            self.recorder.tick.connect(
                lambda t: self.record_action.setText(f"Stop {t}" if t
                                                     else "Stop"))
            self.recorder.stopping.connect(self.set_stopping)
```

- [x] `wondershot/gallery.py` — replace `_toggle_record` (lines 922-930):

```python
    def _toggle_record(self) -> None:
        if self.recorder is None:
            self.capture.record_region()  # spectacle fallback
            return
        if self.recorder.recording:
            self.recorder.stop()  # recorder.stopping resets BOTH controls
        else:
            self.record_requested.emit()
```

- [x] `wondershot/app.py` — in `__init__`, connect the new signals. After line 77 (`self.recorder.failed.connect(...)`) add:

```python
        self.recorder.stopping.connect(self._on_recording_stopping)
```

  and after line 83 (`self.gallery.capture_requested.connect(self.trigger_capture)`) add:

```python
        self.gallery.record_requested.connect(self._begin_recording)
```

- [x] `wondershot/app.py` — replace `toggle_recording` (lines 238-245) and add the two new methods:

```python
    def toggle_recording(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()  # recorder.stopping resets BOTH controls
        else:
            self._begin_recording()

    def _begin_recording(self) -> None:
        # Task 5 puts the countdown gate here; until then, start directly.
        self.recorder.start()

    def _on_recording_stopping(self) -> None:
        # The gallery toolbar resets itself via its own stopping
        # connection (gallery.py __init__); only the tray is ours.
        self.record_action.setText("Stopping…")
        self.record_action.setEnabled(False)
```

  Note `gallery.set_stopping()` is no longer called from `toggle_recording` — the recorder's `stopping` signal reaches the gallery directly. The reset path is unchanged: `_on_recording_finished` (app.py:255-263) / `_on_recording_failed` (app.py:265-270) re-enable the tray action and call `gallery.set_recording(False)`, which re-enables the toolbar (gallery.py:932-936).

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_sync.py tests/test_record.py -q`
      Expected: all pass.

- [x] Run the full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`
      Expected: green.

- [x] Commit: `git add -A && git commit -m "recording: either control stops, both reset (recorder-signal-driven stop UI)"`

---

## Task 3: Recording duration in the tray tooltip

**Files:**
- `wondershot/app.py`
- `tests/test_tray_tooltip.py` (new)

### Step 3.1: Failing test

- [x] Create `tests/test_tray_tooltip.py` (the `make_app` fixture is repeated verbatim from `tests/test_record_sync.py` — same `_Settings`, `_counter`, `qapp`; copy lines 1-60 of that file's helpers, then add):

```python
"""The tray tooltip mirrors the recording duration (recorder.tick)."""
import itertools
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
                 "share_expiry_days", "quick_bar_timeout"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick", "capture_cursor",
                                      "record")) else ""


def make_app(qapp, tmp_path, monkeypatch):
    import wondershot.app as appmod
    from wondershot.hotkey import NullHotkeyBackend
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-tt-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings",
                        lambda: _Settings(str(tmp_path)))
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    return appmod.GrabbitApp(qapp)


def test_tick_updates_tray_tooltip_and_action(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    a.recorder.tick.emit("1:05")
    assert a.tray.toolTip() == "Wondershot — recording 1:05"
    assert a.record_action.text() == "Stop recording (1:05)"


def test_tooltip_resets_when_recording_ends(qapp, tmp_path, monkeypatch):
    a = make_app(qapp, tmp_path, monkeypatch)
    a.recorder.tick.emit("0:10")
    a._on_recording_failed("boom")
    assert a.tray.toolTip() == "Wondershot — screenshots"
    a.recorder.tick.emit("0:11")
    p = str(tmp_path / "r.mp4")
    open(p, "wb").write(b"x")
    a._on_recording_finished(p)
    assert a.tray.toolTip() == "Wondershot — screenshots"
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_tray_tooltip.py -q`
      Expected: both FAIL — tooltip stays "Wondershot — screenshots" during ticks (first test's first assert).

### Step 3.2: Implementation

- [x] `wondershot/app.py` — replace the tick lambda (lines 97-99):

```python
        self.recorder.tick.connect(self._on_recording_tick)
```

  and add the method (next to `_on_recording_stopping`):

```python
    def _on_recording_tick(self, t: str) -> None:
        self.record_action.setText(
            f"Stop recording ({t})" if t else "Stop recording")
        self.tray.setToolTip(
            f"Wondershot — recording {t}" if t
            else "Wondershot — screenshots")
```

- [x] `wondershot/app.py` — reset the tooltip in both end states. In `_on_recording_finished` (after line 258 `self.gallery.set_recording(False)`) and in `_on_recording_failed` (after line 268 `self.gallery.set_recording(False)`) add:

```python
        self.tray.setToolTip("Wondershot — screenshots")
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_tray_tooltip.py tests/test_record_sync.py -q`
      Expected: all pass.

- [x] Commit: `git add -A && git commit -m "tray: show recording duration in the tooltip; reset on finish/fail"`

---

## Task 4: Countdown-before-start setting (settings + dialog)

**Files:**
- `wondershot/settings.py`
- `wondershot/settings_dialog.py`
- `tests/test_settings_recording.py` (new)
- `tests/test_settings_dialog_recording.py` (new)

Recording settings (mic, camera, noise suppression) currently live on the **General** tab of `SettingsDialog` (settings_dialog.py lines 159-188) — there is no separate Recording tab; the spinbox goes in that block. Do not create a new tab.

### Step 4.1: Failing tests

- [x] Create `tests/test_settings_recording.py` (mirrors `tests/test_settings_quickbar.py`):

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_record_countdown_default_off(tmp_path):
    s = make_settings(tmp_path)
    assert s.record_countdown == 0


def test_record_countdown_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.record_countdown = 3
    assert s.record_countdown == 3
```

- [x] Create `tests/test_settings_dialog_recording.py` (mirrors `tests/test_settings_dialog_quickbar.py`):

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_apply_writes_record_countdown(qapp, tmp_path):
    from wondershot.settings_dialog import SettingsDialog
    s = make_settings(tmp_path)
    s.library_dir = str(tmp_path)  # keep the dialog off the real library
    dlg = SettingsDialog(s)
    assert dlg.countdown_spin.value() == 0
    assert dlg.countdown_spin.minimum() == 0
    assert dlg.countdown_spin.maximum() == 10
    dlg.countdown_spin.setValue(5)
    dlg.apply()
    assert s.record_countdown == 5
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_recording.py tests/test_settings_dialog_recording.py -q`
      Expected: FAIL — `AttributeError: ... record_countdown` / `... countdown_spin`.

### Step 4.2: Implementation

- [x] `wondershot/settings.py` — add after the `noise_suppression` property (lines 91-97):

```python
    @property
    def record_countdown(self) -> int:
        """Seconds of on-screen countdown before a recording starts (0 = off)."""
        return int(self._s.value("record_countdown", 0))

    @record_countdown.setter
    def record_countdown(self, value: int) -> None:
        self._s.setValue("record_countdown", int(value))
```

- [x] `wondershot/settings_dialog.py` — after the `noise_check` row (line 188 `form.addRow("", self.noise_check)`) add:

```python
        self.countdown_spin = QSpinBox()
        self.countdown_spin.setRange(0, 10)
        self.countdown_spin.setSuffix(" s")
        self.countdown_spin.setSpecialValueText("Off")
        self.countdown_spin.setValue(settings.record_countdown)
        self.countdown_spin.setToolTip(
            "Count down on screen before a recording starts (Esc cancels)")
        form.addRow("Recording countdown:", self.countdown_spin)
```

  `QSpinBox` is already imported in settings_dialog.py (used by `quickbar_timeout` at line 151).

- [x] `wondershot/settings_dialog.py` — in `apply()`, after line 682 (`self.settings.noise_suppression = ...`) add:

```python
        self.settings.record_countdown = self.countdown_spin.value()
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_recording.py tests/test_settings_dialog_recording.py -q`
      Expected: pass.

- [x] Commit: `git add -A && git commit -m "settings: recording countdown (0-10 s, default off) on the General tab"`

---

## Task 5: Countdown overlay + app wiring

**Files:**
- `wondershot/countdown.py` (new)
- `wondershot/app.py`
- `tests/test_countdown.py` (new)

### Step 5.1: Failing tests

- [x] Create `tests/test_countdown.py`:

```python
"""CountdownOverlay: ticks to finished; Esc/click/close cancels.

App wiring: countdown=0 starts the recorder immediately; countdown>0
defers start until the overlay finishes; cancel never starts."""
import itertools
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_counter = itertools.count()


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(qapp, cond, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_overlay_counts_down_to_finished(qapp):
    from wondershot.countdown import CountdownOverlay
    cd = CountdownOverlay(3, interval_ms=20)
    got = {"finished": 0, "cancelled": 0}
    cd.finished.connect(lambda: got.__setitem__("finished",
                                                got["finished"] + 1))
    cd.cancelled.connect(lambda: got.__setitem__("cancelled",
                                                 got["cancelled"] + 1))
    cd.show()
    assert cd.label.text() == "3"
    assert wait_until(qapp, lambda: got["finished"], 3)
    assert got == {"finished": 1, "cancelled": 0}


def test_overlay_esc_cancels(qapp):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from wondershot.countdown import CountdownOverlay
    cd = CountdownOverlay(5, interval_ms=10_000)
    got = {"finished": 0, "cancelled": 0}
    cd.finished.connect(lambda: got.__setitem__("finished", 1))
    cd.cancelled.connect(lambda: got.__setitem__("cancelled", 1))
    cd.show()
    cd.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                               Qt.NoModifier))
    qapp.processEvents()
    assert got == {"finished": 0, "cancelled": 1}


def test_overlay_close_emits_cancelled_once(qapp):
    from wondershot.countdown import CountdownOverlay
    cd = CountdownOverlay(5, interval_ms=10_000)
    got = []
    cd.cancelled.connect(lambda: got.append(1))
    cd.show()
    cd.close()
    qapp.processEvents()
    assert got == [1]


# ---- app wiring (make_app repeated from tests/test_record_sync.py) ----

class _Settings:
    def __init__(self, library_dir):
        self.library_dir = library_dir
        self.extra_dirs = []
        self.record_countdown = 0

    def __getattr__(self, k):
        if k in ("stroke_width", "font_size", "capture_delay",
                 "share_expiry_days", "quick_bar_timeout"):
            return 10
        if k == "tool_color":
            return "#e3242b"
        return False if k.startswith(("pin", "show", "mic", "noise",
                                      "copy", "quick",
                                      "capture_cursor")) else ""


def make_app(qapp, tmp_path, monkeypatch):
    import wondershot.app as appmod
    from wondershot.hotkey import NullHotkeyBackend
    settings = _Settings(str(tmp_path))
    monkeypatch.setattr(
        appmod, "server_name",
        lambda n=next(_counter): f"wondershot-cd-{os.getpid()}-{n}")
    monkeypatch.setattr(appmod, "Settings", lambda: settings)
    monkeypatch.setattr(appmod, "create_hotkey_backend",
                        lambda parent=None: NullHotkeyBackend())
    return appmod.GrabbitApp(qapp), settings


def test_zero_countdown_starts_immediately(qapp, tmp_path, monkeypatch):
    a, settings = make_app(qapp, tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a._begin_recording()
    assert started == [1]
    assert getattr(a, "_countdown", None) is None


def test_countdown_defers_then_starts(qapp, tmp_path, monkeypatch):
    a, settings = make_app(qapp, tmp_path, monkeypatch)
    settings.record_countdown = 2
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a._begin_recording()
    assert started == []          # deferred
    assert a._countdown is not None
    a._countdown._timer.setInterval(20)  # fast-forward for the test
    assert wait_until(qapp, lambda: started, 3)
    assert started == [1]
    assert a._countdown is None


def test_second_press_cancels_countdown(qapp, tmp_path, monkeypatch):
    a, settings = make_app(qapp, tmp_path, monkeypatch)
    settings.record_countdown = 5
    started = []
    monkeypatch.setattr(a.recorder, "start", lambda: started.append(1))
    a._begin_recording()
    assert a._countdown is not None
    a._begin_recording()          # press again = cancel, not start
    qapp.processEvents()
    assert started == []
    assert a._countdown is None
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_countdown.py -q`
      Expected: FAIL — `ModuleNotFoundError: No module named 'wondershot.countdown'`, and the wiring tests fail on `_countdown` behavior.

### Step 5.2: Implementation

- [x] Create `wondershot/countdown.py`:

```python
"""Frameless on-screen countdown shown before a recording starts.

Wayland clients can't self-position; like the bubble and the quick bar
the compositor places this window. It only lives a few seconds, so no
KWin position rule is written — default placement is fine. Esc or a
click cancels; closing it any other way also counts as cancel.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class CountdownOverlay(QWidget):
    finished = Signal()   # ticked down to zero — start the recording
    cancelled = Signal()  # Esc / click / closed — do NOT start

    def __init__(self, seconds: int, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("wondershot countdown")
        self._left = max(1, int(seconds))
        self._done = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 24, 48, 24)
        self.label = QLabel(str(self._left), self)
        font = QFont()
        font.setPointSize(64)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        hint = QLabel("Esc to cancel", self)
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self._done = True
            self._timer.stop()
            self.finished.emit()
            self.close()
        else:
            self.label.setText(str(self._left))

    def cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.cancelled.emit()
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancel()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, _event) -> None:
        self.cancel()

    def closeEvent(self, event) -> None:
        if not self._done:  # closed by the WM/user: treat as cancel
            self._done = True
            self._timer.stop()
            self.cancelled.emit()
        super().closeEvent(event)
```

- [x] `wondershot/app.py` — replace `_begin_recording` (added in Task 2) with the countdown gate, and add the two handlers:

```python
    def _begin_recording(self) -> None:
        cd = getattr(self, "_countdown", None)
        if cd is not None:
            try:
                cd.cancel()  # pressing Record again during the countdown
            except RuntimeError:
                pass  # already deleted (WA_DeleteOnClose)
            self._countdown = None
            return
        secs = int(getattr(self.settings, "record_countdown", 0) or 0)
        if secs <= 0:
            self.recorder.start()
            return
        from .countdown import CountdownOverlay
        cd = CountdownOverlay(secs)
        cd.finished.connect(self._countdown_finished)
        cd.cancelled.connect(self._countdown_cancelled)
        self._countdown = cd
        cd.show()

    def _countdown_finished(self) -> None:
        self._countdown = None
        self.recorder.start()

    def _countdown_cancelled(self) -> None:
        self._countdown = None
```

  Gotcha: `cancel()` emits `cancelled` synchronously, which sets `self._countdown = None` via `_countdown_cancelled` — the explicit `self._countdown = None` after the `try` is belt-and-braces for the already-deleted case.

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_countdown.py tests/test_record_sync.py -q`
      Expected: all pass (`test_record_sync.py`'s start-routing test still passes because `_Settings.record_countdown` resolves falsy there).

- [x] Run the full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`
      Expected: green.

- [x] Commit: `git add -A && git commit -m "recording: optional on-screen countdown before start (Esc/click cancels)"`

---

## Task 6: Pause/resume — TIMEBOXED spike behind a feasibility gate (default outcome: ROADMAP findings, no implementation)

**Files:**
- `spikes/pause_resume_probe.md` (new)
- `ROADMAP.md`

Timebox: max ~1 hour of spike work. **Do NOT write pause/resume product code unless the gate below passes.** The expected outcome is a documented "no, not with gst-launch" finding.

### Step 6.1: Spike (document everything in `spikes/pause_resume_probe.md`)

Why this is expected to fail — reason from the architecture before running anything:

- The recorder is a `gst-launch-1.0` **argv subprocess** (`record.py:248-288 _gst_args`, `record.py:308-309 Popen`). gst-launch exposes **no runtime control channel**: no way to set the pipeline to `PAUSED`, no way to flip a `valve drop=true/false` property mid-run. Its only inputs are signals, and the only meaningful one is SIGINT (= EOS via `-e`).
- The one externally available "pause" is `SIGSTOP`/`SIGCONT` on the process. That freezes the *process*, not the *pipeline clock*: `pipewiresrc do-timestamp=true` and `pulsesrc do-timestamp=true` stamp buffers with the running pipeline clock, so on `SIGCONT` the buffer PTS jump by the paused wall-time. `mp4mux` writes those timestamps as-is → a frozen-frame gap (and pulse overruns dropping audio, exactly the journal signature from 2026-06-06). Worse, the `videorate` element in the video branch (the no-PTS landmine fix, ROADMAP "Platform landmines": *pipewiresrc intermittently emits buffers with no PTS … videorate + fixed framerate caps drop them and yield CFR output*) will **fill the entire pause gap with duplicated frames** to maintain CFR — silently producing minutes of frozen video instead of a cut.

- [x] Run the SIGSTOP probe on a live KDE session (NOT offscreen) to confirm and capture evidence: *(this session is non-interactive — probe moved to the Manual verification checklist below; the gate fails on architecture grounds regardless)*
  1. Start a recording from the app (worktree build: `.venv/bin/wondershot`, Record).
  2. `kill -STOP $(pgrep -f 'gst-launch-1.0 -e pipewiresrc')`, wait 10 s, `kill -CONT` the same pid, record 5 more seconds, stop normally.
  3. `ffprobe -show_streams <output>.mp4` and play it: expected duration includes the paused 10 s as duplicated frames (videorate backfill) and/or desynced audio.
  4. Paste the ffprobe output and observations into `spikes/pause_resume_probe.md`.

- [x] Write `spikes/pause_resume_probe.md` with: the architecture reasoning above, the probe transcript, and the conclusion.

### Step 6.2: Feasibility gate

- [x] **Gate:** *(FAILED, as expected)* pause/resume ships in this track ONLY IF the probe shows a mechanism that (a) works against a `gst-launch` argv subprocess, and (b) produces gapless, A/V-synced output across a pause. Per the reasoning above this is not expected to exist.
- [x] If the gate FAILS (expected): add the findings to `ROADMAP.md` under the recording section (near the cursor-halo "parked" entry, which already documents the same in-process-pipeline seam), with this text:

```markdown
- Pause/resume (M): **investigated 2026-06-07, parked.** (Use the actual probe-run date.) gst-launch argv
  subprocesses have no runtime control channel — no PAUSED state, no
  valve property flips. SIGSTOP/SIGCONT freezes the process but not the
  pipeline clock: do-timestamp'd buffers jump PTS across the gap, and
  the videorate element (the no-PTS landmine fix) backfills the entire
  pause with duplicated frames to keep CFR — silently wrong output
  (probe transcript: spikes/pause_resume_probe.md). Clean pause needs
  owning the pipeline in-process (gst python bindings / appsink) with
  valves ahead of the mux and accumulated-offset PTS rewriting — the
  same frame-source seam as the cursor halo and WS-D scroll capture;
  pause/resume rides along with that rewrite.
```

- [x] If the gate PASSES (unexpected): *(N/A — gate failed)* STOP and write a follow-up plan instead of improvising — pause touches the stop state machine from Tasks 1-2 and needs its own TDD pass (recorder `paused` state + signal, both-control Pause UI, PTS verification fixture).

- [x] Commit: `git add -A && git commit -m "spike: pause/resume infeasible over gst-launch; findings to ROADMAP (parked)"`

---

## Task 7: ROADMAP note — region-only recording (out of scope, note ONLY)

**Files:**
- `ROADMAP.md`

- [x] Add to `ROADMAP.md`, in the same recording section as the Task 6 note:

```markdown
- Region-only recording (M): out of scope for now. The portal ScreenCast
  source types are monitor|window (record.py SelectSources `types: 3`) —
  there is no region source on Wayland. A fixed crop *could* be injected
  at launch time (`videocrop` after videoconvert in _gst_args, with a
  region picked by the existing region selector before the portal dance),
  but mid-recording region changes and DPI/multi-monitor mapping need the
  same in-process pipeline rewrite as pause/resume and the cursor halo.
  Design crop-in-pipeline alongside that seam; do not bolt onto gst-launch.
```

- [x] Run the full suite one final time: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`
      Expected: green.

- [x] Commit: `git add -A && git commit -m "roadmap: region-only recording parked (portal has no region source)"`

---

## Out of scope / explicitly NOT in this track

- Region-only recording implementation (Task 7 note only).
- Pause/resume implementation unless the Task 6 gate passes (not expected).
- The `toggle_bubble` RuntimeError (`CameraBubble already deleted` — journal tracebacks 2026-06-06 16:03/16:47/16:48, current code `app.py:282-293`): real adjacent bug, belongs to the bubble owner's track; flag it to the orchestrator rather than fixing here.
- Quitting the app while recording orphans the gst process (the `.rendering` orphans' root source): Task 1's sweep cleans the leftovers; a clean shutdown-stop belongs with the quit/lifecycle work — note for the orchestrator.

---

## Manual verification checklist (live KDE session — not runnable offscreen)

- [ ] Tray-stop bug fix: start a recording, stop it from the GALLERY toolbar —
      the tray item must immediately flip to a disabled "Stopping…" and both
      controls must reset afterwards. Repeat stopping from the TRAY item and
      confirm the toolbar mirrors it.
- [ ] Double-stop: while a stop is finalizing, click the other Stop control —
      it must already be disabled (no dead-click possible).
- [ ] Tray tooltip: hover the tray icon during a recording — it must read
      "Wondershot — recording N:NN" and revert to "Wondershot — screenshots"
      after finish/fail.
- [ ] EOS-wedge escalation: if a stop ever takes more than ~5 s, confirm the
      recording still finalizes within ~10 s (second SIGINT, then SIGKILL) and
      that on the SIGKILL path the partial recording is KEPT in the library
      (failure toast says "partial recording kept: …").
- [ ] Stale-tmp sweep: with old orphans in `<library>/.rendering` (the four
      from 2026-06-06), start a recording — orphans older than 1 h are removed;
      the live recording's tmp is untouched.
- [ ] Countdown: set Recording countdown to 3 s in Settings → General, hit
      Record — a frameless always-on-top 3-2-1 overlay shows, then recording
      starts. Esc (or clicking the overlay, or pressing Record again) cancels
      without starting.
- [ ] Task 6 SIGSTOP probe (evidence capture only — gate already failed on
      architecture): start a recording, `kill -STOP $(pgrep -f
      'gst-launch-1.0 -e pipewiresrc')`, wait 10 s, `kill -CONT` the pid,
      record 5 more seconds, stop. `ffprobe -show_streams <output>.mp4` —
      expect the paused 10 s present as duplicated frames / desynced audio.
      Paste results into `spikes/pause_resume_probe.md`.
