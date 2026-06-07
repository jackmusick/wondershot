# In-Process Recorder Pipeline + Cursor Halo / Pause-Resume / Region-Only

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Foundation tasks (A1–A3) land FIRST and each leaves the suite green before any feature task starts.

**Goal:** Convert the Linux `ScreenRecorder` (`wondershot/record.py`) from a `gst-launch-1.0 -e` *subprocess* to an **in-process** GStreamer pipeline (the appsink technique `scrollsource.py` already uses), preserving every observable behavior; then layer three features the subprocess design blocked: (B) translucent cursor halo, (C) pause/resume, (D) region-only recording. Honors spec Addendum 4 (`docs/superpowers/specs/2026-06-06-snagit-parity-design.md`) exactly.

**Architecture:** `ScreenRecorder` (QObject) runs the xdg-desktop-portal ScreenCast dance (`CreateSession → SelectSources → Start → OpenPipeWireRemote`) over Gio/GLib, then hands the PipeWire `fd`+`node` to `_launch_gst`. Today `_launch_gst` spawns `gst-launch-1.0` and the lifecycle is driven by `subprocess.Popen.poll()` + POSIX signals. After this work, `_launch_gst` builds an in-process `Gst.Pipeline` (`Gst.parse_launch`) ending in the **verbatim** `videorate → fixed-framerate caps → x264enc → h264parse → mp4mux → filesink` chain, and the lifecycle is driven by a `GstBus` + pipeline state. The subprocess `_proc` field is replaced by a thin `_GstPipeline` wrapper exposing a tiny, fakeable surface (`poll_status() → "running"|"eos"|"error"`, `send_eos()`, `force_stop()`, `error_text()`, `pause()`, `resume()`). All decision logic (description building, salvage, escalation ladder, clock/PTS bookkeeping, crop math, halo math) lives in **pure module functions** that import no Gst, so the entire behavioral test suite runs headless on CI; only new live-pipeline smoke tests (videotestsrc, **no portal**) import Gst behind `importorskip`.

The portal restore-token hooks (`_restore_token`/`_save_restore_token`), the `_created`/`_sources_selected`/`_started_cb` dance, `_fail`, `_busy`, `recording`, and the `_launch_gst(fd, node)` hook signature are PRESERVED — `scrollsource.py` subclasses `ScreenRecorder`, overrides `_launch_gst`+`stop` with its OWN appsink pipeline, and MUST keep working untouched. `winrecord.py` (Windows, QProcess+ffmpeg) is UNTOUCHED; the `create_screen_recorder` `sys.platform` factory stays.

**Tech Stack:** Python 3.14, PySide6 (Qt 6), GStreamer 1.x via PyGObject (`gi.repository.Gst`) — in-process, NOT `gst-launch`; xdg-desktop-portal ScreenCast via Gio/GLib (system `gi`; typed `GLib.Variant` options — PySide6 QtDBus cannot produce uint32 variants, see Platform landmine); pytest with `QT_QPA_PLATFORM=offscreen`.

**Execution environment:** Worktree ALREADY EXISTS at `/home/jack/GitHub/grabbit-wt/recorder-inproc` on branch `session/recorder-inproc`. Create the venv there:

```bash
cd /home/jack/GitHub/grabbit-wt/recorder-inproc
python -m venv .venv --system-site-packages   # --system-site-packages: gi/Gst live on the system, not on PyPI
.venv/bin/pip install -e ".[spike]" pytest
```

