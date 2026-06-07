# WS-A: Video Quick Wins — Frame Grab, Trim, Cursor Halo, ffmpeg Helper

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add "Save frame" and "Trim" to the video player (both routed through a new single ffmpeg invocation helper), then timeboxed-attempt a cursor-halo recording option — documenting findings in ROADMAP.md if portal metadata cursor mode can't deliver coordinates to our gst-launch pipeline.

**Architecture:** All video features live in `wondershot/video.py` (the `VideoPane` player with the existing range-blur timeline) and follow its established pattern: pure, headless-testable command-builder functions + QProcess-driven renders into `<library>/.rendering/` that `shutil.move` into the library on success and emit `file_ready(path)`. A new `wondershot/ffmpegutil.py` becomes the single chokepoint for finding/invoking ffmpeg (WS-E will later swap PATH discovery for a bundled binary there). The cursor halo task is last and gated: items 1–2 must not depend on it.

**Tech Stack:** Python ≥3.10, PySide6 (only required dep), ffmpeg via subprocess/QProcess, pytest (headless, `QT_QPA_PLATFORM=offscreen`), GStreamer/portal only in the halo task.

## Verified codebase facts (read before starting)

- `wondershot/video.py` (852 lines): `VideoPane` widget. Existing patterns to copy:
  - Pure builder: `build_blur_filter(redactions, blur, video_w, video_h)` at line ~46, tested headless in `tests/test_video_filter.py`.
  - `Redaction` dataclass (line ~38): `rect: QRect, start: float, end: float` (seconds). The trim span reuses this with an empty `QRect()`.
  - Render flow: `_apply_blurs` (line ~755) → `unique_path(...)` from `wondershot/capture.py` → `_render_temp(out)` returns `<library>/.rendering/<basename>` → `QProcess` runs `ffmpeg` → `_blur_done(code, tmp, out)` checks `code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0`, then `shutil.move(tmp, out)` + `self.file_ready.emit(out)`; on failure shows last stderr line via `self._notify(...)` and unlinks tmp.
  - `pick_encoder()` (line ~75) probes `ffmpeg -encoders` with module-level `_encoder_cache`; encoder opts in `_apply_blurs`: `["-crf", "20", "-preset", "veryfast"]` for libx264 else `["-q:v", "4"]`.
  - `RangeBar` (line ~247): the timeline strip. It reads `self.pane.redactions`, `self.pane.active_idx`, calls `self.pane.set_active(i)`, `self.pane.active_redaction()`, `self.pane.sync_active_row()`, `self.pane.refresh_overlays()`. Trim mode piggybacks on it via a `pane.spans()` indirection (Task 6).
  - Buttons currently gate on `shutil.which("ffmpeg") is not None` (lines ~434, ~444).
- `wondershot/gallery.py`: `VideoPane.file_ready` is connected to `GalleryWindow._file_ready` (line ~364, ~623) which rescans and `select_path(out)`; selecting a `.png` loads it into the embedded editor automatically (`_selection_changed`, line ~589). So "opens in editor" for the frame grab = just emit `file_ready`. ffmpeg fallback call site to migrate: `_ThumbJob._video_frame` (line ~201). Esc handling for blur mode: `GalleryWindow.keyPressEvent` (line ~1000).
- `wondershot/record.py`: portal dance; cursor mode hardcoded `GLib.Variant("u", 2)` (embedded) in `_created` (line ~182). `gi`/`GLib` import is guarded by `_HAVE_GIO`.
- `wondershot/settings.py`: QSettings wrapper, property pattern — copy the `noise_suppression` bool property shape exactly.
- `wondershot/settings_dialog.py`: recording options live on the **General** tab (mic combo/checkboxes, lines ~147–176); `apply()` at line ~591 writes everything back.
- Tests: run headless via `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at the top of each test file (see `tests/test_video_filter.py`). `tests/test_record.py` has a session-scoped `qapp` fixture and a `FakeSettings` class. Run: `python -m pytest tests/ -q` from the repo root.
- Gotcha: `tests/test_video_filter.py` imports `from PySide6.QtCore import QRect` AFTER setting `QT_QPA_PLATFORM` — keep that ordering in any new test file.
- Gotcha: H.264 can't live in a WebM container (Spectacle records `.webm`); the blur pass renders to `.mp4` unless the source is already mp4-family. Trim stream-copy must keep the source container; trim re-encode always outputs `.mp4`. (Deliberate deviation from the spec's literal "Output `<stem>-trimmed.mp4`": stream-copying a WebM's codec stream into `.mp4` is exactly the container mismatch this gotcha exists for — keep this plan's container-preserving naming; do not "correct" it back to the spec text.)

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `wondershot/ffmpegutil.py` | **Create** (Task 1) | Single ffmpeg chokepoint: PATH discovery (`shutil.which`), `FfmpegMissing` error, `ffmpeg_path()`, `have_ffmpeg()`, blocking `run_ffmpeg()` |
| `tests/test_ffmpegutil.py` | **Create** (Task 1) | Helper unit tests (which-mocking, error message, arg prepending) |
| `wondershot/video.py` | **Modify** (Tasks 2,3,4,5,6) | Migrate ffmpeg call sites to ffmpegutil; add `build_frame_grab_args`/`frame_output_name`/`build_trim_args`/`trim_output_name` pure builders; "Save frame" button + render flow; trim mode (button, frame-accurate checkbox, RangeBar spans indirection, render flow) |
| `tests/test_video_filter.py` | **Modify** (Tasks 2,3,5) | New tests for pick_encoder fallback, frame-grab args/naming, trim args/naming |
| `wondershot/gallery.py` | **Modify** (Tasks 2,6) | `_ThumbJob._video_frame` routed through ffmpegutil (~line 201); Esc also exits trim mode (~line 1000) |
| `wondershot/settings.py` | **Modify** (Task 7, branch A only) | `cursor_halo` bool property |
| `wondershot/settings_dialog.py` | **Modify** (Task 7, branch A only) | "Highlight the cursor…" checkbox on General tab + `apply()` line |
| `wondershot/record.py` | **Modify** (Task 7, branch A only) | Extract `_source_options(token)`; cursor_mode 4 when halo enabled; halo compositing per probe findings |
| `tests/test_record.py` | **Modify** (Task 7, branch A only) | `_source_options` cursor_mode test |
| `spikes/cursor_halo_probe.md` | **Create** (Task 7) | Raw probe transcript (commands + output) backing the decision |
| `ROADMAP.md` | **Modify** (Task 7, branch B) | Documented "investigated, parked" findings for cursor halo |

---

## Task 1: Create `wondershot/ffmpegutil.py` (the WS-E seam)

**Files:**
- Create: `wondershot/ffmpegutil.py`
- Test: `tests/test_ffmpegutil.py` (create)

- [x] **Step 1.1 — Write the failing tests.** Create `tests/test_ffmpegutil.py`:

```python
import subprocess

