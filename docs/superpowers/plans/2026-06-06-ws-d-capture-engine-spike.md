# WS-D: Capture Engine Spike — Scroll Stitching + InputCapture Probe

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Produce running code that answers WS-D's two questions: (1) can we stitch a scrolled window into one tall PNG from the existing portal ScreenCast pipeline, and (2) does this Fedora/KDE box expose a usable `org.freedesktop.portal.InputCapture` portal for step capture.

**Architecture:** A pure, fully unit-tested stitcher core (`wondershot/stitch.py`) that consumes only `QImage`s through a `FrameSource` seam — it must never import PipeWire/GStreamer types (this is the WS-E portability seam). A spike-quality Linux `FrameSource` (`wondershot/scrollsource.py`) reuses `record.py`'s portal dance by subclassing `ScreenRecorder` and swapping the `gst-launch` subprocess for an in-process appsink pipeline, wired to a hidden `--scroll-spike` CLI flag. A standalone D-Bus probe script (`spikes/inputcapture_probe.py`) reports InputCapture portal findings, and a findings template is appended to `ROADMAP.md` for the executor to fill after manual runs.

**Tech Stack:** Python ≥3.10, PySide6 (QImage/QtCore), numpy (new optional extra `wondershot[spike]`), PyGObject (`gi` — Gio/GLib/Gst, already a system dep of `record.py`), pytest (headless, `QT_QPA_PLATFORM=offscreen`).

---

## Context for an engineer with zero codebase knowledge