`--system-site-packages` is mandatory: `gi`/`Gst`/`Gio`/`GLib` come from the OS, and the `[spike]` extra pulls numpy needed for test *collection* (stitch tests import it). The Linux dev box HAS gi/Gst, so live-pipeline smoke tests run here; CI (ubuntu/windows/macos) may lack gi → those tests `importorskip`. Run the suite as:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
```

---

## Platform landmines that govern this work (re-read before Task A1)

From `ROADMAP.md` "Platform landmines" and Addendum 4:

1. **No-PTS / videorate (CRITICAL, keep VERBATIM):** `pipewiresrc` intermittently emits buffers with no PTS near stream start even with `do-timestamp=true`; `mp4mux` aborts the *whole* pipeline on the first one ("Buffer has no PTS"). `videorate` + fixed-framerate caps drop them and yield CFR. The `videorate ! video/x-raw,format=I420,framerate=30/1` segment and the `x264enc`/`mp4mux` token *values* copy across **token-for-token** — the only structural addition is the transparent `identity name=pause` tap (a no-op until C1), inserted on the raw-frame side of `x264enc`.
2. **Watchdog the whole life, never hang on "Stopping":** a single startup liveness check misses later death (mux errors minutes in) and the UI hangs. The 1 s watchdog stays; bus ERROR/EOS is now the death signal.
3. **Typed variants via Gio:** portal options must be `GLib.Variant` (e.g. `cursor_mode` is `"u"` uint32). The existing `_created`/`SelectSources` code already does this; the halo feature only changes the `cursor_mode` value (2→4), still as `GLib.Variant("u", ...)`.
4. **KGlobalAccel:** not touched here, but the defensive-D-Bus discipline (typed variants, timeouts, never crash KWin) is the house style; portal calls keep the 3000 ms timeouts already present.

---

## Out of scope (per Addendum 4 — do NOT build here)

These stay gated/parked; no task in this plan touches them, and the foundation must not accidentally pull them in:

- **Click *animation*** — needs EI click events (same gate as step capture). Cursor *halo* (B) is in scope; animated click ripples are NOT.
- **Step-capture feature UI** — blocked on the interception-semantics (EI) verdict.
- **macOS recorder** — hardware-gated; Linux + Windows only.
- **During-capture toolbar** — we don't own the Wayland portal picker.

If any of these become tempting while wiring B/C/D, stop and note it in ROADMAP rather than expanding scope.

## File Structure

```
wondershot/
  record.py          # A1: in-process rewrite — _GstPipeline wrapper, build_pipeline_description,
                     #     clock pure fns, bus-driven lifecycle. B2: cursor_mode=4 + cairooverlay.
                     #     C1: pause()/resume() + PTS offset. D1: videocrop insertion + crop_props.
  scrollsource.py    # UNTOUCHED (already in-process; subclasses ScreenRecorder._launch_gst/stop)
  winrecord.py       # UNTOUCHED
  settings.py        # B1: record_cursor_halo property. D1: (no new persisted region; region is per-session)
  settings_dialog.py # B1: "Show cursor halo" checkbox (General/Recording rows, after noise_check)
  app.py             # A2: fake_recording analog only in tests; C2: tray Pause/Resume action;
                     #     D2: "Record region…" tray entry → region pick → start with crop
  gallery.py         # C2: toolbar Pause/Resume button; D2: "Record region" toolbar entry
tests/
  _fakegst.py           # A1: NEW — shared FakePipeline + WedgedPipeline (no Gst)
  test_record.py        # A1: REWRITTEN to FakePipeline + pure-fn assertions (stays PURE, no Gst)
  test_record_sync.py   # A2: fake_recording switched to FakePipeline (stays PURE)
  test_record_pure.py   # A1/B2/C1/D1: NEW — pure-fn unit tests (description, clock, pts, crop, halo)
  test_record_live.py   # A3/B2/C3: NEW — importorskip("gi") live smoke (videotestsrc, NO portal)
  test_settings_recording.py        # B1: record_cursor_halo default/roundtrip (PURE)
  test_record_pause_ui.py           # C2: tray+toolbar pause/resume wiring (PURE, offscreen Qt)
  test_record_region.py             # D2: region-pick → crop wiring (PURE, offscreen Qt)
ROADMAP.md            # B2/C3/D2: landmine + findings updates
docs/superpowers/plans/2026-06-07-desktop-checklist.md  # append live checks (non-blocking)
```

### The `_GstPipeline` seam (read before any task)

`ScreenRecorder` never imports Gst. It owns `self._pipeline`, which is either a real `_GstPipeline` (built by `_make_pipeline`, the only place Gst is imported) or a test `FakePipeline`. The lifecycle calls ONLY this surface:

```python
class _PipelineProto:                  # documentation only — duck-typed
    def poll_status(self) -> str: ...  # "running" | "eos" | "error"
    def error_text(self) -> str: ...   # last bus ERROR message text
    def send_eos(self) -> None: ...    # graceful finalize (in-process analog of SIGINT-as-EOS)
    def force_stop(self) -> None: ...  # set NULL (analog of second-SIGINT / SIGKILL); idempotent
    def pause(self) -> None: ...       # C1
    def resume(self) -> None: ...      # C1
```

`FakePipeline` (defined in a shared `tests/_fakegst.py`, imported by `test_record.py`, `test_record_sync.py`, `test_record_pause_ui.py`, `test_record_region.py`) lets behavioral tests run with no Gst:

```python
class FakePipeline:
    def __init__(self, status="running"):
        self._status = status          # set "error" to simulate death; "running" then flip on stop
        self.eos_sent = False
        self.stopped = False
        self.paused = False
    def poll_status(self): return self._status
    def error_text(self): return "from element mux: wedged"
    def send_eos(self):
        self.eos_sent = True
        if self._status == "running":  # a cooperative pipeline finalizes on EOS
            self._status = "eos"
    def force_stop(self):
        self.stopped = True
        self._status = "error"         # giving up == terminal, non-clean
    def pause(self): self.paused = True
    def resume(self): self.paused = False