import pytest

from wondershot import ffmpegutil


@pytest.fixture(autouse=True)
def fresh_cache():
    ffmpegutil.reset_cache()
    yield
    ffmpegutil.reset_cache()


def test_ffmpeg_path_found(monkeypatch):
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    assert ffmpegutil.ffmpeg_path() == "/usr/bin/ffmpeg"


def test_ffmpeg_path_missing_raises_clear_error(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ffmpegutil.FfmpegMissing) as exc:
        ffmpegutil.ffmpeg_path()
    msg = str(exc.value)
    assert "ffmpeg" in msg
    assert "PATH" in msg
    assert "Install" in msg


def test_have_ffmpeg_false_then_true(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert ffmpegutil.have_ffmpeg() is False
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert ffmpegutil.have_ffmpeg() is True


def test_path_is_cached_after_first_hit(monkeypatch):
    calls = []

    def which(name):
        calls.append(name)
        return "/usr/bin/ffmpeg"

    monkeypatch.setattr("shutil.which", which)
    ffmpegutil.ffmpeg_path()
    ffmpegutil.ffmpeg_path()
    assert calls == ["ffmpeg"]


def test_run_ffmpeg_prepends_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        seen["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ffmpegutil.run_ffmpeg(["-hide_banner", "-encoders"], timeout=10)
    assert seen["argv"] == ["/usr/bin/ffmpeg", "-hide_banner", "-encoders"]
    assert seen["timeout"] == 10
    assert r.returncode == 0
```

- [x] **Step 1.2 — Run it, expect failure.** `python -m pytest tests/test_ffmpegutil.py -q` → fails with `ModuleNotFoundError: No module named 'wondershot.ffmpegutil'`.

- [x] **Step 1.3 — Implement.** Create `wondershot/ffmpegutil.py`:

```python
"""Single chokepoint for invoking ffmpeg.

Every ffmpeg call site routes through here. Today this is PATH discovery
via shutil.which; WS-E (Windows/macOS packaging) will swap in a bundled
binary at this one seam and every caller gets it for free.
"""

from __future__ import annotations

import shutil
import subprocess


class FfmpegMissing(RuntimeError):
    """ffmpeg is not installed / not on PATH."""

    def __init__(self):
        super().__init__(
            "ffmpeg was not found on PATH. Install it (e.g. "
            "`sudo dnf install ffmpeg`) and restart Wondershot.")


_path_cache: str | None = None


def reset_cache() -> None:
    """Test hook: forget the discovered path."""
    global _path_cache
    _path_cache = None


def ffmpeg_path() -> str:
    """Absolute path to the ffmpeg binary; raises FfmpegMissing if absent.

    Successful discovery is cached for the process lifetime; a miss is
    re-probed each call (the user may install ffmpeg mid-session).
    """
    global _path_cache
    if _path_cache is None:
        found = shutil.which("ffmpeg")
        if not found:
            raise FfmpegMissing()
        _path_cache = found
    return _path_cache


def have_ffmpeg() -> bool:
    try:
        ffmpeg_path()
        return True
    except FfmpegMissing:
        return False


def run_ffmpeg(args: list[str],
               timeout: float = 60) -> subprocess.CompletedProcess:
    """Blocking ffmpeg run (capability probes, thumbnailers). Callers that
    must not block the UI use QProcess with ffmpeg_path() instead."""
    return subprocess.run([ffmpeg_path(), *args], capture_output=True,
                          text=True, timeout=timeout)
```

- [x] **Step 1.4 — Run tests.** `python -m pytest tests/test_ffmpegutil.py -q` → 5 passed. Then full suite: `python -m pytest tests/ -q` → all pass (no regressions possible yet, nothing imports the new module).

- [x] **Step 1.5 — Commit.**
```
git add wondershot/ffmpegutil.py tests/test_ffmpegutil.py
git commit -m "Add ffmpegutil: single ffmpeg discovery/invocation seam for WS-E"
```

---

## Task 2: Migrate existing ffmpeg call sites to ffmpegutil

**Files:**
- Modify: `wondershot/video.py` (lines ~10–14 imports, ~75–91 `pick_encoder`, ~434 `blur_btn`, ~444 `gif_btn`, ~794 `_blur_proc.start`, ~836 `_gif_proc.start`)
- Modify: `wondershot/gallery.py` (lines ~201–231 `_ThumbJob._video_frame`)
- Test: `tests/test_video_filter.py` (extend)

- [x] **Step 2.1 — Write the failing test.** Append to `tests/test_video_filter.py`:

```python
def test_pick_encoder_falls_back_when_ffmpeg_missing(monkeypatch):
    import wondershot.video as video
    from wondershot import ffmpegutil

    monkeypatch.setattr(video, "_encoder_cache", None)

    def boom(args, timeout=60):
        raise ffmpegutil.FfmpegMissing()

    monkeypatch.setattr(ffmpegutil, "run_ffmpeg", boom)
    assert video.pick_encoder() == "mpeg4"
```

- [x] **Step 2.2 — Run it, expect failure.** `python -m pytest tests/test_video_filter.py::test_pick_encoder_falls_back_when_ffmpeg_missing -q` → fails: `pick_encoder` still calls `subprocess.run` directly (returns whatever the real machine has, e.g. `libx264`, or errors because `boom` was never invoked). Either failure mode is fine — the point is it doesn't go through ffmpegutil yet.

- [x] **Step 2.3 — Migrate `video.py`.** Add to the imports block (after `import subprocess`):

```python
from . import ffmpegutil
```

Replace the body of `pick_encoder` (keep `import subprocess` at top of file — `TimeoutExpired` is still caught):

```python
def pick_encoder() -> str:
    """Best available H.264-ish encoder on this system."""
    global _encoder_cache
    if _encoder_cache is None:
        try:
            out = ffmpegutil.run_ffmpeg(["-hide_banner", "-encoders"],
                                        timeout=10).stdout
        except (ffmpegutil.FfmpegMissing, OSError,
                subprocess.TimeoutExpired):
            out = ""
        for enc in ("libx264", "libopenh264", "mpeg4"):
            if enc in out:
                _encoder_cache = enc
                break
        else:
            _encoder_cache = "mpeg4"
    return _encoder_cache
```

In `VideoPane.__init__`, replace both button gates:
- `self.blur_btn.setEnabled(shutil.which("ffmpeg") is not None)` → `self.blur_btn.setEnabled(ffmpegutil.have_ffmpeg())`
- `self.gif_btn.setEnabled(shutil.which("ffmpeg") is not None)` → `self.gif_btn.setEnabled(ffmpegutil.have_ffmpeg())`

In `_apply_blurs`, replace `self._blur_proc.start("ffmpeg", args)` → `self._blur_proc.start(ffmpegutil.ffmpeg_path(), args)`.
In `_convert_gif`, replace `self._gif_proc.start("ffmpeg", [...])` → `self._gif_proc.start(ffmpegutil.ffmpeg_path(), ["-y", "-i", self.path, "-vf", vf, tmp])` (same args list as today, only the program changes).

Gotcha: `ffmpeg_path()` raises if ffmpeg is missing, but both call sites are only reachable from buttons that are disabled when `have_ffmpeg()` is False — no extra try/except needed. Keep `import shutil` in video.py (`shutil.move` is still used).

- [x] **Step 2.4 — Migrate `gallery.py`.** Replace `_ThumbJob._video_frame` (line ~201) with:

```python
    def _video_frame(self) -> QImage:
        """Poster frame via ffmpegthumbnailer/ffmpeg, else a dark slate."""
        import shutil
        import subprocess
        import tempfile

        from . import ffmpegutil

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            out = tf.name
        try:
            if shutil.which("ffmpegthumbnailer"):
                r = subprocess.run(
                    ["ffmpegthumbnailer", "-i", self.path, "-o", out,
                     "-s", "512", "-q", "8"],
                    capture_output=True, timeout=15)
            elif ffmpegutil.have_ffmpeg():
                r = ffmpegutil.run_ffmpeg(
                    ["-y", "-ss", "1", "-i", self.path,
                     "-frames:v", "1", out],
                    timeout=15)
            else:
                r = None
            img = QImage(out) if r is not None and r.returncode == 0 else QImage()
        except (OSError, subprocess.TimeoutExpired, ffmpegutil.FfmpegMissing):
            img = QImage()
        finally:
            if os.path.exists(out):
                os.unlink(out)
        if img.isNull():
            img = QImage(THUMB_SIZE, QImage.Format_ARGB32_Premultiplied)
            img.fill(QColor(40, 40, 46))
        return img
```

- [x] **Step 2.5 — Run tests.** `python -m pytest tests/ -q` → all pass, including the new fallback test.

- [x] **Step 2.6 — Commit.**
```
git add wondershot/video.py wondershot/gallery.py tests/test_video_filter.py
git commit -m "Route all existing ffmpeg call sites through ffmpegutil"
```

---

## Task 3: Frame-grab command builder + output naming (pure functions)

**Files:**
- Modify: `wondershot/video.py` (add two module-level functions after `build_blur_filter`, ~line 70)
- Test: `tests/test_video_filter.py` (extend)

- [x] **Step 3.1 — Write the failing tests.** Append to `tests/test_video_filter.py`:

```python
def test_frame_grab_args():
    from wondershot.video import build_frame_grab_args
    args = build_frame_grab_args(
        "/lib/Recording.mp4", 12.3456, "/lib/.rendering/Recording-frame.png")
    assert args == ["-y", "-ss", "12.346", "-i", "/lib/Recording.mp4",
                    "-frames:v", "1", "/lib/.rendering/Recording-frame.png"]


def test_frame_grab_at_zero():
    from wondershot.video import build_frame_grab_args
    args = build_frame_grab_args("/lib/a.webm", 0.0, "/lib/a-frame.png")
    assert args[1:3] == ["-ss", "0.000"]


def test_frame_output_name():
    from wondershot.video import frame_output_name
    assert frame_output_name("Recording_20260606_1.mp4") == \
        "Recording_20260606_1-frame.png"
    assert frame_output_name("clip.webm") == "clip-frame.png"
```

- [x] **Step 3.2 — Run them, expect failure.** `python -m pytest tests/test_video_filter.py -q` → 3 new tests fail with `ImportError: cannot import name 'build_frame_grab_args'`.

- [x] **Step 3.3 — Implement.** In `wondershot/video.py`, after `build_blur_filter` (before the `_encoder_cache` line):

```python
def build_frame_grab_args(src: str, position_s: float, out: str) -> list[str]:
    """ffmpeg args extracting one frame at position_s seconds.

    -ss before -i = fast input seek; with -frames:v 1 the decoder lands on
    the frame at/just after the seek point. This sidesteps grabbing from
    QVideoSink, whose Wayland subsurface frames aren't reliably readable.
    """
    return ["-y", "-ss", f"{position_s:.3f}", "-i", src,
            "-frames:v", "1", out]


def frame_output_name(src_name: str) -> str:
    """'<video-stem>-frame.png' library name for a grabbed frame."""
    return f"{os.path.splitext(src_name)[0]}-frame.png"
```

- [x] **Step 3.4 — Run tests.** `python -m pytest tests/test_video_filter.py -q` → all pass. Full suite: `python -m pytest tests/ -q` → all pass.

- [x] **Step 3.5 — Commit.**
```
git add wondershot/video.py tests/test_video_filter.py
git commit -m "Frame grab: pure ffmpeg arg builder + output naming"
```

---

## Task 4: "Save frame" button + render flow in VideoPane

**Files:**
- Modify: `wondershot/video.py` (`VideoPane.__init__` ~lines 419–455 for the button, `load` ~line 486, new `_save_frame`/`_frame_done` methods next to `_convert_gif` ~line 821)
- Test: none new — this is GUI-only glue (QProcess + widget wiring around the already-tested builders); explicitly skipping the failing-test step. The done-handler logic is a verbatim copy of the tested-in-production `_gif_done` shape.

- [x] **Step 4.1 — Add the button.** In `VideoPane.__init__`, after the `self.gif_btn` block (~line 444):

```python
        self.frame_btn = QPushButton("Save frame", self)
        self.frame_btn.setIcon(QIcon.fromTheme("camera-photo"))
        self.frame_btn.setToolTip(
            "Save the current frame as a PNG in the library")
        self.frame_btn.clicked.connect(self._save_frame)
        self.frame_btn.setEnabled(ffmpegutil.have_ffmpeg())
```

Add it to the controls row right after `controls.addWidget(self.gif_btn)`:

```python
        controls.addWidget(self.frame_btn)
```

Add the process slot to the `__init__` state block (next to `self._gif_proc`):

```python
        self._frame_proc: QProcess | None = None
```

- [x] **Step 4.2 — Implement the render flow.** Add after `_gif_done` (end of file):

```python
    # -- frame grab ----------------------------------------------------------

    def _save_frame(self) -> None:
        if not self.path or self._frame_proc is not None:
            return
        from .capture import unique_path
        self.player.pause()
        pos = self.player.position() / 1000.0
        out = unique_path(self.settings.library_dir,
                          frame_output_name(os.path.basename(self.path)))
        tmp = self._render_temp(out)
        self._frame_proc = QProcess(self)
        self._frame_proc.finished.connect(
            lambda code, _st: self._frame_done(code, tmp, out))
        self.frame_btn.setEnabled(False)
        self._notify("Saving frame…", 0)
        self._frame_proc.start(ffmpegutil.ffmpeg_path(),
                               build_frame_grab_args(self.path, pos, tmp))

    def _frame_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._frame_proc = self._frame_proc, None
        if proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")
            proc.deleteLater()
        else:
            err = ""
        self.frame_btn.setEnabled(True)
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self._notify(f"Saved {os.path.basename(out)}")
            self.file_ready.emit(out)
        else:
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self._notify(f"Frame grab failed: {tail[:160]}", 8000)
            if os.path.exists(tmp):
                os.unlink(tmp)
```

Why this "opens in the editor" with no further code: `GalleryWindow` connects `video_pane.file_ready` → `_file_ready` → `rescan()` + `select_path(out)`; selecting a `.png` routes to the embedded editor (`gallery.py` `_selection_changed`).

- [x] **Step 4.3 — Run the suite + manual smoke.** `python -m pytest tests/ -q` → all pass (imports must not break). Manual check (needs a desktop session): `python -m wondershot`, select a recording, scrub, click "Save frame" → `<stem>-frame.png` appears in the carousel and loads in the editor.

- [x] **Step 4.4 — Commit.**
```
git add wondershot/video.py
git commit -m "Save frame: extract current video frame to <stem>-frame.png, opens in editor"
```

---

## Task 5: Trim command builder + output naming (pure functions)

**Files:**
- Modify: `wondershot/video.py` (module-level functions, next to the Task 3 builders)
- Test: `tests/test_video_filter.py` (extend)

- [x] **Step 5.1 — Write the failing tests.** Append to `tests/test_video_filter.py`:

```python
def test_trim_output_name_keeps_container_on_copy():
    from wondershot.video import trim_output_name
    assert trim_output_name("Rec.webm", reencode=False) == "Rec-trimmed.webm"
    assert trim_output_name("Rec.mp4", reencode=False) == "Rec-trimmed.mp4"


def test_trim_output_name_reencode_is_mp4():
    from wondershot.video import trim_output_name
    assert trim_output_name("Rec.webm", reencode=True) == "Rec-trimmed.mp4"
    assert trim_output_name("Rec.mkv", reencode=True) == "Rec-trimmed.mp4"


def test_trim_args_stream_copy():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.mp4", 1.0, 8.5,
                           "/l/.rendering/in-trimmed.mp4", reencode=False)
    i = args.index("-i")
    # -ss AND -to as input options (before -i): both absolute timestamps
    assert args[:i] == ["-y", "-ss", "1.000", "-to", "8.500"]
    assert args[i + 1] == "/l/in.mp4"
    c = args.index("-c")
    assert args[c + 1] == "copy"
    assert "-movflags" in args  # mp4 output gets +faststart
    assert args[-1] == "/l/.rendering/in-trimmed.mp4"


def test_trim_args_copy_to_webm_has_no_movflags():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.webm", 0.0, 2.0,
                           "/l/.rendering/in-trimmed.webm", reencode=False)
    assert "-movflags" not in args