- Repo: `/home/jack/GitHub/grabbit` (you execute in a worktree branched from `main`; this plan file is present in the worktree). Package dir: `wondershot/`. Tests: `tests/` (pytest).
- Spec: `docs/superpowers/specs/2026-06-06-snagit-parity-design.md`, section "This session: WS-D".
- The main checkout has `.venv/` made with `--system-site-packages` (so the system `gi` module is visible — required; see ROADMAP "Platform landmines"). Your worktree will NOT have it; Task 1 creates one.
- `wondershot/record.py` (387 lines) is the existing recorder: xdg-desktop-portal ScreenCast dance over Gio/GLib (`CreateSession → SelectSources → Start → OpenPipeWireRemote`) yielding a PipeWire fd + node id, then a `gst-launch-1.0` subprocess encodes to mp4. Key members of `ScreenRecorder(QObject)` you will reuse by subclassing: `start()` (runs the whole dance, ends by calling `self._launch_gst(fd, node)`), `_launch_gst(self, fd, node)` (we override this), `stop()` (we override this — base version assumes a subprocess), `_cleanup()` (closes fd + portal session; safe to call with `_proc is None`), `available()`, signals `started`, `failed(str)`, `finished(str)`, attributes `self.settings`, `self.recording`, `self._busy`, module constant `_HAVE_GIO`.
- `wondershot/cli.py`: argparse entry point. `build_command(args)` maps flags to single-instance commands; special modes (`--install-desktop`, `--selftest`) short-circuit before the Qt app starts — `--scroll-spike` follows that pattern.
- `wondershot/hotkey.py` module docstring is the KWin landmine history: a mistyped D-Bus call into KGlobalAccel **aborted the compositor** (kwin 6.6.5). Defensive posture for the probe: only talk to `org.freedesktop.portal.Desktop` (the portal daemon process, not KWin), always pass explicitly typed `GLib.Variant`s (portals demand uint32-typed options — PySide6's QtDBus cannot produce them, which is why portal code uses Gio/GLib), wrap every call in `try/except GLib.Error`, use finite timeouts.
- `wondershot/imageops.py` + `tests/test_imageops.py` are the idiom for pure-image TDD: session-scoped `qapp` fixture with `QT_QPA_PLATFORM=offscreen` and a `QGuiApplication`, synthetic QImages, no widgets. Copy that fixture style.
- `tests/test_record.py` shows the headless-Qt test pattern with `QApplication` and `processEvents` polling — not needed here; stitch tests are synchronous pure functions.
- ROADMAP landmine relevant to the appsink pipeline: "pipewiresrc intermittently emits buffers with no PTS … videorate + fixed framerate caps drop them". Keep `videorate` in the appsink pipeline too.
- numpy is NOT installed anywhere yet (checked). Task 1 adds it as the `spike` extra.
- Run tests with: `.venv/bin/python -m pytest tests/ -q` (the venv you create in Task 1).

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify (~line 13, after `dependencies`) | Add `[project.optional-dependencies] spike = ["numpy"]` |
| `wondershot/stitch.py` | Create | Portability seam: `FrameSource` ABC (Qt-only) + pure stitcher core — QImage↔numpy conversion, vertical offset detection via overlap band matching, static header/footer band detection, `ScrollStitcher` accumulator. **Never imports gi/Gst/PipeWire.** |
| `tests/test_stitch.py` | Create | Full TDD coverage of stitch.py: conversions, offset detection, static bands, end-to-end synthetic reconstruction, no-motion drop |
| `wondershot/scrollsource.py` | Create | Spike-quality Linux `FrameSource`: subclasses `ScreenRecorder`, replaces gst-launch subprocess with in-process Gst appsink pipeline emitting QImages; plus `run_scroll_spike()` CLI runner. Manual-test only (explicitly). |
| `wondershot/cli.py` | Modify (argparser ~line 44-50, dispatch ~line 53-58) | Hidden `--scroll-spike` flag short-circuiting to `run_scroll_spike()` |
| `spikes/inputcapture_probe.py` | Create | Standalone (non-package) InputCapture portal probe; prints `FINDING:` lines; defensive D-Bus posture. Manual-run only (explicitly). |
| `ROADMAP.md` | Modify (append at end) | WS-D findings template for the executor to fill after manual runs |

---

## Task 1: Worktree environment + `spike` extra

**Files:**
- Modify: `pyproject.toml` (insert after line 13 `dependencies = ["PySide6>=6.6"]`)
- Test: existing suite (baseline)

- [x] Create the venv in the worktree root (system-site-packages is REQUIRED so `gi` is importable — ROADMAP landmine):
  ```bash
  python3 -m venv --system-site-packages .venv
  .venv/bin/pip install -e . pytest
  ```
- [x] Run the existing suite to establish a green baseline:
  ```bash
  .venv/bin/python -m pytest tests/ -q
  ```
  Expected: all tests pass (8 test files). If anything fails here, stop — the baseline is broken, not your work.
- [x] Edit `pyproject.toml`: after the `dependencies = ["PySide6>=6.6"]` line and before `keywords`, add:
  ```toml
  [project.optional-dependencies]
  spike = ["numpy"]  # WS-D scroll-stitch spike only; not a runtime dep
  ```
  Note: TOML tables can't nest mid-table — place this block AFTER the entire `[project]` table's simple keys but it must still belong to project. Concretely, put it between the `keywords = [...]` line and `[project.scripts]`.
- [x] Install the extra:
  ```bash
  .venv/bin/pip install -e ".[spike]"
  .venv/bin/python -c "import numpy; print(numpy.__version__)"
  ```
  Expected: a version prints.
- [x] Re-run the suite (`.venv/bin/python -m pytest tests/ -q`), expected: still green.
- [x] Commit:
  ```bash
  git add pyproject.toml && git commit -m "WS-D: add wondershot[spike] extra (numpy) for scroll-stitch spike"
  ```

---

## Task 2: stitch.py — QImage↔numpy conversions + FrameSource seam

**Files:**
- Create: `wondershot/stitch.py`
- Create: `tests/test_stitch.py`

- [x] Write the failing test. Create `tests/test_stitch.py`:
  ```python
  import os

  import numpy as np
  import pytest

  os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

  from PySide6.QtGui import QImage


  @pytest.fixture(scope="session", autouse=True)
  def qapp():
      from PySide6.QtGui import QGuiApplication
      app = QGuiApplication.instance() or QGuiApplication([])
      yield app


  def make_rgb(height=60, width=40, seed=7) -> np.ndarray:
      """Deterministic noise image: every row is unique."""
      rng = np.random.default_rng(seed)
      return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


  def test_rgb_qimage_roundtrip_exact():
      from wondershot.stitch import qimage_to_rgb, rgb_to_qimage
      arr = make_rgb()
      img = rgb_to_qimage(arr)
      assert img.width() == 40 and img.height() == 60
      assert img.format() == QImage.Format_RGB888
      back = qimage_to_rgb(img)
      assert np.array_equal(arr, back)


  def test_qimage_to_rgb_handles_other_formats():
      """Real frames arrive as RGB32/ARGB32 from the appsink; conversion
      must normalize any input format to (H, W, 3) RGB."""
      from wondershot.stitch import qimage_to_rgb
      img = QImage(10, 8, QImage.Format_ARGB32_Premultiplied)
      img.fill(0xFF336699)  # opaque RGB(0x33, 0x66, 0x99)
      arr = qimage_to_rgb(img)
      assert arr.shape == (8, 10, 3)
      assert tuple(arr[0, 0]) == (0x33, 0x66, 0x99)


  def test_to_gray_shape_and_range():
      from wondershot.stitch import qimage_to_rgb, to_gray
      arr = make_rgb()
      g = to_gray(arr)
      assert g.shape == (60, 40)
      assert g.dtype == np.float32
      assert 0.0 <= g.min() and g.max() <= 255.0
  ```
- [x] Run it — must fail with `ModuleNotFoundError: No module named 'wondershot.stitch'`:
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
- [x] Implement. Create `wondershot/stitch.py`:
  ```python
  """Scroll-capture stitcher core (WS-D spike).

  PORTABILITY SEAM (WS-E): this module consumes QImages only. It must
  NEVER import PipeWire, GStreamer, or gi types — platform frame
  delivery lives behind FrameSource implementations (scrollsource.py
  on Linux today; Windows/macOS sources later).

  Requires numpy (install the spike extra: pip install -e ".[spike]").
  """

  from __future__ import annotations

  import numpy as np
  from PySide6.QtCore import QObject, Signal
  from PySide6.QtGui import QImage


  class FrameSource(QObject):
      """Delivers viewport frames as QImages.

      Implementations own all platform machinery (portals, PipeWire,
      GStreamer, native APIs); consumers only ever see QImages.
      """

      frame = Signal(QImage)
      started = Signal()
      failed = Signal(str)

      def start(self) -> None:  # pragma: no cover - interface
          raise NotImplementedError

      def stop(self) -> None:  # pragma: no cover - interface
          raise NotImplementedError


  # -- QImage <-> numpy ----------------------------------------------------

  def qimage_to_rgb(img: QImage) -> np.ndarray:
      """Return an (H, W, 3) uint8 RGB copy of img (any source format)."""
      rgb = img.convertToFormat(QImage.Format_RGB888)
      h, w = rgb.height(), rgb.width()
      # Scanlines are padded to 4 bytes — slice each row to w*3.
      buf = np.frombuffer(rgb.constBits(), dtype=np.uint8,
                          count=rgb.sizeInBytes())
      buf = buf.reshape(h, rgb.bytesPerLine())
      return buf[:, :w * 3].reshape(h, w, 3).copy()


  def rgb_to_qimage(arr: np.ndarray) -> QImage:
      """Return a detached QImage (Format_RGB888) from an (H, W, 3) array."""
      h, w, _ = arr.shape
      arr = np.ascontiguousarray(arr, dtype=np.uint8)
      img = QImage(arr.tobytes(), w, h, w * 3, QImage.Format_RGB888)
      return img.copy()  # detach from the Python buffer


  def to_gray(rgb: np.ndarray) -> np.ndarray:
      """(H, W) float32 luma for matching; exactness doesn't matter."""
      return rgb.astype(np.float32).mean(axis=2)
  ```
- [x] Run tests, expected pass:
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
- [x] Commit:
  ```bash
  git add wondershot/stitch.py tests/test_stitch.py
  git commit -m "WS-D: stitch.py FrameSource seam + QImage/numpy conversions (TDD)"
  ```

---

## Task 3: stitch.py — vertical offset detection (overlap band matching)

**Files:**
- Modify: `wondershot/stitch.py` (append)
- Modify: `tests/test_stitch.py` (append)

- [x] Write the failing tests. Append to `tests/test_stitch.py`:
  ```python
  def test_detect_offset_finds_scroll():
      """cur is prev scrolled up by d rows: cur[y] == prev[y + d]."""
      from wondershot.stitch import detect_offset, to_gray
      tall = make_rgb(height=300, width=40, seed=1)
      prev = to_gray(tall[0:200])
      for d in (1, 17, 60, 130):
          cur = to_gray(tall[d:200 + d])
          assert detect_offset(prev, cur) == d


  def test_detect_offset_identical_frames_is_zero():
      from wondershot.stitch import detect_offset, to_gray
      g = to_gray(make_rgb(height=200, width=40, seed=2))
      assert detect_offset(g, g) == 0


  def test_detect_offset_unrelated_frames_is_none():
      """A scene change (different window content) must not stitch."""
      from wondershot.stitch import detect_offset, to_gray
      a = to_gray(make_rgb(height=200, width=40, seed=3))
      b = to_gray(make_rgb(height=200, width=40, seed=4))
      assert detect_offset(a, b) is None
  ```
- [x] Run — must fail with `ImportError: cannot import name 'detect_offset'`:
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
- [x] Implement. Append to `wondershot/stitch.py`:
  ```python
  # -- offset detection ------------------------------------------------------

  def detect_offset(prev: np.ndarray, cur: np.ndarray,
                    band: int = 64, threshold: float = 8.0) -> int | None:
      """Vertical scroll distance between two grayscale frames.

      Overlap band matching: take the top `band` rows of cur and slide
      them down prev; at the true offset d, cur[y] == prev[y + d], so
      the band matches prev[d : d + band].

      Returns 0 for no motion, d > 0 for a downward scroll, or None
      when no candidate's mean abs difference beats `threshold`
      (scene change / unrelated frames).

      Known spike limitation: a uniform (featureless) band matches
      everywhere and resolves to d=0 (frame dropped) — acceptable.
      """
      h = prev.shape[0]
      band = min(band, h)
      strip = cur[:band]
      best_d: int | None = None
      best_score = threshold
      for d in range(0, h - band + 1):
          score = float(np.abs(prev[d:d + band] - strip).mean())
          if score < best_score:  # strict: ties keep the smallest d
              best_d, best_score = d, score
      return best_d
  ```
- [x] Run tests, expected pass:
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
- [x] Commit:
  ```bash
  git add wondershot/stitch.py tests/test_stitch.py
  git commit -m "WS-D: overlap-band vertical offset detection (TDD)"
  ```

---

## Task 4: stitch.py — static header/footer band detection

**Files:**
- Modify: `wondershot/stitch.py` (append)
- Modify: `tests/test_stitch.py` (append)

- [x] Write the failing tests. Append to `tests/test_stitch.py`:
  ```python
  def _frame_with_chrome(content: np.ndarray, header: np.ndarray,
                         footer: np.ndarray) -> np.ndarray:
      return np.vstack([header, content, footer])


  def test_static_bands_detects_header_and_footer():
      from wondershot.stitch import static_bands, to_gray
      tall = make_rgb(height=400, width=40, seed=5)
      header = make_rgb(height=15, width=40, seed=6)
      footer = make_rgb(height=25, width=40, seed=7)
      prev = to_gray(_frame_with_chrome(tall[0:200], header, footer))
      cur = to_gray(_frame_with_chrome(tall[50:250], header, footer))
      assert static_bands(prev, cur) == (15, 25)


  def test_static_bands_none_when_everything_scrolls():
      from wondershot.stitch import static_bands, to_gray
      tall = make_rgb(height=400, width=40, seed=8)
      prev = to_gray(tall[0:200])
      cur = to_gray(tall[50:250])
      assert static_bands(prev, cur) == (0, 0)


  def test_static_bands_identical_frames_returns_zero():
      """Whole frame 'static' is meaningless — refuse, don't crop all."""
      from wondershot.stitch import static_bands, to_gray
      g = to_gray(make_rgb(height=200, width=40, seed=9))
      assert static_bands(g, g) == (0, 0)
  ```
- [x] Run — must fail with `ImportError: cannot import name 'static_bands'`:
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
- [x] Implement. Append to `wondershot/stitch.py`:
  ```python
  # -- fixed header/footer heuristic (best effort for the spike) ------------

  def static_bands(prev: np.ndarray, cur: np.ndarray,
                   tolerance: float = 4.0) -> tuple[int, int]:
      """(header_height, footer_height): contiguous edge rows that are
      identical at the SAME y across a scrolled pair — i.e. window
      chrome / sticky headers that don't move while content scrolls.

      Best effort: scrolled content that coincidentally matches itself
      can inflate the bands; real pages rarely do. If the 'static'
      region covers the whole frame (frames identical), returns (0, 0).
      """
      row_same = np.abs(prev - cur).mean(axis=1) < tolerance
      h = len(row_same)
      header = 0
      while header < h and row_same[header]:
          header += 1
      footer = 0
      while footer < h and row_same[h - 1 - footer]:
          footer += 1
      if header + footer >= h:
          return (0, 0)
      return (header, footer)
  ```
- [x] Run tests, expected pass:
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
- [x] Commit:
  ```bash
  git add wondershot/stitch.py tests/test_stitch.py
  git commit -m "WS-D: static header/footer band heuristic (TDD)"
  ```

---

## Task 5: stitch.py — ScrollStitcher accumulator (end-to-end synthetic reconstruction)

**Files:**
- Modify: `wondershot/stitch.py` (append)
- Modify: `tests/test_stitch.py` (append)

- [x] Write the failing tests — this is the load-bearing reconstruction proof. Append to `tests/test_stitch.py`:
  ```python
  def _window_frames(tall: np.ndarray, viewport: int, offsets):
      """Simulate a user scrolling: viewport-sized windows of a tall page."""
      from wondershot.stitch import rgb_to_qimage
      return [rgb_to_qimage(tall[o:o + viewport]) for o in offsets]


  def test_stitcher_reconstructs_tall_image():
      from wondershot.stitch import ScrollStitcher, qimage_to_rgb
      tall = make_rgb(height=900, width=120, seed=10)
      offsets = [0, 30, 60, 95, 140, 200, 260, 300]
      st = ScrollStitcher()
      for f in _window_frames(tall, viewport=200, offsets=offsets):
          st.add_frame(f)
      out = qimage_to_rgb(st.result())
      expected = tall[0:offsets[-1] + 200]   # rows 0..500
      assert out.shape == expected.shape
      assert np.array_equal(out, expected)
      assert st.frames_used == len(offsets)


  def test_stitcher_drops_no_motion_frames():
      from wondershot.stitch import ScrollStitcher, qimage_to_rgb
      tall = make_rgb(height=600, width=80, seed=11)
      frames = _window_frames(tall, 200, [0, 0, 40, 40, 40, 80])
      st = ScrollStitcher()
      for f in frames:
          st.add_frame(f)
      out = qimage_to_rgb(st.result())
      assert np.array_equal(out, tall[0:280])
      assert st.frames_dropped == 3


  def test_stitcher_strips_fixed_header_and_footer():
      from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
      tall = make_rgb(height=700, width=100, seed=12)
      header = make_rgb(height=18, width=100, seed=13)
      footer = make_rgb(height=22, width=100, seed=14)
      st = ScrollStitcher()
      for o in [0, 35, 70, 110]:
          st.add_frame(rgb_to_qimage(
              _frame_with_chrome(tall[o:o + 160], header, footer)))
      out = qimage_to_rgb(st.result())
      assert np.array_equal(out, tall[0:110 + 160])


  def test_stitcher_single_frame_passthrough():
      from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
      arr = make_rgb(height=150, width=60, seed=15)
      st = ScrollStitcher()
      st.add_frame(rgb_to_qimage(arr))
      assert np.array_equal(qimage_to_rgb(st.result()), arr)


  def test_stitcher_empty_result_is_null_image():
      from wondershot.stitch import ScrollStitcher
      assert ScrollStitcher().result().isNull()


  def test_stitcher_scene_change_does_not_append_garbage():
      """detect_offset -> None must not vstack unrelated content."""
      from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
      a = make_rgb(height=200, width=60, seed=16)
      b = make_rgb(height=200, width=60, seed=17)
      st = ScrollStitcher()
      st.add_frame(rgb_to_qimage(a))
      st.add_frame(rgb_to_qimage(b))
      assert np.array_equal(qimage_to_rgb(st.result()), a)
      assert st.frames_dropped == 1
  ```
- [x] Run — must fail with `ImportError: cannot import name 'ScrollStitcher'`:
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
- [x] Implement. Append to `wondershot/stitch.py`:
  ```python
  # -- accumulator -----------------------------------------------------------

  class ScrollStitcher:
      """Accumulates scrolled viewport frames into one tall image.

      Feed frames via add_frame() in capture order; read the tall
      QImage from result(). Pure image math — safe to unit test and
      to reuse unchanged on Windows/macOS (WS-E).
      """

      def __init__(self, band: int = 64, col_step: int = 4):
          self.band = band
          self.col_step = col_step      # column subsampling for matching
          self._canvas: np.ndarray | None = None     # (H, W, 3) uint8
          self._prev_gray: np.ndarray | None = None  # full-res gray
          self._header = 0
          self._footer = 0
          self._bands_locked = False
          self.frames_used = 0
          self.frames_dropped = 0

      def add_frame(self, img: QImage) -> None:
          rgb = qimage_to_rgb(img)
          gray = to_gray(rgb)
          if self._canvas is None:
              self._canvas = rgb
              self._prev_gray = gray
              self.frames_used += 1
              return
          if float(np.abs(gray - self._prev_gray).mean()) < 1.0:
              self.frames_dropped += 1   # no motion: drop
              return
          if not self._bands_locked:
              # First moving pair defines the fixed chrome; freeze it
              # and re-crop the canvas (which is just frame 0 so far).
              self._header, self._footer = static_bands(
                  self._prev_gray, gray)
              self._bands_locked = True
              self._canvas = self._crop(self._canvas)
          d = detect_offset(
              self._crop(self._prev_gray)[:, ::self.col_step],
              self._crop(gray)[:, ::self.col_step],
              band=self.band)
          self._prev_gray = gray   # always resync, even on a miss
          if not d:                # None (scene change) or 0 (no scroll)
              self.frames_dropped += 1
              return
          self._canvas = np.vstack([self._canvas, self._crop(rgb)[-d:]])
          self.frames_used += 1

      def _crop(self, arr: np.ndarray) -> np.ndarray:
          end = arr.shape[0] - self._footer
          return arr[self._header:end]

      def result(self) -> QImage:
          if self._canvas is None:
              return QImage()
          return rgb_to_qimage(self._canvas)
  ```
- [x] Run the full stitch suite, expected pass (all tasks 2-5 tests):
  ```bash
  .venv/bin/python -m pytest tests/test_stitch.py -q
  ```
  Gotcha if `test_stitcher_drops_no_motion_frames` fails on the count: offsets `[0, 0, 40, 40, 40, 80]` give one duplicate of frame 0 and two duplicates of the 40-frame = 3 drops, 3 used. If reconstruction fails on the header test: remember bands lock on the first DIFFERING pair (frames at offsets 0 and 35), and the canvas (frame 0) is re-cropped at that moment.
- [x] Run the whole repo suite to confirm nothing else broke:
  ```bash
  .venv/bin/python -m pytest tests/ -q
  ```
- [x] Commit:
  ```bash
  git add wondershot/stitch.py tests/test_stitch.py
  git commit -m "WS-D: ScrollStitcher with synthetic end-to-end reconstruction (TDD)"
  ```

---

## Task 6: scrollsource.py — Linux ScreenCast FrameSource (spike quality)

**Files:**
- Create: `wondershot/scrollsource.py`

**Explicitly stated:** this GStreamer/portal half is spike-quality. It has NO unit tests — the portal dance needs a live compositor and user interaction, which cannot run headless. Manual test instructions are in Task 7 (after the CLI flag exists). Do not write a failing test for this task.

- [x] Create `wondershot/scrollsource.py`:
  ```python
  """Linux FrameSource: portal ScreenCast -> PipeWire -> Gst appsink.

  WS-D SPIKE QUALITY. Reuses record.py's portal dance by subclassing
  ScreenRecorder and overriding _launch_gst: instead of spawning a
  gst-launch subprocess that encodes mp4, we build an in-process
  pipeline ending in an appsink and emit each sample as a QImage.

  The stitcher side (stitch.py) never sees Gst/PipeWire types — frames
  cross this boundary as QImages only (WS-E portability seam).

  Threading note: appsink's new-sample callback fires on a GStreamer
  streaming thread, and the QImage is deep-copied before emitting.
  BUT: connecting the signal to a plain-Python callable (ScrollStitcher
  is not a QObject) gives a DIRECT connection — add_frame runs on the
  streaming thread, not the Qt main loop. Acceptable for the spike
  because the stitcher touches no UI and stop() drives the pipeline to
  NULL (callbacks cease) before result() is read on the main thread.
  Productization (WS-E) must put the stitcher behind a QObject so
  delivery is queued.
  """

  from __future__ import annotations

  import signal as _signal
  import sys

  from PySide6.QtCore import QTimer, Signal
  from PySide6.QtGui import QImage

  from .record import _HAVE_GIO, ScreenRecorder


  def _gst():
      import gi
      gi.require_version("Gst", "1.0")
      from gi.repository import Gst
      if not Gst.is_initialized():
          Gst.init(None)
      return Gst


  class ScreenCastFrameSource(ScreenRecorder):
      """FrameSource over the existing portal ScreenCast dance.

      Inherits the whole CreateSession/SelectSources/Start/
      OpenPipeWireRemote flow (and the persisted restore token) from
      ScreenRecorder; only the pipeline endpoint differs.
      Duck-types stitch.FrameSource: start()/stop()/frame/started/failed.
      """

      frame = Signal(QImage)

      def __init__(self, settings, fps: int = 10, parent=None):
          super().__init__(settings, parent)
          self.fps = fps
          self._pipeline = None

      def available(self) -> bool:
          if not _HAVE_GIO:
              return False
          try:
              _gst()
              return True
          except (ImportError, ValueError):
              return False

      # ScreenRecorder.start() runs the portal dance, then calls this
      # with the PipeWire fd + node id.
      def _launch_gst(self, fd: int, node: int) -> None:
          Gst = _gst()
          # videorate: pipewiresrc emits PTS-less buffers near stream
          # start (ROADMAP landmine); also throttles stitch input.
          desc = (
              f"pipewiresrc fd={fd} path={node} do-timestamp=true ! "
              "queue ! videoconvert ! videorate ! "
              f"video/x-raw,format=BGRx,framerate={self.fps}/1 ! "
              "appsink name=sink emit-signals=true max-buffers=2 "
              "drop=true sync=false"
          )
          try:
              self._pipeline = Gst.parse_launch(desc)
          except Exception as e:  # GLib.Error from parse_launch
              self._fail(f"could not build appsink pipeline: {e}")
              return
          sink = self._pipeline.get_by_name("sink")
          sink.connect("new-sample", self._on_sample)
          self._pipeline.set_state(Gst.State.PLAYING)
          self._busy = False
          self.recording = True
          self.started.emit()

      def _on_sample(self, sink):
          Gst = _gst()
          sample = sink.emit("pull-sample")
          if sample is None:
              return Gst.FlowReturn.OK
          caps = sample.get_caps().get_structure(0)
          w = caps.get_value("width")
          h = caps.get_value("height")
          buf = sample.get_buffer()
          ok, info = buf.map(Gst.MapFlags.READ)
          if not ok:
              return Gst.FlowReturn.OK
          try:
              stride = info.size // h  # BGRx rows may be padded
              img = QImage(bytes(info.data), w, h, stride,
                           QImage.Format_RGB32).copy()
          finally:
              buf.unmap(info)
          self.frame.emit(img)
          return Gst.FlowReturn.OK

      def stop(self) -> None:
          if self._pipeline is not None:
              Gst = _gst()
              self._pipeline.set_state(Gst.State.NULL)
              self._pipeline = None
          self.recording = False
          self._cleanup()  # base class: closes fd + portal session


  # -- CLI runner (wondershot --scroll-spike) --------------------------------

  def run_scroll_spike(out_path: str | None = None) -> int:
      """Record the screen-cast while the user scrolls; write a stitched
      PNG on Ctrl+C. Spike harness, not shippable UI."""
      try:
          from .stitch import ScrollStitcher
      except ImportError:
          print("numpy missing — install the spike extra:\n"
                "  pip install -e '.[spike]'", file=sys.stderr)
          return 2

      from PySide6.QtGui import QGuiApplication
      from .settings import Settings
      from .capture import timestamp_name, unique_path

      app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
      app.setApplicationName("wondershot")
      app.setOrganizationName("wondershot")

      settings = Settings()
      out = out_path or unique_path(settings.library_dir,
                                    timestamp_name("ScrollCapture"))
      source = ScreenCastFrameSource(settings, fps=10)
      if not source.available():
          print("needs python3-gobject + GStreamer (Gst) bindings",
                file=sys.stderr)
          return 2
      stitcher = ScrollStitcher()
      # Direct connection (non-QObject slot): add_frame runs on the Gst
      # streaming thread — see module docstring for why that's OK here.
      source.frame.connect(stitcher.add_frame)
      source.failed.connect(lambda m: (print(f"FAILED: {m}",
                                             file=sys.stderr),
                                       app.exit(1)))
      source.started.connect(lambda: print(
          "Recording — pick the window in the portal dialog, scroll it "
          "top-to-bottom slowly, then press Ctrl+C here."))

      # Let Ctrl+C reach Python inside the Qt loop.
      _signal.signal(_signal.SIGINT, lambda *_: app.exit(0))
      pump = QTimer()
      pump.timeout.connect(lambda: None)
      pump.start(200)

      source.start()
      code = app.exec()
      source.stop()
      if code != 0:
          return code
      img = stitcher.result()
      if img.isNull():
          print("no frames captured — nothing to write", file=sys.stderr)
          return 1
      img.save(out, "PNG")
      print(f"stitched {stitcher.frames_used} frames "
            f"({stitcher.frames_dropped} dropped) -> {out} "
            f"({img.width()}x{img.height()})")
      return 0
  ```
- [x] Sanity-check it imports headless (this is the only automated check for this module — stated above, no unit tests for the GStreamer half):
  ```bash
  QT_QPA_PLATFORM=offscreen .venv/bin/python -c "import wondershot.scrollsource; print('import ok')"
  ```
  Expected: `import ok`.
- [x] Run the repo suite to confirm no collateral damage:
  ```bash
  .venv/bin/python -m pytest tests/ -q
  ```
- [x] Commit:
  ```bash
  git add wondershot/scrollsource.py
  git commit -m "WS-D: ScreenCastFrameSource (portal->appsink) + scroll-spike runner (spike quality, manual test)"
  ```

---

## Task 7: cli.py — hidden `--scroll-spike` flag + manual test

**Files:**
- Modify: `wondershot/cli.py` (argparser block lines 34-51; dispatch block lines 53-58)

This is glue to a live-compositor spike path; the dispatch line itself cannot be unit-tested headless without launching the portal — stated explicitly, manual test below instead.

Naming note: the spec suggests `--scroll-capture-spike`; this plan deliberately shortens it to `--scroll-spike` (hidden flag, spike-only, never user-facing — the spec's "hidden CLI flag or test harness" wording leaves the name open).

- [x] In `wondershot/cli.py`, after the `--selftest` argument (line 46-47):
  ```python
      parser.add_argument("--selftest", metavar="DIR",
                          help="render UI screenshots into DIR and exit (dev tool)")
  ```
  add:
  ```python
      parser.add_argument("--scroll-spike", action="store_true",
                          help=argparse.SUPPRESS)  # WS-D spike harness
  ```
- [x] In the same file, after the `--selftest` dispatch (lines 56-58):
  ```python
      if args.selftest:
          from .selftest import run_selftest
          return run_selftest(args.selftest)
  ```
  add:
  ```python
      if args.scroll_spike:
          from .scrollsource import run_scroll_spike
          return run_scroll_spike()
  ```
- [x] Quick headless check (flag must be hidden from --help but still parse):
  ```bash
  QT_QPA_PLATFORM=offscreen .venv/bin/wondershot --help | grep scroll-spike
  echo "exit=$? (expect 1: hidden flag absent from help)"
  ```
  Expected: no grep output, `exit=1`.
- [x] Run the repo suite:
  ```bash
  .venv/bin/python -m pytest tests/ -q
  ```
- [ ] **MANUAL TEST (the spike's success criterion — run on the Fedora/KDE box, in a real session, not offscreen):**
  ```bash
  .venv/bin/wondershot --scroll-spike
  ```
  1. The portal screen-share picker appears (or is skipped if a restore token exists from prior recordings — it remembers the whole screen; that's fine).
  2. Open a long page (e.g. a README in a browser), wait for "Recording —" to print.
  3. Scroll top-to-bottom slowly (one mouse-wheel notch every ~0.5 s).
  4. Ctrl+C in the terminal.
  5. Verify: a `ScrollCapture_*.png` lands in the library dir (default `~/Pictures/Screenshots`), is taller than the screen, and content reads continuously (small seams acceptable; note them in the ROADMAP findings, Task 9).
  - Known limits to record in findings: full-screen casts stitch the whole desktop (window-pick the browser for cleaner results); fast scrolling that exceeds `viewport_height - 64px` per frame at 10 fps breaks matching.
- [x] Commit:
  ```bash
  git add wondershot/cli.py
  git commit -m "WS-D: hidden --scroll-spike CLI flag (spike harness, manual test)"
  ```

---

## Task 8: spikes/inputcapture_probe.py — InputCapture portal probe

**Files:**
- Create: `spikes/inputcapture_probe.py` (standalone script, NOT part of the `wondershot` package — `spikes/` has no `__init__.py` and stays outside `[tool.setuptools.packages.find]`'s `wondershot*` include)

**Explicitly stated:** no unit tests — this is a standalone interactive D-Bus probe against a live portal/compositor. The automated check is import/`--help`-free: a syntax check. Manual run instructions below.

Defensive posture (per `hotkey.py`'s KWin landmine: a mistyped D-Bus call once aborted the compositor): the probe only ever calls `org.freedesktop.portal.Desktop` (the xdg-desktop-portal daemon — a separate process from KWin, so a bad call kills a request, not the session), every option is an explicitly typed `GLib.Variant` (portals demand uint32-typed options; that's why this uses Gio, not QtDBus), every call has a finite timeout and is wrapped in `try/except GLib.Error`, and the script never registers anything with KGlobalAccel.

- [x] Create `spikes/inputcapture_probe.py`:
  ```python
  #!/usr/bin/env python3
  """WS-D spike: probe org.freedesktop.portal.InputCapture on this box.

  Answers: is the InputCapture portal present on Fedora/KDE, and can we
  get far enough (session -> zones -> EIS fd) to observe pointer button
  events? Findings decide whether step capture ships Linux-first or
  Windows-first (see ROADMAP.md "WS-D capture-engine spike findings").

  Standalone: run with the SYSTEM python (needs gi):
      python3 spikes/inputcapture_probe.py

  Defensive D-Bus posture (see wondershot/hotkey.py landmine history):
  talks only to org.freedesktop.portal.Desktop, explicit GLib.Variant
  types everywhere, finite timeouts, GLib.Error caught per step.
  """
  from __future__ import annotations

  import os
  import random
  import select
  import sys

  try:
      import gi
      from gi.repository import Gio, GLib
  except ImportError:
      print("FINDING: python3-gobject (gi) not importable — cannot probe")
      sys.exit(2)

  BUS = "org.freedesktop.portal.Desktop"
  PATH = "/org/freedesktop/portal/desktop"
  IFACE = "org.freedesktop.portal.InputCapture"
  TIMEOUT_MS = 5000

  # InputCapture capabilities bitmask (portal spec)
  CAP_KEYBOARD, CAP_POINTER, CAP_TOUCH = 1, 2, 4


  def finding(msg: str) -> None:
      print(f"FINDING: {msg}", flush=True)


  class Probe:
      def __init__(self):
          self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
          self.loop = GLib.MainLoop()
          self.session: str | None = None
          self.zone_set: int | None = None

      # -- plumbing (mirrors wondershot/record.py) ----------------------

      def _token(self) -> str:
          return f"wsprobe{random.randint(0, 2**31)}"

      def _request_path(self, token: str) -> str:
          sender = self.conn.get_unique_name()[1:].replace(".", "_")
          return (f"/org/freedesktop/portal/desktop/request/"
                  f"{sender}/{token}")

      def _call_with_response(self, method: str, variant: GLib.Variant,
                              token: str) -> dict | None:
          """Synchronous request/Response: subscribe first, call, spin
          a main loop until the Response signal or timeout."""
          result: dict = {}

          def on_response(_c, _s, _p, _i, _m, params):
              code, results = params.unpack()
              result["code"] = code
              result["results"] = results
              self.loop.quit()

          sub = self.conn.signal_subscribe(
              BUS, "org.freedesktop.portal.Request", "Response",
              self._request_path(token), None,
              Gio.DBusSignalFlags.NONE, on_response)
          try:
              self.conn.call_sync(BUS, PATH, IFACE, method, variant,
                                  None, Gio.DBusCallFlags.NONE,
                                  TIMEOUT_MS, None)
          except GLib.Error as e:
              self.conn.signal_unsubscribe(sub)
              finding(f"{method} call failed: {e.message}")
              return None
          # Track the timeout source: if the Response arrives first, a
          # stale timeout would fire into the NEXT call's loop.run()
          # and quit it early. (On timeout the source self-removes by
          # returning None/False from loop.quit.)
          timeout_id = GLib.timeout_add(TIMEOUT_MS, self.loop.quit)
          self.loop.run()
          if "code" in result:
              GLib.Source.remove(timeout_id)
          self.conn.signal_unsubscribe(sub)
          if "code" not in result:
              finding(f"{method}: no Response within {TIMEOUT_MS}ms")
              return None
          if result["code"] != 0:
              finding(f"{method}: Response code {result['code']} "
                      "(1=cancelled, 2=other)")
              return None
          return result["results"]

      def _get_property(self, name: str):
          try:
              v = self.conn.call_sync(
                  BUS, PATH, "org.freedesktop.DBus.Properties", "Get",
                  GLib.Variant("(ss)", (IFACE, name)),
                  None, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
              return v.unpack()[0]
          except GLib.Error as e:
              finding(f"property {name} unavailable: {e.message}")
              return None

      # -- probe steps ---------------------------------------------------

      def check_available(self) -> bool:
          version = self._get_property("version")
          if version is None:
              finding("InputCapture portal NOT available on this box")
              return False
          finding(f"InputCapture portal present, version={version}")
          caps = self._get_property("SupportedCapabilities")
          if caps is not None:
              names = [n for bit, n in ((CAP_KEYBOARD, "KEYBOARD"),
                                        (CAP_POINTER, "POINTER"),
                                        (CAP_TOUCH, "TOUCHSCREEN"))
                       if caps & bit]
              finding(f"SupportedCapabilities={caps} ({'|'.join(names)})")
          return True

      def create_session(self) -> bool:
          token, stoken = self._token(), self._token()
          results = self._call_with_response(
              "CreateSession",
              GLib.Variant("(sa{sv})", ("", {
                  "handle_token": GLib.Variant("s", token),
                  "session_handle_token": GLib.Variant("s", stoken),
                  "capabilities": GLib.Variant(
                      "u", CAP_POINTER | CAP_KEYBOARD),
              })), token)
          if results is None:
              finding("CreateSession FAILED — cannot probe further")
              return False
          self.session = results.get("session_handle", "")
          caps = results.get("capabilities")
          finding(f"CreateSession OK (granted capabilities={caps})")
          return bool(self.session)

      def get_zones(self) -> bool:
          token = self._token()
          results = self._call_with_response(
              "GetZones",
              # Signature is (o session_handle, a{sv} options) — no
              # parent_window string, unlike CreateSession.
              GLib.Variant("(oa{sv})", (self.session, {
                  "handle_token": GLib.Variant("s", token)})), token)
          if results is None:
              finding("GetZones FAILED")
              return False
          zones = results.get("zones") or []
          self.zone_set = results.get("zone_set")
          finding(f"GetZones OK: zones={zones} zone_set={self.zone_set}")
          return bool(zones)

      def connect_eis(self) -> int:
          try:
              reply, fd_list = self.conn.call_with_unix_fd_list_sync(
                  BUS, PATH, IFACE, "ConnectToEIS",
                  GLib.Variant("(oa{sv})", (self.session, {})),
                  None, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None, None)
              fd = fd_list.get(reply.unpack()[0])
              finding(f"ConnectToEIS OK: got EIS fd={fd}")
              return fd
          except GLib.Error as e:
              finding(f"ConnectToEIS FAILED: {e.message}")
              return -1

      def observe_events(self, fd: int) -> None:
          """Try to see pointer-button events on the EIS fd."""
          try:
              import snegg.ei  # python libei bindings, if installed
          except ImportError:
              finding("no python libei bindings (snegg) installed — "
                      "cannot speak the EI protocol from Python here")
              # Honest fallback: EI requires a client handshake, so a
              # raw read should yield nothing; prove/record that.
              os.set_blocking(fd, False)
              r, _, _ = select.select([fd], [], [], 3.0)
              if r:
                  data = os.read(fd, 4096)
                  finding(f"raw read got {len(data)} bytes without a "
                          "handshake (unexpected — investigate)")
              else:
                  finding("raw fd silent without EI handshake (expected); "
                          "event observation needs libei (C) or snegg — "
                          "fd plumbing itself works")
              return
          finding("snegg (python libei) present — attempting real "
                  "event observation for 10s; CLICK SOME BUTTONS NOW")
          ctx = snegg.ei.Receiver.create_for_fd(fd=fd, name="ws-probe")
          deadline = GLib.get_monotonic_time() + 10_000_000
          saw = 0
          while GLib.get_monotonic_time() < deadline:
              r, _, _ = select.select([ctx.fd], [], [], 0.5)
              if not r:
                  continue
              ctx.dispatch()
              for ev in ctx.events:
                  if ev.event_type == snegg.ei.EventType.BUTTON_BUTTON:
                      saw += 1
                      finding(f"pointer BUTTON event observed: "
                              f"button={ev.button} state={ev.is_press}")
          finding(f"observed {saw} button events"
                  if saw else "no button events observed (capture may "
                  "need Enable + pointer barriers + activation)")

      def close(self) -> None:
          if self.session:
              try:
                  self.conn.call_sync(
                      BUS, self.session,
                      "org.freedesktop.portal.Session", "Close",
                      None, None, Gio.DBusCallFlags.NONE, 1000, None)
              except GLib.Error:
                  pass


  def main() -> int:
      print("== InputCapture portal probe (WS-D spike) ==")
      print("Safe-by-construction: portal daemon only, typed variants,")
      print("finite timeouts. See wondershot/hotkey.py for why.\n")
      try:
          probe = Probe()
      except GLib.Error as e:
          finding(f"session bus unavailable: {e.message}")
          return 2
      try:
          if not probe.check_available():
              return 1
          if not probe.create_session():
              return 1
          probe.get_zones()
          fd = probe.connect_eis()
          if fd >= 0:
              probe.observe_events(fd)
              os.close(fd)
          return 0
      finally:
          probe.close()
          finding("probe done — copy FINDING lines into ROADMAP.md "
                  "(WS-D findings section)")


  if __name__ == "__main__":
      sys.exit(main())
  ```
- [x] Automated check (syntax only — stated above, no unit tests for this standalone probe):
  ```bash
  .venv/bin/python -m py_compile spikes/inputcapture_probe.py && echo "compiles"
  ```
  Expected: `compiles`.
- [ ] **MANUAL TEST (live KDE session):**
  ```bash
  python3 spikes/inputcapture_probe.py
  ```
  Expected output shapes (any of these is a valid spike result — record whichever happens):
  - `FINDING: InputCapture portal NOT available on this box` → step capture is Windows-first; done.
  - Portal present but `CreateSession FAILED` / response code 2 → present-but-nonfunctional; record the code.
  - Full chain to `ConnectToEIS OK` + the snegg/raw-read finding → record how far event observation got.
  - If a permission dialog appears, accept it. The probe never touches KWin directly; worst case is a failed portal request.
- [x] Commit:
  ```bash
  git add spikes/inputcapture_probe.py
  git commit -m "WS-D: standalone InputCapture portal probe (manual run; defensive D-Bus)"
  ```

---

## Task 9: ROADMAP.md findings template + final verification

**Files:**
- Modify: `ROADMAP.md` (append at end of file, after the "Platform landmines" section)

- [x] Append the following to the END of `ROADMAP.md` (the executor fills the blanks after performing the manual tests in Tasks 7 and 8 on the Fedora/KDE box):
  ```markdown

  ## WS-D capture-engine spike findings (2026-06-06)

  _Template appended by the WS-D plan; fill in after running the two
  spikes on the Fedora/KDE box. These results gate scroll capture's
  productization and step capture's platform order (Linux-first vs
  Windows-first as part of WS-E)._

  ### Scroll capture (`wondershot --scroll-spike`, stitch.py)

  - Stitched tall PNG produced from a real scrolled window: YES / NO
  - Output file + dimensions: ____
  - Frames used / dropped (printed at exit): ____ / ____
  - Seam quality (duplicated or missing rows? where?): ____
  - Fixed header/footer heuristic behavior on a real page: ____
  - Scroll speed limits observed (when did matching break?): ____
  - Verdict: stitcher core PRODUCTIZABLE / NEEDS algorithm work: ____

  ### InputCapture portal (`spikes/inputcapture_probe.py`)

  - Portal interface present: YES / NO — version: ____
  - SupportedCapabilities: ____
  - CreateSession: OK / FAILED (code/message): ____
  - GetZones: ____
  - ConnectToEIS fd obtained: YES / NO
  - Pointer button events observed: YES / NO — via (snegg / raw / n.a.): ____
  - Blocking gaps (e.g. need libei bindings, need Enable+barriers): ____
  - **Verdict: step capture LINUX-VIABLE / WINDOWS-FIRST**: ____
  ```
- [x] Final full verification:
  ```bash
  .venv/bin/python -m pytest tests/ -q
  QT_QPA_PLATFORM=offscreen .venv/bin/python -c "import wondershot.stitch, wondershot.scrollsource, wondershot.cli; print('imports ok')"
  ```
  Expected: full suite green (including all of `tests/test_stitch.py`), `imports ok`.
- [x] Commit:
  ```bash
  git add ROADMAP.md
  git commit -m "WS-D: append spike findings template to ROADMAP (executor fills after manual runs)"
  ```