```

A *wedged* pipeline is `FakePipeline()` with `send_eos` overridden to NOT flip status (stays "running" until `force_stop`), exercising the escalation ladder.

---

## [x] TASK A1 — In-process rewrite (FOUNDATION, behavior-preserving)

This is the load-bearing task. TDD: rewrite `tests/test_record.py` to the new mechanism (failing), then rewrite `record.py`. End state: full suite green, zero argv assertions, no `subprocess.Popen` in `record.py` (the only remaining `subprocess` use is the `gst-inspect-1.0` capability probe in `_have_gst_element`, which stays — it is not part of the recording lifecycle).

### A1.1 — Pure helpers first (`record.py`, top-level, no Gst import)

Replace `_gst_args(self, fd, node, tmp)` with a pure module function. Copy the encode/mux/mic chain VERBATIM (only joining tokens with spaces instead of building a list):

```python
def build_pipeline_description(fd, node, tmp, *, mic_enabled, mic_device="",
                               noise_suppression=True, have_webrtcdsp=False,
                               crop=None, halo=False):
    """Build the Gst.parse_launch string. PURE — no Gst, no portal, no I/O.

    crop: dict(left,right,top,bottom) or None. halo: bool (cursor overlay).
    The videorate + fixed-framerate caps are the no-PTS landmine fix — VERBATIM.
    """
    crop_seg = ""
    if crop:
        crop_seg = ("videocrop top={top} left={left} "
                    "right={right} bottom={bottom} ! ").format(**crop)
    # cairooverlay needs an alpha-capable format; wrap it in videoconvert.
    halo_seg = ("videoconvert ! cairooverlay name=halo ! " if halo else "")
    video = (
        f"pipewiresrc fd={fd} path={node} do-timestamp=true ! "
        "queue ! videoconvert ! "
        f"{crop_seg}"
        # pipewiresrc emits PTS-less buffers (mp4mux-fatal); videorate drops
        # them and turns the damage-driven stream into clean CFR. VERBATIM.
        "videorate ! video/x-raw,format=I420,framerate=30/1 ! "
        # 'pause' identity carries the PTS-offset probe (C1) and MUST sit on
        # RAW frames BEFORE x264enc: dropping/retiming encoded H264 NALs would
        # corrupt inter-frame dependencies. Harmless transparent tap until C1
        # wires the probe. (Matches C1's "in front of the encoder".)
        "identity name=pause ! "
        f"{halo_seg}"
        "x264enc speed-preset=veryfast tune=zerolatency "
        "bitrate=8000 key-int-max=120 ! "
        "h264parse ! queue ! mux. "
    )
    audio = ""
    if mic_enabled:
        device = mic_pulse_device(mic_device)
        dev = f"device={device} " if device else ""
        dsp = ""
        if noise_suppression and have_webrtcdsp:
            dsp = ("audio/x-raw,rate=48000,channels=1 ! webrtcdsp "
                   "echo-cancel=false noise-suppression=true "
                   "noise-suppression-level=very-high gain-control=false "
                   "high-pass-filter=true ! ")
        audio = (
            f"pulsesrc {dev}do-timestamp=true ! "
            "queue ! audioconvert ! audioresample ! "
            f"{dsp}audioconvert ! avenc_aac bitrate=160000 ! "
            "aacparse ! queue ! mux. "
        )
    return f"{video}{audio}mp4mux name=mux ! filesink location={tmp}"
```

Add clock/PTS pure helpers (pause-aware):

```python
def elapsed_seconds(started_at, now, paused_total=0.0, paused_at=None):
    """Wall seconds recorded, excluding paused spans. PURE."""
    if started_at is None:
        return 0.0
    live = now - started_at - paused_total
    if paused_at is not None:
        live -= (now - paused_at)
    return max(0.0, live)

def format_elapsed(seconds):
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"
```

`mic_pulse_device`, `sweep_stale_tmp`, `_salvage_partial` stay as-is (already pure).

### A1.2 — `_GstPipeline` wrapper (`record.py`, the ONLY Gst-importing class)

```python
def _gst():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    if not Gst.is_initialized():
        Gst.init(None)
    return Gst

class _GstPipeline:
    """Owns a real Gst pipeline + bus; exposes the fakeable lifecycle surface."""
    def __init__(self, desc, log_path):
        Gst = _gst()
        self._Gst = Gst
        self._log_path = log_path
        self._error = ""
        self._p = Gst.parse_launch(desc)          # may raise GLib.Error
        self._bus = self._p.get_bus()
        self._p.set_state(Gst.State.PLAYING)

    def poll_status(self):
        Gst = self._Gst
        flt = Gst.MessageType.ERROR | Gst.MessageType.EOS
        msg = self._bus.pop_filtered(flt)
        while msg is not None:
            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                self._error = err.message
                self._append_log(f"ERROR: {err.message} | {dbg}")
                return "error"
            if msg.type == Gst.MessageType.EOS:
                return "eos"          # EOS on the bus == filesink finalized
            msg = self._bus.pop_filtered(flt)
        return "running"

    def error_text(self):
        return self._error or "unknown"

    def send_eos(self):
        self._p.send_event(self._Gst.Event.new_eos())

    def force_stop(self):
        try:
            self._p.set_state(self._Gst.State.NULL)
        except Exception:
            pass

    def _append_log(self, line):
        try:
            with open(self._log_path, "a", errors="replace") as f:
                f.write(line + "\n")
        except OSError:
            pass
    # pause()/resume() added in C1.