def test_trim_args_reencode_x264():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.webm", 0.5, 3.25,
                           "/l/.rendering/in-trimmed.mp4",
                           reencode=True, encoder="libx264")
    v = args.index("-c:v")
    assert args[v + 1] == "libx264"
    assert "-crf" in args and "-preset" in args
    a = args.index("-c:a")
    assert args[a + 1] == "aac"
    assert "-movflags" in args


def test_trim_args_reencode_fallback_encoder():
    from wondershot.video import build_trim_args
    args = build_trim_args("/l/in.mp4", 0.0, 1.0,
                           "/l/.rendering/in-trimmed.mp4",
                           reencode=True, encoder="mpeg4")
    assert "-q:v" in args and "-crf" not in args
```

- [x] **Step 5.2 — Run them, expect failure.** `python -m pytest tests/test_video_filter.py -q` → new tests fail with `ImportError: cannot import name 'trim_output_name'`.

- [x] **Step 5.3 — Implement.** In `wondershot/video.py`, after `frame_output_name`:

```python
def trim_output_name(src_name: str, reencode: bool) -> str:
    """'<stem>-trimmed.<ext>' library name.

    Stream copy must keep the source container (H.264 can't live in WebM
    and vice versa — same constraint the blur pass handles); re-encode is
    always x264-family, so it always lands in .mp4.
    """
    base, ext = os.path.splitext(src_name)
    return f"{base}-trimmed{'.mp4' if reencode else ext}"


def build_trim_args(src: str, start_s: float, end_s: float, out: str,
                    reencode: bool, encoder: str = "libx264") -> list[str]:
    """ffmpeg args trimming src to [start_s, end_s].

    Both -ss and -to are INPUT options (before -i), so both are absolute
    source timestamps. Stream copy snaps the start back to the previous
    keyframe (instant, lossless); re-encode decodes from that keyframe and
    cuts exactly (frame-accurate, slower).
    """
    args = ["-y", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}", "-i", src]
    if reencode:
        enc_opts = (["-crf", "20", "-preset", "veryfast"]
                    if encoder == "libx264" else ["-q:v", "4"])
        args += ["-c:v", encoder, *enc_opts, "-c:a", "aac", "-b:a", "160k"]
    else:
        args += ["-c", "copy"]
    if os.path.splitext(out)[1].lower() in (".mp4", ".m4v", ".mov"):
        args += ["-movflags", "+faststart"]  # instant seeking
    return [*args, out]
```

- [x] **Step 5.4 — Run tests.** `python -m pytest tests/test_video_filter.py -q` → all pass. `python -m pytest tests/ -q` → all pass.

- [x] **Step 5.5 — Commit.**
```
git add wondershot/video.py tests/test_video_filter.py
git commit -m "Trim: pure ffmpeg arg builder (copy vs frame-accurate) + naming"
```

---

## Task 6: Trim mode on the timeline (in/out handles + render flow)

**Files:**
- Modify: `wondershot/video.py` — `RangeBar` (~lines 247–379: switch reads to `pane.spans()`), `VideoPane.__init__` (~419–482: trim widgets + state), `load` (~486), `frozen_mode` (~533), `active_redaction`/`set_active`/`sync_active_row` (~576–651), `refresh_overlays` (~621), `_position_changed` (~551), new `_trim_mode`/`_apply_trim`/`_trim_done` methods
- Modify: `wondershot/gallery.py` — `keyPressEvent` (~line 1000, Esc exits trim mode)
- Test: none new — RangeBar/VideoPane require a live `QMediaPlayer`/video widget stack, which is GUI-only glue not exercisable headless without a media backend; explicitly skipping the failing-test step. All command construction and naming was tested in Task 5; the timeline span-drag math is the existing, shipped RangeBar code operating on a `Redaction` object unchanged.

- [x] **Step 6.1 — VideoPane state + spans indirection.** In `VideoPane.__init__`, next to `self.redactions = []`:

```python
        self.trim: Redaction | None = None   # rect unused; start/end = kept span
        self._trim_proc: QProcess | None = None