```

### A1.3 — Rewrite lifecycle (`record.py`)

- `__init__`: drop `self._proc`; add `self._pipeline = None`. Keep `_stopping`, `_watchdog`, `_started_at`, `_tmp/_out`, `_fd`, `log_path`. Add (used by C1) `self._paused_at = None`, `self._paused_total = 0.0`, `self.paused = False`.
- `available()`:
  ```python
  def available(self):
      if not _HAVE_GIO:
          return False
      try:
          _gst(); return True
      except (ImportError, ValueError):
          return False
  ```
  (Drops the `shutil.which("gst-launch-1.0")` check — no subprocess anymore.) Update the `start()` failure string to `"recording needs python3-gobject and GStreamer (Gst) bindings"`.
- `_make_pipeline(desc)` seam (overridable by tests, the only Gst entry):
  ```python
  def _make_pipeline(self, desc):
      return _GstPipeline(desc, self.log_path)
  ```
- `_launch_gst(fd, node)`: build out/tmp/tmp_dir + `sweep_stale_tmp` exactly as today; build `desc = build_pipeline_description(fd, node, tmp, mic_enabled=self.settings.mic_enabled, mic_device=self.settings.mic_device, noise_suppression=self.settings.noise_suppression, have_webrtcdsp=_have_gst_element("webrtcdsp"), crop=self._crop, halo=self._halo)`; write the desc as the log header (`open(log,"w")`); `try: self._pipeline = self._make_pipeline(desc) except Exception as e: self._fail(f"could not start gstreamer: {e}"); return`; then `_start_watchdog(); self._busy=False; self.recording=True; self._started_at=time.monotonic(); self.started.emit()`. REMOVE `os.set_inheritable`/`pass_fds` (in-process pipewiresrc uses the fd directly). Initialize `self._crop = None` and `self._halo = False` in `__init__` (set by D2/B1 before `start()`).
- `stop()`:
  ```python
  def stop(self):
      if self._stopping: return
      if self._pipeline is None: return
      self._stopping = True
      self.stopping.emit()
      self._pipeline.send_eos()          # in-process analog of -e + SIGINT
      self._poll_exit(elapsed_ms=0)
  ```
- `_poll_exit(elapsed_ms=0, escalated=False)`:
  ```python
  def _poll_exit(self, elapsed_ms=0, escalated=False):
      if self._pipeline is None: return
      status = self._pipeline.poll_status()
      if status == "running":
          if elapsed_ms >= self.KILL_MS:
              self._pipeline.force_stop()           # hard give-up (SIGKILL analog)
          elif elapsed_ms >= self.GRACE_MS and not escalated:
              self._pipeline.force_stop()           # abandon wedged EOS (2nd-SIGINT analog)
              escalated = True
          QTimer.singleShot(200, lambda: self._poll_exit(elapsed_ms + 200, escalated))
          return
      self.recording = False
      ok = (status == "eos" and self._tmp and os.path.exists(self._tmp)
            and os.path.getsize(self._tmp) > 0)
      tmp, out = self._tmp, self._out
      tail = self._pipeline.error_text()
      self._cleanup()
      if ok:
          shutil.move(tmp, out); self.finished.emit(out); return
      partial = self._salvage_partial(tmp, out)
      self.failed.emit(f"recording did not finalize: {tail[:160]} "
                       f"(log: {getattr(self,'log_path','?')}){partial}")
  ```
- `_check_alive()` (watchdog): keep the `if self._stopping: return` early-out; tick is now pause-aware:
  ```python
  def _check_alive(self):
      if self._stopping: return
      if self._pipeline is not None and self._pipeline.poll_status() == "error":
          self.recording = False
          tmp, out = self._tmp, self._out
          tail = self._pipeline.error_text()
          self._cleanup()
          partial = self._salvage_partial(tmp, out)
          self.failed.emit(f"recorder died: {tail[:160]} "
                           f"(full log: {self.log_path}){partial}")
          return
      if not self.paused:
          self.tick.emit(self.elapsed_str())
  ```
- `elapsed_str()`: `return format_elapsed(elapsed_seconds(self._started_at, time.monotonic(), self._paused_total, self._paused_at)) if self.recording else ""`.
- `_cleanup()`: same as today, plus null+drop the pipeline:
  ```python
  if self._pipeline is not None:
      self._pipeline.force_stop()
      self._pipeline = None
  ```
  and reset `self.paused=False; self._paused_at=None; self._paused_total=0.0`. Keep `_stopping=False`, watchdog stop, fd close, `_close_session()`.
- Keep `_log_tail` (the live wrapper appends ERROR lines to `log_path`; failure messages prefer `error_text()`, the escalation test asserts "ERROR" via the tail — see A1.4).

### A1.4 — Rewrite `tests/test_record.py` (PURE, FakePipeline)

Delete `dead_proc`, the `subprocess`/`signal` imports, and the `sleep` procs. Define `FakePipeline` + `WedgedPipeline` in `tests/_fakegst.py` and import them here. **Remove the module-level `pytestmark = pytest.mark.skipif(sys.platform == "win32", ...)`** — its justification ("tests drive POSIX subprocesses (true/sleep, SIGINT-as-EOS)") no longer holds; the rewritten tests are PURE (construct `ScreenRecorder`, assign a `FakePipeline`, assert `build_pipeline_description`/clock), so they must run on every platform with no skips. Each test sets `rec._pipeline = FakePipeline(...)` (mirroring the old `rec._proc = ...`). Rewrites:

- `test_stop_with_dead_pipeline_emits_signal`: `rec._pipeline = FakePipeline(status="error")`; `rec.stop()`; assert `finished`/`failed` emitted, `rec.recording is False`, `rec._pipeline is None`.
- `test_watchdog_detects_late_pipeline_death`: `FakePipeline("error")`; `_start_watchdog()`; assert `failed`, state reset.
- `test_video_branch_sanitizes_timestamps` → assert against `build_pipeline_description(...)`: `"videorate" in desc and "framerate=" in desc`.
- `test_elapsed_and_tick_while_recording`: `FakePipeline("running")`, `_started_at = monotonic()-65`; assert `elapsed_str()=="1:05"`; `_start_watchdog()`; assert a tick arrives starting `"1:0"`.
- `test_log_dir_*`, `test_recorder_restore_token_*`, `test_recorder_save_token_*`, `test_sweep_stale_tmp_*`: unchanged.
- `test_stop_emits_stopping_exactly_once`: `FakePipeline("running")`; `rec.stop(); rec.stop()`; assert `stopping` emitted once and a terminal signal arrives.
- `test_stop_escalates_when_eos_wait_wedges`: `WedgedPipeline` (send_eos no-ops, stays "running" until `force_stop`); set `GRACE_MS=400, KILL_MS=900`; write a fake log with an `ERROR:` line and set `rec.log_path`; `rec.stop()`; assert it finalizes (`failed`), state reset, and the message surfaces the error (`error_text()` "wedged" OR `_log_tail` "ERROR").
- `test_sigkill_keeps_partial_recording`: `WedgedPipeline`, partial bytes in `.rendering`; after escalation assert the partial was moved to `out` and `tmp` gone, `"partial" in failed`.
- `test_watchdog_death_keeps_partial_recording`: `FakePipeline("error")`, partial present; `_start_watchdog()`; assert partial salvaged.

**These 12 tests stay PURE — no `importorskip`.** Constructing `ScreenRecorder` imports no Gst; `_make_pipeline` is never called (tests assign `_pipeline` directly).

### A1.5 — Verify

```bash
cd /home/jack/GitHub/grabbit-wt/recorder-inproc
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record.py -q
```
Expected: `12 passed` (no skips). Then full suite:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
```
Expected: all pass; `test_record_sync.py` may now FAIL (it still fakes a subprocess) — that's Task A2. If green already, even better.