```

Add a method after `set_active` (~line 585):

```python
    def spans(self) -> list[Redaction]:
        """What the timeline bar edits: the trim span while trimming,
        otherwise the blur redactions."""
        return [self.trim] if self.trim is not None else self.redactions
```

Replace `active_redaction` with:

```python
    def active_redaction(self) -> Redaction | None:
        if self.trim is not None:
            return self.trim
        if 0 <= self.active_idx < len(self.redactions):
            return self.redactions[self.active_idx]
        return None
```

Guard `set_active` (first line): `if self.trim is not None: return` (the trim span is always "active"; there are no rows to rebuild). Guard `sync_active_row` (first line): `if self.trim is not None: return` (no spin rows exist in trim mode; without this, `self._row_spins[self.active_idx]` IndexErrors).

- [x] **Step 6.2 — RangeBar reads spans().** In `RangeBar`:
  - `_hit` (~line 276): replace both `self.pane.redactions` with `self.pane.spans()`, and replace the active-first ordering head with:

```python
        spans = self.pane.spans()
        active = 0 if self.pane.trim is not None else self.pane.active_idx
        order = []
        if 0 <= active < len(spans):
            order.append(active)
        order += [i for i in range(len(spans)) if i not in order]
        for i in order:
            red = spans[i]
```
  (rest of the loop body unchanged)
  - `mousePressEvent` (~line 297): TWO edits. (a) In the `if hit is not None:` branch, replace `red = self.pane.redactions[hit[1]]` (~line 305) with `red = self.pane.spans()[hit[1]]` — `_hit` now returns indices into `spans()`, and in trim mode `redactions` is empty, so the old line IndexErrors on the first edge-grab. (b) Replace `elif self.pane.redactions:` with `elif self.pane.spans():` (empty-bar drag redefines the trim span too). `mouseMoveEvent` needs no change — it goes through `active_redaction()`, which Step 6.1 already redirects to the trim span.
  - `paintEvent` (~line 357): replace the band loop header `for i, red in enumerate(self.pane.redactions):` with:

```python
        spans = self.pane.spans()
        active_i = 0 if self.pane.trim is not None else self.pane.active_idx
        for i, red in enumerate(spans):
            x1 = red.start * 1000 / dur * w
            x2 = red.end * 1000 / dur * w
            color = (QColor("#3daee9") if self.pane.trim is not None
                     else QColor(PALETTE[i % len(PALETTE)]))
            active = i == active_i