---

## [x] TASK A2 — Port the cross-control sync tests (FOUNDATION)

`tests/test_record_sync.py` `fake_recording()` sets `rec._proc = subprocess.Popen(["sleep",30])`. The recorder no longer has `_proc`. `app.py`/`gallery.py` need NO changes (signals are identical). Update only the test helper:

```python
def fake_recording(a, tmp_path):
    from tests._fakegst import FakePipeline   # shared helper (see below)
    rec = a.recorder
    rec._pipeline = FakePipeline("running")
    rec.recording = True
    d = tmp_path / ".rendering"; d.mkdir(exist_ok=True)
    rec._tmp = str(d / "r.mp4"); rec._out = str(tmp_path / "r.mp4")
    (d / "r.mp4").write_bytes(b"x")               # partial bytes to salvage
    a._on_recording_started()                     # what recorder.started does
    return rec._pipeline                          # callers no longer kill a proc
```
Move `FakePipeline` (and `WedgedPipeline`) to a shared `tests/_fakegst.py` so both `test_record.py` and `test_record_sync.py` import it (avoid duplicate divergence). The two stop-sync tests then drive `gallery._toggle_record()` / `a.toggle_recording()`; the cooperative `FakePipeline` finalizes on `send_eos` → both controls reset. The helper now returns the fake pipeline (not a `Popen`); DROP the `subprocess` import and the `proc.poll()/proc.kill()` teardown in `finally:` (no live process to reap).

Verify:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_sync.py tests/test_record.py -q
```
Expected: all pass, no skips. Then full suite green.

---

## [x] TASK A3 — Live-pipeline smoke (FOUNDATION; Linux dev box, NO portal)

New `tests/test_record_live.py`. Proves the REAL in-process lifecycle without a portal session by building a pipeline from `videotestsrc` (the only difference from production is the source; the encode→mux→filesink chain + bus EOS finalize are identical).

```python
import os, pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
gi = pytest.importorskip("gi")        # SKIPS on CI without GObject Introspection
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])

def _gst_or_skip():
    try:
        from wondershot.record import _gst
        return _gst()
    except Exception:
        pytest.skip("GStreamer Gst bindings unavailable")

def test_live_eos_finalizes_playable_mp4(qapp, tmp_path):
    """Real pipeline (videotestsrc, no portal): EOS must finalize a non-empty mp4."""
    _gst_or_skip()
    from wondershot.record import ScreenRecorder, _GstPipeline
    from tests.test_record import FakeSettings   # reuse
    rec = ScreenRecorder(FakeSettings(str(tmp_path)))
    out = str(tmp_path / "r.mp4"); tmp = str(tmp_path / ".rendering" / "r.mp4")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    rec.log_path = str(tmp_path / "rec.log")
    desc = ("videotestsrc num-buffers=30 ! videoconvert ! videorate ! "
            "video/x-raw,format=I420,framerate=30/1 ! "
            "x264enc speed-preset=veryfast tune=zerolatency ! h264parse ! "
            f"queue ! mp4mux name=mux ! filesink location={tmp}")
    rec._tmp, rec._out = tmp, out
    rec._pipeline = _GstPipeline(desc, rec.log_path)
    rec.recording = True; rec._start_watchdog()
    done = []
    rec.finished.connect(done.append); rec.failed.connect(done.append)
    rec.stop()
    # pump the Qt/GLib loop until the bus posts EOS and _poll_exit finalizes
    import time
    deadline = time.monotonic() + 15
    while not done and time.monotonic() < deadline:
        qapp.processEvents(); time.sleep(0.02)
    assert done, "live pipeline never finalized"
    assert os.path.exists(out) and os.path.getsize(out) > 0
```

This is the ONLY foundation test that needs Gst → `importorskip`. Verify on the dev box:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_live.py -q
```
Expected on dev box: `1 passed`. On a box without gi: `1 skipped`.

**FOUNDATION COMPLETE.** Suite green; `record.py` no longer spawns the pipeline as a subprocess (`gst-inspect-1.0` probe aside); observable behavior identical. Features layer on from here.

---

## [x] TASK B1 — Cursor-halo setting (feature)

- `settings.py`: add property after `capture_cursor` (mirror the boolean idiom):
  ```python
  @property
  def record_cursor_halo(self):
      return self._s.value("record_cursor_halo", "false") in (True, "true")
  @record_cursor_halo.setter
  def record_cursor_halo(self, v):
      self._s.setValue("record_cursor_halo", "true" if v else "false")
  ```
- `settings_dialog.py`: after `noise_check` row add `self.halo_check = QCheckBox("Show cursor halo in screen recordings")`, `setChecked(settings.record_cursor_halo)`, `form.addRow("", self.halo_check)`; in `apply()` add `self.settings.record_cursor_halo = self.halo_check.isChecked()`.
- `tests/test_settings_recording.py` (PURE; this file ALREADY EXISTS with `record_countdown` tests — APPEND, do not overwrite): default `False`; round-trips `True`. Use the `make_settings`/QSettings pattern already in that file. Also confirm `test_settings_dialog_recording.py` (existing) still passes after the dialog row is added.

Verify:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_recording.py -q
```
Expected: `2 passed`.

---

## [x] TASK B2 — Cursor halo compositing (feature; metadata cursor, default off)

- **Pure halo math** in `record.py` + `tests/test_record_pure.py`:
  ```python
  def halo_geometry(cx, cy, frame_w, frame_h, radius=24):
      """Clamp the halo centre into frame; return (cx, cy, radius). PURE."""
      cx = max(0, min(int(cx), frame_w)); cy = max(0, min(int(cy), frame_h))
      return (cx, cy, radius)
  ```
  Tests: centre passes through; out-of-bounds clamps to edges; negative clamps to 0.
- **Portal:** in `_created`, when `self._halo` (set from `settings.record_cursor_halo` in `start()` before the dance), request `"cursor_mode": GLib.Variant("u", 4)` (METADATA) instead of `2`. Keep `2` otherwise. PURE-ish test: spy that with halo on, the SelectSources options carry `cursor_mode==4` (call `_created` with a fake `_call`/`_session`, capture the variant; unpack and assert `4`).
- **Pipeline:** `build_pipeline_description(..., halo=True)` already inserts `videoconvert ! cairooverlay name=halo`. After PLAYING, fetch `self._pipeline._p.get_by_name("halo")`, `connect("draw", self._draw_halo)`. `_draw_halo(overlay, cr, ts, dur)` reads the latest cursor (cx,cy) (shared attr updated by a pad probe), computes `halo_geometry`, and paints a translucent circle via cairo (`cr.set_source_rgba(1,1,0,0.35); cr.arc(...); cr.fill()`).
- **The hard part — reading `spa_meta_cursor`:** install a buffer pad probe on the `cairooverlay` sink (or pipewiresrc src). Attempt to read the cursor position from the buffer's PipeWire metadata via gi. **If the cursor coords are unreadable through gi bindings** (the known risk — SPA meta is not exposed as a typed GstMeta in PyGObject): document PRECISELY in `ROADMAP.md` under a new "Cursor halo (in-process)" heading — what was tried (cursor_mode=4 negotiated? meta present on buffer? which gi call returned what), and PARK the compositing (keep the setting + `halo_geometry` + the disabled wiring). The foundation makes this *reachable*; document from that vantage per spec.
- **Live smoke (if coords ARE readable):** extend `test_record_live.py` with an `importorskip` test that builds `videotestsrc ! ... ! cairooverlay name=halo ! ...`, connects a draw callback, runs 10 buffers, and asserts the callback fired (proves the overlay element path works in-process; cursor-source correctness is a desktop checklist item).

Verify:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_pure.py -q
```
Expected: halo + cursor_mode tests pass. ROADMAP updated either way.