```
  (the alpha/drawRoundedRect lines below stay as they are; the playhead block is untouched). The existing edge-grab logic (`EDGE_PX = 7`, `SplitHCursor`) IS the in/out handle interaction — no new handle code needed.

- [x] **Step 6.3 — Trim widgets.** Add `QCheckBox` to the `PySide6.QtWidgets` import list at the top of video.py. In `VideoPane.__init__` after the `self.apply_btn` block (~line 439):

```python
        self.trim_btn = QPushButton("Trim", self)
        self.trim_btn.setIcon(QIcon.fromTheme("edit-cut"))
        self.trim_btn.setCheckable(True)
        self.trim_btn.toggled.connect(self._trim_mode)
        self.trim_btn.setEnabled(ffmpegutil.have_ffmpeg())

        self.trim_accurate = QCheckBox("Frame-accurate (re-encode)", self)
        self.trim_accurate.setToolTip(
            "Default trim is instant but snaps the start to the previous "
            "keyframe; re-encoding cuts exactly but takes longer")
        self.trim_accurate.hide()

        self.trim_apply_btn = QPushButton("Save trim", self)
        self.trim_apply_btn.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.trim_apply_btn.clicked.connect(self._apply_trim)
        self.trim_apply_btn.hide()
```

Insert into the controls row after `controls.addWidget(self.apply_btn)`:

```python
        controls.addWidget(self.trim_btn)
        controls.addWidget(self.trim_accurate)
        controls.addWidget(self.trim_apply_btn)
```

- [x] **Step 6.4 — Mode toggle + integration points.** Add after `_blur_mode` (~line 596):

```python
    def _trim_mode(self, on: bool) -> None:
        if on and self.redactions:
            self.trim_btn.setChecked(False)
            self._notify("Apply or remove the pending blurs before trimming")
            return
        if on:
            self.player.pause()
            dur = self.player.duration() / 1000.0
            self.trim = Redaction(QRect(), 0.0, round(max(dur, 0.1), 2))
            self._notify("Drag the timeline edges to choose the section to "
                         "keep, then Save trim — the video scrubs as you "
                         "drag", 0)
        else:
            self.trim = None
            self.hint.hide()
        self.trim_accurate.setVisible(on)
        self.trim_apply_btn.setVisible(on)
        self.blur_btn.setEnabled(not on and ffmpegutil.have_ffmpeg())
        self.range_bar.setVisible(on or bool(self.redactions))
        self.range_bar.update()
        self._sync_video_surface()
```

Integration edits (each is one line):
  - `frozen_mode` (~line 533): condition becomes `and (self.overlay.active or bool(self.redactions) or self.trim is not None)` — trim scrubbing previews on the self-painted paused frame, same as blur editing.
  - `refresh_overlays` (~line 621): `self.range_bar.setVisible(bool(self.redactions) or self.trim is not None)`.
  - `_position_changed` (~line 556): `if self.redactions or self.trim is not None:` (so the playhead repaints while scrubbing a trim).
  - `_clear_redactions` (~line 613): add `self.trim_btn.setChecked(False)` after `self.blur_btn.setChecked(False)` (toggling off runs `_trim_mode(False)` which clears `self.trim`).
  - `load` (~line 489): add `self.trim_btn.setVisible(not is_gif)` next to `self.blur_btn.setVisible(not is_gif)`.
  - `_blur_mode` (~line 587): first line of the `if on:` branch, add `self.trim_btn.setChecked(False)` (blur and trim modes are mutually exclusive both ways).

- [x] **Step 6.5 — Render flow.** Add after `_trim_mode`:

```python
    def _apply_trim(self) -> None:
        if not self.path or self.trim is None or self._trim_proc is not None:
            return
        if self.trim.end <= self.trim.start:
            self.status.emit("Trim: end must be after start", 4000)
            return
        from .capture import unique_path
        reencode = self.trim_accurate.isChecked()
        out = unique_path(
            self.settings.library_dir,
            trim_output_name(os.path.basename(self.path), reencode))
        tmp = self._render_temp(out)
        enc = pick_encoder() if reencode else "libx264"
        args = build_trim_args(self.path, self.trim.start, self.trim.end,
                               tmp, reencode, encoder=enc)
        self._trim_proc = QProcess(self)
        self._trim_proc.finished.connect(
            lambda code, _st: self._trim_done(code, tmp, out))
        self.trim_apply_btn.setEnabled(False)
        self.trim_apply_btn.setText("Trimming…")
        self._notify("Trimming — the result will appear in the gallery "
                     "when done", 0)
        self._trim_proc.start(ffmpegutil.ffmpeg_path(), args)

    def _trim_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._trim_proc = self._trim_proc, None
        if proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")
            proc.deleteLater()
        else:
            err = ""
        self.trim_apply_btn.setEnabled(True)
        self.trim_apply_btn.setText("Save trim")
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self.trim_btn.setChecked(False)  # exits trim mode
            self._notify(f"Saved {os.path.basename(out)}")
            self.file_ready.emit(out)
        else:
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self._notify(f"Trim failed: {tail[:160]}", 10000)
            if os.path.exists(tmp):
                os.unlink(tmp)