---

## TASK C1 — Pause/resume in the recorder (feature; PTS continuity is the real risk)

- **Pure PTS bookkeeping** in `record.py` + `test_record_pure.py`:
  ```python
  def pts_offset_ns(paused_total_s):
      """Nanoseconds to subtract from buffer PTS/DTS so the resumed
      segment is gap-free for mp4mux. PURE."""
      return int(round(paused_total_s * 1_000_000_000))
  ```
  Tests: 0→0; 2.5 s → 2_500_000_000.
- **`_GstPipeline.pause()/resume()`:** gate the stream at the `identity name=pause` element placed in front of the encoder (after the CFR caps, so videorate keeps producing CFR; we drop downstream of it so timestamps stay sane). Implementation: a buffer pad probe on `pause`'s src pad that, while paused, returns `Gst.PadProbeReturn.DROP`; on resume it stops dropping and rewrites each buffer's `pts`/`dts` by subtracting the accumulated paused duration (`pts_offset_ns`), making the encoded stream continuous. Record the running-time at pause; accumulate on resume. (Valve `drop=true` is the simpler alternative but leaves a segment/PTS jump mp4mux dislikes — the probe-offset approach is why `identity name=pause` is in the description.)
- **Recorder API:** `pause()` → if `recording and not paused and not _stopping`: `self._pipeline.pause(); self.paused=True; self._paused_at=time.monotonic()`. `resume()` → `self._paused_total += time.monotonic()-self._paused_at; self._paused_at=None; self.paused=False; self._pipeline.resume()`. Add a `paused_changed = Signal(bool)` and emit it. `_check_alive` already skips `tick` while paused (A1.3), so the clock pauses.
- **FakePipeline tests (PURE):** add `pause()/resume()` (already in the fake). Test: `rec.pause()` sets `rec.paused True` and `_pipeline.paused True`, ticks stop; `rec.resume()` clears it and `_paused_total` grew; elapsed excludes the paused span (drive `elapsed_seconds` with known timestamps).

Verify:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_pure.py tests/test_record.py -q
```
Expected: all pass.

---

## TASK C2 — Pause/resume UI (tray + toolbar) (feature)

- `app.py`: add a tray `pause_action` ("Pause recording"). On `_on_recording_started` enable+show it; on stopping/finished/failed reset+hide. `toggle_pause()` → `recorder.resume() if recorder.paused else recorder.pause()`, then relabel ("Pause"/"Resume"). Connect `recorder.paused_changed` to relabel BOTH controls (single source of truth, same discipline as `stopping`).
- `gallery.py`: add a toolbar Pause/Resume button (`media-playback-pause`/`media-playback-start`) next to record; enable only while `recording`; click → app coordinator (add a `pause_requested` signal OR call `self.recorder` directly mirroring `_toggle_record`). Relabel via `recorder.paused_changed`.
- `tests/test_record_pause_ui.py` (PURE, offscreen, real `GrabbitApp` via the `make_app` pattern from `test_record_sync.py`, FakePipeline): start fake recording; toolbar Pause → `recorder.paused True`, BOTH controls read "Resume"; tray Resume → both read "Pause", recorder running; idle → both pause controls disabled.

Verify:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_pause_ui.py -q
```
Expected: pass.

---

## TASK C3 — Pause/resume live continuity smoke (THE risk; Linux dev box)

`test_record_live.py` (importorskip): build a `videotestsrc` pipeline with `identity name=pause`, run; `pause()`; pump ~0.5 s; `resume()`; run; `stop()`; assert the mp4 finalizes (no mux error → `finished`, not `failed`), is non-empty, and — if `ffprobe` is on PATH — that duration is plausibly continuous (no negative/backwards-PTS warning). If mp4mux breaks on the resumed segment despite the offset probe, document findings in `ROADMAP.md` and PARK pause/resume (keep C1/C2 behind `recorder.pause_supported`), per spec's timeboxed mandate.

Verify (dev box):
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_live.py -q
```
Expected: passes on dev box (or documented park).

---

## TASK D1 — Region crop in pipeline (feature; pure math + description)

- **Pure crop math** in `record.py` + `test_record_pure.py`:
  ```python
  def crop_props(rect, stream_w, stream_h):
      """Map a chosen rect (x,y,w,h) in stream pixels to videocrop
      top/left/right/bottom borders, clamped. PURE."""
      x, y, w, h = rect
      left = max(0, x); top = max(0, y)
      right = max(0, stream_w - (x + w)); bottom = max(0, stream_h - (y + h))
      return {"left": left, "top": top, "right": right, "bottom": bottom}
  ```
  Tests: centred rect → symmetric borders; full-frame rect → all zeros; over-edge rect clamps to 0.
- `build_pipeline_description(..., crop={...})` already inserts `videocrop top=.. left=.. right=.. bottom=..` after `videoconvert` (done in A1.1). Pure test: with `crop` set, the description contains `videocrop` with the expected borders; without it, no `videocrop`.
- Recorder: `self._crop` set before `start()` (D2). Portal still streams the whole monitor; we crop in-pipeline.

Verify:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_pure.py -q
```
Expected: pass.

---

## TASK D2 — Region pick UI (feature; reuse RegionOverlay)

- New flow: "Record region…" entry in the tray menu (and a gallery toolbar entry). On trigger: grab a fullscreen still (reuse `wincapture.grab_fullscreen` — it lives in `wincapture.py`, NOT `capture.py`, and is portable Qt via `QGuiApplication`), show `wincapture.RegionOverlay(image)` (portable Qt — `selected(QRect)` in image pixels, `cancelled()`), then on `selected` set `recorder._crop = crop_props((rect.x,rect.y,rect.w,rect.h), image.width(), image.height())` and call the normal start (`_begin_recording`). On cancel, do nothing.
- Multi-monitor: the overlay covers `virtualGeometry`; the grabbed still is the virtual desktop, so crop coords are in stream/virtual pixels — matches what pipewiresrc casts when the monitor selection equals the picked screen. (If the portal stream is a single monitor while the rect spans the virtual desktop, document the offset handling in ROADMAP; for v1 constrain region recording to the primary screen and note it.)
- `tests/test_record_region.py` (PURE, offscreen): inject a fake overlay that emits `selected(QRect(...))`; assert `recorder._crop` equals `crop_props(...)` and `recorder.start` was invoked; cancel path leaves `_crop None` and does not start.

Verify:
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_record_region.py -q
```
Expected: pass.

---

## TASK E — Docs + final verification

- `ROADMAP.md`: add an "In-process recorder (2026-06-07)" note under Platform landmines summarizing: subprocess→`Gst.parse_launch`, bus-driven lifecycle, the `videorate` no-PTS fix preserved verbatim, EOS-via-bus finalize, and `force_stop()` escalation replacing the double-SIGINT/SIGKILL ladder. Record the cursor-halo (B2) and pause/resume (C3) outcomes (shipped vs parked-with-findings).
- Append to `docs/superpowers/plans/2026-06-07-desktop-checklist.md` (non-blocking, live-desktop): real recording finalizes a playable mp4; cursor halo visible (if shipped); pause/resume yields a continuous playable mp4; region crop matches the picked rect; tray+toolbar pause/stop both work and both reset.
- Final gate:
  ```bash
  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
  ```
  Expected: all pass; live tests pass on the dev box (skip honestly where gi is absent).

---

## Test disposition (importorskip vs pure)

**PURE (no Gst import; run on CI without GObject Introspection):**
- All of `tests/test_record.py` (12, rewritten to `FakePipeline` + `build_pipeline_description`/clock assertions — no argv, no subprocess).
- `tests/test_record_sync.py` (`fake_recording` → `FakePipeline`).
- `tests/test_record_pure.py` (NEW: `build_pipeline_description`, `elapsed_seconds`/`format_elapsed`, `pts_offset_ns`, `crop_props`, `halo_geometry`, `cursor_mode==4` option spy).
- `tests/test_settings_recording.py` (EXTEND existing file — it already holds `record_countdown` tests; add `record_cursor_halo`).
- `tests/test_record_pause_ui.py` (NEW: tray+toolbar pause wiring, offscreen Qt, FakePipeline).
- `tests/test_record_region.py` (NEW: region-pick → crop wiring, offscreen Qt, fake overlay).

**importorskip("gi") + real Gst (Linux dev box only; videotestsrc, NEVER a portal session):**
- `tests/test_record_live.py` (NEW): EOS-finalizes-playable-mp4 (A3); cairooverlay draw-callback fires (B2, only if cursor coords readable); pause/resume continuity (C3, the real risk).

Rationale: `ScreenRecorder` imports no Gst (lazy `_gst()`/`_make_pipeline`), so every behavioral assertion runs against `FakePipeline` headless; only proof that the REAL bus/parse_launch/mux path works lives behind `importorskip`, and it uses `videotestsrc` so it never needs the portal at test time.