```

Note `tmp` (not `out`) is passed to `build_trim_args` as the output — same basename/extension, so the `-movflags` extension check behaves identically, and the half-written file stays hidden in `.rendering/` like every other render.

- [x] **Step 6.6 — Esc exits trim mode.** In `wondershot/gallery.py` `keyPressEvent` (~line 1000), extend the Esc branch:

```python
        if ev.key() == Qt.Key_Escape:
            # Esc cancels things; it never hides the window.
            if (self.video_pane is not None
                    and self.video_pane.blur_btn.isChecked()):
                self.video_pane.blur_btn.setChecked(False)
            elif (self.video_pane is not None
                    and self.video_pane.trim_btn.isChecked()):
                self.video_pane.trim_btn.setChecked(False)
            else:
                self.editor.scene.clearSelection()
```

- [x] **Step 6.7 — Run the suite + manual smoke.** `python -m pytest tests/ -q` → all pass (the RangeBar refactor must not break the blur tests — `build_blur_filter` is untouched). Manual check (desktop session): open a recording → Trim → drag in/out edges (video scrubs) → Save trim with checkbox off (near-instant, `<stem>-trimmed.<ext>`) and on (re-encodes to `.mp4`); verify blur mode still works after exiting trim mode, and Esc exits trim.

- [x] **Step 6.8 — Commit.**
```
git add wondershot/video.py wondershot/gallery.py
git commit -m "Trim mode: in/out handles on the range timeline, stream-copy default, frame-accurate re-encode option"
```

---

## Task 7: Cursor halo — TIMEBOXED probe, then implement OR document

**Hard timebox: 2 hours from starting Step 7.1 to the decision in Step 7.3.** Tasks 1–6 are already complete and committed; nothing here may touch them. The likely outcome is branch B (document): `pipewiresrc` has historically not surfaced `spa_meta_cursor` (the metadata cursor stream) to downstream GStreamer elements, and our recorder is a `gst-launch-1.0` argv subprocess (`record.py` `_gst_args`, ~line 228) with no programmatic buffer access.

**Files:**
- Create: `spikes/cursor_halo_probe.md` (probe transcript — always)
- Branch A only — Modify: `wondershot/settings.py` (new property after `noise_suppression`, ~line 97), `wondershot/settings_dialog.py` (General tab ~line 176, `apply()` ~line 602), `wondershot/record.py` (`_created` ~line 172, `_gst_args` ~line 228); Test: `tests/test_record.py`
- Branch B only — Modify: `ROADMAP.md` (WS-A cursor halo bullet, ~lines 107–108)

- [x] **Step 7.1 — Probe the stack (no production code).** Run and capture output of each:

```
# 1. Does the portal offer metadata cursor mode? (bitmask: 1=hidden, 2=embedded, 4=metadata)
gdbus call --session --dest org.freedesktop.portal.Desktop \
  --object-path /org/freedesktop/portal/desktop \
  --method org.freedesktop.DBus.Properties.Get \
  org.freedesktop.portal.ScreenCast AvailableCursorModes

# 2. Does pipewiresrc expose ANY cursor-related property or meta API?
gst-inspect-1.0 pipewiresrc

# 3. What pipewire-gstreamer version is installed, and does its source mention spa_meta_cursor?
rpm -q pipewire-gstreamer
```

Then the empirical check: temporarily hardcode `"cursor_mode": GLib.Variant("u", 4)` in `record.py` `_created` (line ~182), run `python -m wondershot`, record 5 seconds while moving the mouse, and inspect the output: with metadata mode the cursor should be ABSENT from the frames (confirming the portal honored it) and there is no element in our pipeline string that could receive its coordinates. Revert the hardcode immediately after.

- [x] **Step 7.2 — Record the transcript.** Create `spikes/cursor_halo_probe.md` containing: the exact commands above, their verbatim output, the recorded-clip observation (cursor present/absent), and one paragraph stating which branch the evidence selects and why. Commit:
```
git add spikes/cursor_halo_probe.md
git commit -m "Cursor halo spike: probe transcript for portal metadata cursor mode in gst-launch pipeline"
```

- [x] **Step 7.3 — Decision gate.** Branch A only if BOTH hold: (a) `AvailableCursorModes` includes 4, and (b) the probe found a concrete mechanism by which cursor coordinates reach a compositing element inside a `gst-launch-1.0` argv pipeline (e.g. a pipewiresrc property that re-embeds or exposes the cursor). If either fails — or the timebox expires — take branch B.

### Branch A — implement (only if the gate passed)

- [ ] **Step 7.A1 — Write the failing test.** Append to `tests/test_record.py`:

```python
def test_source_options_cursor_mode(tmp_path):
    pytest.importorskip("gi")
    rec = make_recorder(tmp_path)
    rec.settings.cursor_halo = False
    assert rec._source_options("tok")["cursor_mode"].get_uint32() == 2
    rec.settings.cursor_halo = True
    assert rec._source_options("tok")["cursor_mode"].get_uint32() == 4
    assert rec._source_options("tok")["handle_token"].get_string() == "tok"
```

Run: `python -m pytest tests/test_record.py::test_source_options_cursor_mode -q` → fails with `AttributeError: 'ScreenRecorder' object has no attribute '_source_options'`.

- [ ] **Step 7.A2 — Extract `_source_options` in `record.py`.** Replace the inline `options = {...}` block in `_created` (~lines 178–188) with a call to a new method, keeping behavior identical when the setting is off:

```python
    def _source_options(self, token: str) -> dict:
        cursor_mode = 4 if getattr(self.settings, "cursor_halo", False) else 2
        options = {
            "handle_token": GLib.Variant("s", token),
            "types": GLib.Variant("u", 3),        # monitor | window
            "multiple": GLib.Variant("b", False),
            "cursor_mode": GLib.Variant("u", cursor_mode),
            "persist_mode": GLib.Variant("u", 2),  # remember permanently
        }
        restore = self.settings.screencast_token
        if restore:
            options["restore_token"] = GLib.Variant("s", restore)
        return options
```

and in `_created`:

```python
        token = self._token()
        self._on_request(token, self._sources_selected)
        self._call("SelectSources",
                   GLib.Variant("(oa{sv})",
                                (self._session, self._source_options(token))))
```

Run: `python -m pytest tests/test_record.py -q` → all pass.

- [ ] **Step 7.A3 — Settings property.** In `wondershot/settings.py`, after the `noise_suppression` setter (~line 97):

```python
    @property
    def cursor_halo(self) -> bool:
        """Draw a translucent halo around the pointer in recordings."""
        return self._s.value("cursor_halo", "false") in (True, "true")

    @cursor_halo.setter
    def cursor_halo(self, value: bool) -> None:
        self._s.setValue("cursor_halo", "true" if value else "false")
```

- [ ] **Step 7.A4 — Settings dialog checkbox.** In `wondershot/settings_dialog.py`, after the `noise_check` block (~line 176):

```python
        self.halo_check = QCheckBox(
            "Highlight the cursor with a halo in recordings")
        self.halo_check.setChecked(settings.cursor_halo)
        form.addRow("", self.halo_check)
```

And in `apply()` (~line 602), after the `noise_suppression` line:

```python
        self.settings.cursor_halo = self.halo_check.isChecked()
```

- [ ] **Step 7.A5 — Pipeline compositing.** Extend `_gst_args` in `record.py` using exactly the mechanism the probe validated in Step 7.3(b) — insert the halo-drawing element(s) between `videoconvert` and `videorate`, gated on `self.settings.cursor_halo`, mirroring how the `dsp` block conditionally extends the audio branch (~line 248). Extend `test_video_branch_sanitizes_timestamps`-style coverage with a new test in `tests/test_record.py` asserting the halo element appears in `_gst_args(...)` output when `FakeSettings.cursor_halo = True` and not when `False` (add `self.cursor_halo = False` to `FakeSettings.__init__`). Verify with a real 10-second recording that the halo tracks the cursor and the file finalizes. If this step exceeds the remaining timebox, abandon branch A: `git checkout -- wondershot/ tests/` and take branch B.

- [ ] **Step 7.A6 — Run tests + commit.** `python -m pytest tests/ -q` → all pass.
```
git add wondershot/record.py wondershot/settings.py wondershot/settings_dialog.py tests/test_record.py
git commit -m "Cursor halo: Settings->Recording option, portal metadata cursor mode, halo composite in gst pipeline"
```

### Branch B — document (the expected outcome)

- [x] **Step 7.B1 — Update ROADMAP.md.** Replace the WS-A cursor halo bullet (~lines 107–108, currently "Cursor halo (M): portal cursor-mode *metadata* + composite in our gst pipeline. Static halo only — click *animation* gated on WS-D input") with:

```markdown
- Cursor halo (M): **investigated 2026-06-06, parked.** Portal cursor-mode
  *metadata* (4) delivers pointer coordinates as PipeWire `spa_meta_cursor`
  per-buffer stream metadata — but our recorder is a `gst-launch-1.0` argv
  subprocess, and `pipewiresrc` does not translate that metadata into
  anything a downstream element in a pipeline string can read, so there is
  nowhere to composite a halo. (Probe transcript:
  `spikes/cursor_halo_probe.md` — AvailableCursorModes, gst-inspect of
  pipewiresrc, and a metadata-mode test recording confirming the cursor
  vanishes with no recoverable coordinates.) Unblocking requires owning the
  pipeline in-process (appsink/appsrc, or a pw_stream consumer) so we can
  read `spa_meta_cursor` per buffer and draw the halo ourselves — that
  rewrite is the same frame-source seam WS-D's scroll capture needs, so the
  halo rides along with WS-D rather than blocking WS-A. Until then,
  recordings keep cursor-mode *embedded* (2). Click *animation* remains
  gated on WS-D input capture.
```

Adjust the bullet text to match the actual probe findings if they differ in detail (e.g. metadata mode not offered at all) — the transcript file is the source of truth.

- [x] **Step 7.B2 — Verify nothing else changed and commit.** `git status` shows only `ROADMAP.md` modified (the probe transcript was committed in 7.2; any temporary hardcode in record.py is reverted). `python -m pytest tests/ -q` → all pass.
```
git add ROADMAP.md
git commit -m "Cursor halo: document gst-launch metadata-cursor findings, park behind WS-D pipeline rewrite"
```
