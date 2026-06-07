# Track 3c: Video Backlog — Blur Strength, True Blur Preview, GIF Options

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Three video-pane features per the spec Addendum 2 (`docs/superpowers/specs/2026-06-06-snagit-parity-design.md`, "Track 3c: Video backlog"). (1) **Blur strength setting** — a spinbox in the blur UI mapped to the `boxblur` radius `build_blur_filter` already accepts (`blur: int = 14` parameter, currently never passed by the UI), with a persisted default in settings. (2) **True blur preview** — the frost rectangles painted while editing show an actual cheap box-blur of the covered region of the frozen frame (QImage-only approximation; honestly commented as preview-only — the ffmpeg render stays the source of truth). (3) **GIF options** — fps / max-width / time-range controls on the GIF convert flow, reusing the exact trim pattern (a checkable mode button creating a single span the `RangeBar` timeline edits), with persisted defaults.

**Architecture:** All feature code lives in `wondershot/video.py` plus three QSettings properties in `wondershot/settings.py`. New pure functions: `preview_blur(img, radius)` (downscale/upscale QImage approximation of boxblur) and `build_gif_args(src, out, fps, max_width, start_s, end_s)` (mirrors `build_trim_args`'s input-seek pattern). The trim feature already proved the "single span on the timeline" pattern via `VideoPane.trim` + `spans()`; GIF range generalizes it with a `single_span()` helper (`trim or gif_range`) so `RangeBar` keeps exactly one code path — this is the only refactor touching shipped trim/blur code, and it is mechanical (replace `self.pane.trim is not None` checks). ALL ffmpeg invocations stay on the existing seam: async renders via `QProcess` started with `ffmpegutil.ffmpeg_path()`, capability probes via `ffmpegutil.run_ffmpeg` — no new direct `ffmpeg` strings anywhere.

**Regression posture (READ FIRST):** trim, blur, and frame-grab shipped this week and MUST keep working. Rules: `build_blur_filter`'s default stays `blur=14` (existing tests assert `boxblur=14`); `build_trim_args` / `build_frame_grab_args` / `trim_output_name` / `frame_output_name` are untouched; the `single_span()` refactor changes no behavior when `gif_range is None` (it returns `self.trim`, exactly what every call site checked before). The full suite (186 tests on main) must stay green after every task. Also read the ROADMAP "Platform landmines" section (`ROADMAP.md` ~line 220) — relevant here: the video lives in a native Wayland subsurface above all widget painting (why the overlay paints the frozen frame itself), and libx264 can't enter WebM containers (why blur renders to mp4 — do not "simplify" that).

**Tech Stack:** Python ≥3.10, PySide6 only (no new runtime deps; preview blur is pure QImage ops — no numpy at runtime). Tests: pytest, headless (`QT_QPA_PLATFORM=offscreen`), fake `QProcess` — ffmpeg is never actually executed by tests.

**Execution environment:** Work in a git worktree branched from `main` (e.g. `git worktree add ../grabbit-wt/track-3c -b track-3c main`). Venv recipe from the worktree root:

```bash
python -m venv .venv && .venv/bin/pip install -e ".[spike]" pytest
```

(The `spike` extra pulls numpy, which is needed for test *collection* — `tests/test_stitch.py` imports it.) Full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` — 186 passing on main at start. Do NOT git commit to main and do NOT push; commit on the worktree branch per task. The orchestrator merges.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `wondershot/settings.py` | Modify (append after `quick_bar_timeout` setter, line 298, before the AI section) | `video_blur_strength` (int, default 14), `gif_fps` (int, default 12), `gif_max_width` (int, default 720) — **cross-track caution**: settings.py is shared; track 3a (recording polish) likely adds its countdown setting here too. Confine this track's edit to the single new `# -- video tools` block at that one insertion point and touch nothing else in the file |
| `wondershot/video.py` | Modify | strength spinbox + plumb into `build_blur_filter`; `preview_blur()` + overlay paint integration; `build_gif_args()`; `single_span()` generalization; GIF mode (checkable button, fps/width spins, Save GIF button, `gif_range` span) |
| `tests/test_settings_video.py` | Create | round-trips + defaults for the three new settings |
| `tests/test_video_pane.py` | Create | headless `VideoPane` tests: strength spin defaults/persistence, strength reaches the filter graph, GIF mode state machine, GIF args from pane state, persisted GIF options |
| `tests/test_video_preview.py` | Create | `preview_blur` pure-function tests + overlay paint integration (rendered pixels) |
| `tests/test_video_filter.py` | Modify (append) | `boxblur=N` strength characterization; `build_gif_args` variants |
| `ROADMAP.md` | Modify (lines 192–194, the "Video backlog" backlog bullet) | mark blur strength / GIF options / true preview done — **cross-track caution**: parallel Batch-3 tracks (3a record/app, 3b sidecar) also edit ROADMAP.md; keep the edit confined to that one bullet so merge conflicts stay trivial |

**Gotchas for someone new to this codebase:**

- **Headless boilerplate**: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` BEFORE any Qt import, then a session-scoped `qapp` fixture (`QApplication.instance() or QApplication([])`). Pattern: `tests/test_quickbar.py` lines 1–15.
- **Never instantiate `Settings()` in tests** — its `__init__` opens the real user config and runs a migration. Use `Settings.__new__(Settings)` + temp `QSettings` (pattern: `tests/test_settings_quickbar.py::make_settings`).
- `QSettings.value()` returns strings — int properties must wrap `int(...)`. Copy the `quick_bar_timeout` idiom exactly (settings.py lines 291–298).
- `VideoPane(settings)` constructs fine offscreen (verified: `QMediaPlayer` initializes with the FFmpeg backend, prints one harmless log line). With no media loaded, `player.duration()` is 0 — `_gif_mode` already clamps the span end to `max(dur, 0.1)` exactly like `_trim_mode` does (video.py line 705).
- **Visibility in offscreen tests**: child widgets of a never-shown `VideoPane` report `isVisible() == False` regardless of `setVisible(True)`. Assert with `isHidden()` (False after `setVisible(True)`, True after `hide()`).
- `_apply_blurs` / `_convert_gif` resolve `build_blur_filter` / `QProcess` / `ffmpegutil.ffmpeg_path` through module globals at call time, so `monkeypatch.setattr(video, "QProcess", FakeProc)` etc. intercepts them — tests never spawn ffmpeg. One trap: `_apply_blurs` ALSO calls `pick_encoder()` (video.py line 126), which shells out via `ffmpegutil.run_ffmpeg` (`subprocess.run`, not `QProcess`) and caches in the module-global `_encoder_cache` — patching `QProcess` does not intercept it. `patch_proc` stubs `video.pick_encoder` for exactly this reason; keep that stub in any new test that reaches `_apply_blurs`.
- The overlay paints only in `frozen_mode()` and maps coords via `_video_size()` (the player's sink). In the paint integration test, override BOTH on the instances: `pane.frozen_mode = lambda: True`, `pane.last_frame_image = lambda: img`, `overlay._video_size = lambda: QSize(...)` — plain attribute assignment shadows the methods.
- Frame pixels and `Redaction.rect` are both in **video pixel coordinates** (the `QVideoFrame.toImage()` result is native frame size) — that's why `frame_img.copy(red.rect ∩ frame rect)` is the right crop for the preview.
- `Redaction` is a plain dataclass and always truthy — `single_span()` must use `is not None` chaining, never `or`.
- The mutual-exclusion convention between modes is **uncheck the other buttons inside the toggled handler** (`_blur_mode` unchecks trim, `_trim_mode` unchecks blur — video.py lines 686, 702). GIF mode joins that convention in both directions; the `toggled` signals fire synchronously so the unchecked mode tears itself down before the new one builds up.
- Renders go to `self._render_temp(out)` (a hidden `.rendering/` dir) and `shutil.move` to the library on success — keep that for GIF (it already does).
- Run all commands from the worktree root.

**What is explicitly NOT headless-testable (GUI-only glue, no failing-test step, justified per item):** the live look of the blurred preview on a real compositor frame (the *pixel pipeline* IS tested via `overlay.render()` in Task 3 — what's untestable is only the Wayland subsurface hide/show interplay, a shipped behavior we don't touch); spinbox/button layout aesthetics; `QIcon.fromTheme` icons. Everything behavioral — settings, filter graphs, args builders, mode state machine, what reaches `QProcess.start` — IS tested headless. These GUI leftovers go on the consolidated end-of-batch desktop checklist (Task 6 lists the entries to add).

---

## Task 1: Persisted video-tool defaults in settings

**Files:**
- Modify: `wondershot/settings.py` (insert after line 298, the `quick_bar_timeout` setter, before the `# -- AI` section comment at line 300)
- Create: `tests/test_settings_video.py`

- [x] **Write the failing test** — create `tests/test_settings_video.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_video_tool_defaults(tmp_path):
    s = make_settings(tmp_path)
    assert s.video_blur_strength == 14
    assert s.gif_fps == 12
    assert s.gif_max_width == 720


def test_video_tool_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.video_blur_strength = 30
    s.gif_fps = 20
    s.gif_max_width = 480
    assert s.video_blur_strength == 30
    assert s.gif_fps == 20
    assert s.gif_max_width == 480


def test_video_tool_values_survive_string_storage(tmp_path):
    # QSettings round-trips ints as strings; the properties must coerce.
    s = make_settings(tmp_path)
    s._s.setValue("video_blur_strength", "25")
    s._s.setValue("gif_fps", "8")
    s._s.setValue("gif_max_width", "1280")
    assert s.video_blur_strength == 25
    assert s.gif_fps == 8
    assert s.gif_max_width == 1280
```

- [x] **Run it, expect failure:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_video.py -q` → 3 failures, `AttributeError: 'Settings' object has no attribute 'video_blur_strength'`.

- [x] **Implement** — in `wondershot/settings.py`, insert between the `quick_bar_timeout` setter (line 298) and the `# -- AI (OpenAI-compatible chat endpoint)` comment (line 300):

```python
    # -- video tools (persisted defaults) ------------------------------------

    @property
    def video_blur_strength(self) -> int:
        """boxblur radius for the video blur render (and its preview)."""
        return int(self._s.value("video_blur_strength", 14))

    @video_blur_strength.setter
    def video_blur_strength(self, value: int) -> None:
        self._s.setValue("video_blur_strength", int(value))

    @property
    def gif_fps(self) -> int:
        return int(self._s.value("gif_fps", 12))

    @gif_fps.setter
    def gif_fps(self, value: int) -> None:
        self._s.setValue("gif_fps", int(value))

    @property
    def gif_max_width(self) -> int:
        """GIF output is scaled down to at most this width (never up)."""
        return int(self._s.value("gif_max_width", 720))

    @gif_max_width.setter
    def gif_max_width(self, value: int) -> None:
        self._s.setValue("gif_max_width", int(value))
```

- [x] **Run:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_video.py -q` → 3 passed.
- [x] **Full suite:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` → 189 passed.
- [x] **Commit:** `git add wondershot/settings.py tests/test_settings_video.py && git commit -m "Settings: persisted video-tool defaults (blur strength, GIF fps/width)"`

---

## Task 2: Blur strength control wired into the blur render

**Files:**
- Modify: `wondershot/video.py` (imports line 23–33; `VideoPane.__init__` after the `apply_btn` block line 494–497; `controls` layout line 535; `_rebuild_rows` line 760; `_set_rendering` line 868; `_apply_blurs` line 890)
- Modify: `tests/test_video_filter.py` (append)
- Create: `tests/test_video_pane.py`

- [x] **Write the characterization test** for the existing `blur` parameter (this test passes immediately — it pins the contract the UI is about to depend on; the failing tests come next). Append to `tests/test_video_filter.py`:

```python
def test_blur_strength_parameter():
    graph, _ = build_blur_filter(
        [Redaction(QRect(0, 0, 100, 100), 0.0, 1.0)],
        blur=30, video_w=640, video_h=360)
    assert "boxblur=30" in graph
    assert "boxblur=14" not in graph
```

- [x] **Write the failing pane tests** — create `tests/test_video_pane.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    s.library_dir = str(tmp_path / "lib")
    return s


def make_pane(qapp, tmp_path, **prefs):
    settings = make_settings(tmp_path)
    for key, val in prefs.items():
        setattr(settings, key, val)
    from wondershot.video import VideoPane
    return VideoPane(settings), settings


class FakeSignal:
    def connect(self, *_):
        pass


class FakeProc:
    """Stands in for QProcess so no ffmpeg is ever spawned."""
    last = None

    def __init__(self, parent=None):
        self.finished = FakeSignal()

    def start(self, prog, args):
        FakeProc.last = (prog, list(args))


def patch_proc(monkeypatch):
    import wondershot.video as video
    FakeProc.last = None
    monkeypatch.setattr(video, "QProcess", FakeProc)
    monkeypatch.setattr(video.ffmpegutil, "ffmpeg_path",
                        lambda: "/usr/bin/ffmpeg")
    # _apply_blurs calls pick_encoder(), which probes via
    # ffmpegutil.run_ffmpeg (a real subprocess.run) — stub it so tests
    # never execute ffmpeg.
    monkeypatch.setattr(video, "pick_encoder", lambda: "libx264")
    return video


def test_blur_strength_spin_defaults(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.blur_strength_spin.value() == 14


def test_blur_strength_spin_reads_saved_default(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path, video_blur_strength=22)
    assert pane.blur_strength_spin.value() == 22


def test_blur_strength_spin_persists(qapp, tmp_path):
    pane, settings = make_pane(qapp, tmp_path)
    pane.blur_strength_spin.setValue(30)
    assert settings.video_blur_strength == 30


def test_blur_strength_controls_track_apply_visibility(qapp, tmp_path):
    import wondershot.video as video
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.blur_strength_spin.isHidden()
    pane.redactions.append(video.Redaction(QRect(0, 0, 50, 50), 0.0, 2.0))
    pane._rebuild_rows()
    assert not pane.blur_strength_spin.isHidden()
    pane.redactions.clear()
    pane._rebuild_rows()
    assert pane.blur_strength_spin.isHidden()


def test_apply_blurs_passes_strength_to_filter(qapp, tmp_path, monkeypatch):
    video = patch_proc(monkeypatch)
    pane, _ = make_pane(qapp, tmp_path)
    pane.path = "/tmp/fake.mp4"
    pane.redactions.append(video.Redaction(QRect(0, 0, 100, 100), 0.0, 2.0))
    pane.blur_strength_spin.setValue(27)
    captured = {}

    def fake_filter(reds, blur=14, video_w=0, video_h=0):
        captured["blur"] = blur
        return "[0:v]null[vout]", "vout"

    monkeypatch.setattr(video, "build_blur_filter", fake_filter)
    pane._apply_blurs()
    assert captured["blur"] == 27
    assert FakeProc.last is not None          # render was started
    assert FakeProc.last[0] == "/usr/bin/ffmpeg"  # via ffmpegutil seam
```

- [x] **Run, expect failure:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_pane.py tests/test_video_filter.py -q` → the 5 pane tests fail (`AttributeError: ... no attribute 'blur_strength_spin'`); all filter tests including the new characterization pass.

- [x] **Implement** — four edits in `wondershot/video.py`:

  1. Add `QSpinBox` to the `QtWidgets` import block (line 23–33), keeping alphabetical order:

```python
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
```

  2. In `VideoPane.__init__`, directly after the `apply_btn` block (after `self.apply_btn.hide()`, line 497), add:

```python
        self.blur_strength_label = QLabel("Strength", self)
        self.blur_strength_label.hide()
        self.blur_strength_spin = QSpinBox(self)
        self.blur_strength_spin.setRange(2, 60)
        self.blur_strength_spin.setToolTip(
            "Blur radius used for the render — the boxes show an "
            "approximate live preview (the rendered blur is the "
            "ffmpeg boxblur, which can differ slightly)")
        self.blur_strength_spin.setValue(settings.video_blur_strength)
        self.blur_strength_spin.valueChanged.connect(
            self._blur_strength_changed)
        self.blur_strength_spin.hide()
```

  3. In the `controls` layout (line 528–540), insert after `controls.addWidget(self.apply_btn)`:

```python
        controls.addWidget(self.blur_strength_label)
        controls.addWidget(self.blur_strength_spin)
```

  4. Add the handler (place it right after `_blur_mode`, line 694) and wire visibility/enabling:

```python
    def _blur_strength_changed(self, v: int) -> None:
        self.settings.video_blur_strength = v
        self.overlay.update()  # the preview (Task 3) repaints live
```

  In `_rebuild_rows` (line 760), after `self.apply_btn.setVisible(has)` add:

```python
        self.blur_strength_label.setVisible(has)
        self.blur_strength_spin.setVisible(has)
```

  In `_set_rendering` (line 868), after `self.apply_btn.setEnabled(not on)` add:

```python
        self.blur_strength_spin.setEnabled(not on)
```

  In `_apply_blurs` (line 890), pass the strength:

```python
        graph, out_label = build_blur_filter(
            self.redactions,
            blur=self.blur_strength_spin.value(),
            video_w=vs.width() if vs else 0,
            video_h=vs.height() if vs else 0)
```

- [x] **Run:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_pane.py tests/test_video_filter.py -q` → all pass (5 pane + 15 filter: 14 existing + the characterization test).
- [x] **Full suite:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` → 195 passed.
- [x] **Commit:** `git add wondershot/video.py tests/test_video_pane.py tests/test_video_filter.py && git commit -m "Video: blur strength control wired into the boxblur render"`

---

## Task 3: True blur preview in the frost rectangles

**Files:**
- Modify: `wondershot/video.py` (new module-level `preview_blur` after `build_blur_filter`, line 73; `RedactOverlay.paintEvent` frost block, lines 258–262)
- Create: `tests/test_video_preview.py`

- [ ] **Write the failing tests** — create `tests/test_video_preview.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QSize, QSettings
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def edge_image(w=64, h=64):
    """Left half black, right half white — a hard vertical edge at x=w/2."""
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("black"))
    p = QPainter(img)
    p.fillRect(w // 2, 0, w // 2, h, QColor("white"))
    p.end()
    return img


def test_preview_blur_preserves_size(qapp):
    from wondershot.video import preview_blur
    img = QImage(64, 48, QImage.Format_RGB32)
    img.fill(QColor("red"))
    out = preview_blur(img, 14)
    assert out.size() == QSize(64, 48)


def test_preview_blur_softens_hard_edge(qapp):
    from wondershot.video import preview_blur
    out = preview_blur(edge_image(), 14)
    edge = out.pixelColor(32, 32)
    assert 10 < edge.red() < 245   # intermediate gray, not pure black/white


def test_preview_blur_keeps_flat_color_flat(qapp):
    from wondershot.video import preview_blur
    img = QImage(40, 40, QImage.Format_RGB32)
    img.fill(QColor(200, 60, 30))
    out = preview_blur(img, 20)
    c = out.pixelColor(20, 20)
    assert abs(c.red() - 200) <= 2
    assert abs(c.green() - 60) <= 2
    assert abs(c.blue() - 30) <= 2


def test_preview_blur_radius_zero_is_identity(qapp):
    from wondershot.video import preview_blur
    img = QImage(16, 16, QImage.Format_RGB32)
    img.fill(QColor("blue"))
    assert preview_blur(img, 0) is img


def test_preview_blur_tiny_image_is_identity(qapp):
    from wondershot.video import preview_blur
    img = QImage(1, 1, QImage.Format_RGB32)
    img.fill(QColor("blue"))
    assert preview_blur(img, 14) is img


def test_overlay_paints_blurred_region(qapp, tmp_path):
    """Integration: the frost rect actually shows blurred frame pixels."""
    import wondershot.video as video
    from wondershot.settings import Settings
    settings = Settings.__new__(Settings)
    settings._s = QSettings(str(tmp_path / "t.ini"), QSettings.IniFormat)
    settings.library_dir = str(tmp_path / "lib")
    pane = video.VideoPane(settings)

    frame = edge_image(64, 64)
    pane.frozen_mode = lambda: True              # instance overrides:
    pane.last_frame_image = lambda: frame        # bypass the real player
    pane.overlay._video_size = lambda: QSize(64, 64)
    pane.overlay.resize(64, 64)
    # span includes t=0 (player position is 0 with no media)
    pane.redactions.append(
        video.Redaction(QRect(8, 8, 48, 48), 0.0, 5.0))

    target = QImage(64, 64, QImage.Format_RGB32)
    target.fill(QColor("green"))
    pane.overlay.render(target)

    # Inside the redaction at the black/white edge: blurred gray.
    inside = target.pixelColor(32, 32)
    assert 10 < inside.red() < 245
    # Outside the redaction the raw frame shows through: pure-ish white.
    outside = target.pixelColor(60, 4)
    assert outside.red() > 245
```

- [ ] **Run, expect failure:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_preview.py -q` → `ImportError: cannot import name 'preview_blur'` (5 tests) and the integration test fails (frost fill paints translucent white over green, not blurred frame pixels — `inside.red()` lands near 255-blend, possibly passing by luck; the `preview_blur` import failures are the definitive red).

- [ ] **Implement** — two edits in `wondershot/video.py`:

  1. Add the module-level function directly after `build_blur_filter` (after line 72, before `build_frame_grab_args`):

```python
def preview_blur(img, radius: int):
    """Preview-only approximation of ffmpeg's boxblur for the overlay.

    Downscale by a radius-derived factor with bilinear filtering, then
    scale back up — O(pixels), pure QImage, no deps. Visually close to
    boxblur=radius but NOT the same kernel: the ffmpeg render pass is
    the source of truth, this only previews it. Returns the input
    unchanged when blurring is meaningless (radius<=0, tiny/null image).
    """
    if radius <= 0 or img.isNull() or img.width() < 2 or img.height() < 2:
        return img
    factor = max(2, int(radius))
    w = max(1, img.width() // factor)
    h = max(1, img.height() // factor)
    small = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(img.width(), img.height(),
                        Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
```

  2. In `RedactOverlay.paintEvent`, replace the frost-fill block (lines 258–262):

```python
            r = self.video_to_widget(red.rect)
            color = QColor(PALETTE[i % len(PALETTE)])
```
```python
            p.setPen(QPen(color, 2, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawRect(r)
```

  with a real blurred patch (frame pixels are in the same video-pixel space as `red.rect`, so a straight `copy` of the intersection is the covered region):

```python
            r = self.video_to_widget(red.rect)
            color = QColor(PALETTE[i % len(PALETTE)])
            region = red.rect.intersected(frame_img.rect())
            if not region.isEmpty():
                # Target the mapped *intersection*, not r: if red.rect ever
                # exceeds the frame (size mismatch edge case), drawing the
                # cropped copy into the full r would stretch it.
                p.drawImage(self.video_to_widget(region), preview_blur(
                    frame_img.copy(region),
                    self.pane.blur_strength_spin.value()))
            p.setPen(QPen(color, 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
```

  (The number badge and the rest of `paintEvent` are unchanged. `_blur_strength_changed` from Task 2 already calls `self.overlay.update()`, so dragging the spinbox re-blurs the preview live.)

- [ ] **Run:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_preview.py -q` → 6 passed.
- [ ] **Full suite:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` → 201 passed.
- [ ] **Commit:** `git add wondershot/video.py tests/test_video_preview.py && git commit -m "Video: frost rectangles preview the actual blur (QImage approximation)"`

---

## Task 4: `build_gif_args` pure builder

**Files:**
- Modify: `wondershot/video.py` (new module-level function after `build_trim_args`, line 120)
- Modify: `tests/test_video_filter.py` (append)

- [ ] **Write the failing tests** — append to `tests/test_video_filter.py`:

```python
def test_gif_args_defaults():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/.rendering/in.gif")
    assert args[:3] == ["-y", "-i", "/l/in.mp4"]
    vf = args[args.index("-vf") + 1]
    assert vf.startswith("fps=12,scale='min(720,iw)':-1:flags=lanczos")
    assert "palettegen" in vf and "paletteuse" in vf
    assert args[-1] == "/l/.rendering/in.gif"


def test_gif_args_custom_fps_and_width():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/o.gif", fps=24, max_width=480)
    vf = args[args.index("-vf") + 1]
    assert "fps=24," in vf
    assert "min(480,iw)" in vf


def test_gif_args_range_is_input_seek():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/o.gif", start_s=1.5, end_s=4.0)
    i = args.index("-i")
    # -ss AND -to before -i: absolute source timestamps, same contract
    # as build_trim_args
    assert args[:i] == ["-y", "-ss", "1.500", "-to", "4.000"]


def test_gif_args_no_partial_range():
    from wondershot.video import build_gif_args
    args = build_gif_args("/l/in.mp4", "/l/o.gif", start_s=1.0, end_s=None)
    assert "-ss" not in args and "-to" not in args
```

- [ ] **Run, expect failure:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_filter.py -q` → 4 failures, `ImportError: cannot import name 'build_gif_args'`.

- [ ] **Implement** — in `wondershot/video.py`, insert after `build_trim_args` (after line 120, before the `_encoder_cache` line):

```python
def build_gif_args(src: str, out: str, fps: int = 12, max_width: int = 720,
                   start_s: float | None = None,
                   end_s: float | None = None) -> list[str]:
    """ffmpeg args for the two-pass palette GIF convert.

    -ss/-to are INPUT options (before -i): absolute source timestamps,
    the exact pattern build_trim_args uses. scale never upsizes
    (min(max_width, iw)) and lanczos keeps screen text legible. The
    range is applied only when both ends are given.
    """
    args = ["-y"]
    if start_s is not None and end_s is not None:
        args += ["-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}"]
    vf = (f"fps={fps},scale='min({max_width},iw)':-1:flags=lanczos,"
          "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse")
    return [*args, "-i", src, "-vf", vf, out]
```

- [ ] **Run:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_filter.py -q` → 19 passed (14 existing + 1 from Task 2 + these 4).
- [ ] **Full suite:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` → 205 passed.
- [ ] **Commit:** `git add wondershot/video.py tests/test_video_filter.py && git commit -m "Video: build_gif_args with fps/width/range (trim-style input seek)"`

---

## Task 5: GIF mode — fps/width/range controls on the convert flow

This task contains the one refactor of shipped code: generalizing the trim-only `self.pane.trim is not None` checks into `single_span()`. It is behavior-preserving when `gif_range is None` — re-run the FULL suite, not just the new tests, before committing.

**Files:**
- Modify: `wondershot/video.py` (`VideoPane.__init__` lines 451–452 & 516–519 & layout line 539; `load` line 575–582; `frozen_mode` line 624; `active_redaction` line 664; `set_active` line 671; `spans` line 679; `_blur_mode` line 684; `_trim_mode` line 696; `_clear_redactions` line 734; `refresh_overlays` line 745; `sync_active_row` line 765; `_position_changed` line 644; `RangeBar._hit` line 330; `RangeBar.paintEvent` lines 418 & 422; `_convert_gif`/`_gif_done` lines 945–976)
- Modify: `tests/test_video_pane.py` (append)

- [ ] **Write the failing tests** — append to `tests/test_video_pane.py`:

```python
def test_gif_mode_creates_full_range_span(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.gif_fps_spin.isHidden()
    pane.gif_btn.setChecked(True)
    assert pane.gif_range is not None
    assert pane.gif_range.start == 0.0
    assert pane.gif_range.end >= 0.1
    assert pane.spans() == [pane.gif_range]
    assert pane.single_span() is pane.gif_range
    assert not pane.gif_fps_spin.isHidden()
    assert not pane.gif_width_spin.isHidden()
    assert not pane.gif_apply_btn.isHidden()
    pane.gif_btn.setChecked(False)
    assert pane.gif_range is None
    assert pane.gif_fps_spin.isHidden()


def test_single_span_prefers_trim_and_preserves_trim_behavior(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    assert pane.single_span() is None
    pane.trim_btn.setChecked(True)
    assert pane.single_span() is pane.trim
    assert pane.spans() == [pane.trim]          # shipped trim contract
    assert pane.active_redaction() is pane.trim


def test_gif_and_trim_modes_are_mutually_exclusive(qapp, tmp_path):
    pane, _ = make_pane(qapp, tmp_path)
    pane.gif_btn.setChecked(True)
    pane.trim_btn.setChecked(True)
    assert pane.gif_range is None and pane.trim is not None
    assert not pane.gif_btn.isChecked()
    pane.gif_btn.setChecked(True)
    assert pane.trim is None and pane.gif_range is not None
    assert not pane.trim_btn.isChecked()


def test_gif_mode_blocked_by_pending_blurs(qapp, tmp_path):
    import wondershot.video as video
    pane, _ = make_pane(qapp, tmp_path)
    pane.redactions.append(video.Redaction(QRect(0, 0, 50, 50), 0.0, 2.0))
    pane.gif_btn.setChecked(True)
    assert pane.gif_range is None
    assert not pane.gif_btn.isChecked()


def test_gif_option_spins_default_and_persist(qapp, tmp_path):
    pane, settings = make_pane(qapp, tmp_path, gif_fps=18, gif_max_width=960)
    assert pane.gif_fps_spin.value() == 18
    assert pane.gif_width_spin.value() == 960
    pane.gif_fps_spin.setValue(15)
    pane.gif_width_spin.setValue(640)
    assert settings.gif_fps == 15
    assert settings.gif_max_width == 640


def test_convert_gif_uses_options_and_range(qapp, tmp_path, monkeypatch):
    patch_proc(monkeypatch)
    pane, _ = make_pane(qapp, tmp_path)
    pane.path = "/tmp/fake.mp4"
    pane.gif_btn.setChecked(True)
    pane.gif_fps_spin.setValue(20)
    pane.gif_width_spin.setValue(480)
    pane.gif_range.start, pane.gif_range.end = 1.0, 3.5
    pane._convert_gif()
    prog, args = FakeProc.last
    assert prog == "/usr/bin/ffmpeg"            # via ffmpegutil seam
    assert args[args.index("-ss") + 1] == "1.000"
    assert args[args.index("-to") + 1] == "3.500"
    vf = args[args.index("-vf") + 1]
    assert "fps=20," in vf and "min(480,iw)" in vf


def test_convert_gif_full_range_omits_seek(qapp, tmp_path, monkeypatch):
    patch_proc(monkeypatch)
    pane, _ = make_pane(qapp, tmp_path)
    pane.path = "/tmp/fake.mp4"
    pane.gif_btn.setChecked(True)   # untouched span == whole video
    pane._convert_gif()
    _, args = FakeProc.last
    assert "-ss" not in args and "-to" not in args
```

- [ ] **Run, expect failure:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_pane.py -q` → the 7 new tests fail (`AttributeError: ... no attribute 'gif_fps_spin'` / `'single_span'`); the Task-2 tests still pass.

- [ ] **Implement** — edits in `wondershot/video.py`:

  1. **State field** — in `VideoPane.__init__`, after `self.trim: Redaction | None = None` (line 451) add:

```python
        self.gif_range: Redaction | None = None  # rect unused; start/end = GIF span
```

  2. **`single_span()` helper** — add directly above `spans()` (line 679):

```python
    def single_span(self) -> Redaction | None:
        """The exclusive one-span mode the timeline edits: the trim span
        or the GIF time range. None when editing blur redactions."""
        return self.trim if self.trim is not None else self.gif_range
```

  3. **Mechanical replacements** (behavior-identical while `gif_range is None`):
     - `spans()` (line 679–682) body becomes:

```python
    def spans(self) -> list[Redaction]:
        """What the timeline bar edits: the exclusive single span while
        trimming or choosing a GIF range, otherwise the blur redactions."""
        single = self.single_span()
        return [single] if single is not None else self.redactions
```

     - `active_redaction()` (line 664): replace `if self.trim is not None: return self.trim` with:

```python
        single = self.single_span()
        if single is not None:
            return single
```

     - `set_active()` (line 672): `if self.trim is not None:` → `if self.single_span() is not None:`
     - `sync_active_row()` (line 766): `if self.trim is not None:` → `if self.single_span() is not None:`
     - `frozen_mode()` (line 626): `or self.trim is not None)` → `or self.single_span() is not None)`
     - `_position_changed()` (line 644): `if self.redactions or self.trim is not None:` → `if self.redactions or self.single_span() is not None:`
     - `refresh_overlays()` (line 745): `self.range_bar.setVisible(bool(self.redactions) or self.trim is not None)` → `... or self.single_span() is not None)`
     - `RangeBar._hit` (line 330): `active = 0 if self.pane.trim is not None else self.pane.active_idx` → `active = 0 if self.pane.single_span() is not None else self.pane.active_idx`
     - `RangeBar.paintEvent` (line 418): same substitution for `active_i`; and (line 422) the band color condition `QColor("#3daee9") if self.pane.trim is not None` → `QColor("#3daee9") if self.pane.single_span() is not None` (the GIF span reuses trim's blue — one exclusive-span look).

  4. **GIF controls** — in `__init__`, replace the `gif_btn` block (lines 516–519):

```python
        self.gif_btn = QPushButton("Convert to GIF", self)
        self.gif_btn.setIcon(QIcon.fromTheme("video-x-generic"))
        self.gif_btn.setCheckable(True)
        self.gif_btn.toggled.connect(self._gif_mode)
        self.gif_btn.setEnabled(ffmpegutil.have_ffmpeg())

        self.gif_fps_spin = QSpinBox(self)
        self.gif_fps_spin.setRange(4, 30)
        self.gif_fps_spin.setSuffix(" fps")
        self.gif_fps_spin.setValue(settings.gif_fps)
        self.gif_fps_spin.valueChanged.connect(
            lambda v: setattr(self.settings, "gif_fps", v))
        self.gif_fps_spin.hide()

        self.gif_width_spin = QSpinBox(self)
        self.gif_width_spin.setRange(160, 1920)
        self.gif_width_spin.setSingleStep(80)
        self.gif_width_spin.setSuffix(" px")
        self.gif_width_spin.setToolTip(
            "Maximum GIF width — the video is never upscaled")
        self.gif_width_spin.setValue(settings.gif_max_width)
        self.gif_width_spin.valueChanged.connect(
            lambda v: setattr(self.settings, "gif_max_width", v))
        self.gif_width_spin.hide()

        self.gif_apply_btn = QPushButton("Save GIF", self)
        self.gif_apply_btn.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.gif_apply_btn.clicked.connect(self._convert_gif)
        self.gif_apply_btn.hide()
```

  In the `controls` layout, after `controls.addWidget(self.gif_btn)` (line 539) add:

```python
        controls.addWidget(self.gif_fps_spin)
        controls.addWidget(self.gif_width_spin)
        controls.addWidget(self.gif_apply_btn)
```

  5. **Mode handler** — add after `_trim_mode` (line 717):

```python
    def _gif_mode(self, on: bool) -> None:
        if on and self.redactions:
            self.gif_btn.setChecked(False)
            self._notify("Apply or remove the pending blurs before "
                         "converting to GIF")
            return
        if on:
            self.blur_btn.setChecked(False)  # exclusive, like trim
            self.trim_btn.setChecked(False)
            self.player.pause()
            dur = self.player.duration() / 1000.0
            self.gif_range = Redaction(QRect(), 0.0, round(max(dur, 0.1), 2))
            self._notify("Pick fps/width, drag the timeline edges to "
                         "choose the section to convert, then Save GIF — "
                         "the video scrubs as you drag", 0)
        else:
            self.gif_range = None
            self.hint.hide()
        for w in (self.gif_fps_spin, self.gif_width_spin, self.gif_apply_btn):
            w.setVisible(on)
        self.blur_btn.setEnabled(not on and ffmpegutil.have_ffmpeg())
        self.range_bar.setVisible(on or bool(self.redactions))
        self.range_bar.update()
        self._sync_video_surface()
```

  6. **Cross-mode unchecks** — in `_blur_mode` (line 686), after `self.trim_btn.setChecked(False)` add `self.gif_btn.setChecked(False)`. In `_trim_mode` (line 702), after `self.blur_btn.setChecked(False)  # mutual exclusion, both ways` add `self.gif_btn.setChecked(False)`. In `_clear_redactions` (line 738), after `self.trim_btn.setChecked(False)` add `self.gif_btn.setChecked(False)` (unchecking runs `_gif_mode(False)`, clearing `gif_range` — `load()`/`stop()` therefore reset GIF mode for free).

  7. **Convert uses the options** — replace `_convert_gif` (lines 945–961) and the button bookkeeping in `_gif_done` (lines 963–976):

```python
    def _convert_gif(self) -> None:
        if not self.path or self._gif_proc is not None:
            return
        from .capture import unique_path
        base = os.path.splitext(os.path.basename(self.path))[0]
        out = unique_path(self.settings.library_dir, f"{base}.gif")
        tmp = self._render_temp(out)
        start = end = None
        if self.gif_range is not None:
            dur = self.player.duration() / 1000.0
            # Skip the seek when the span is effectively the whole video:
            # QMediaPlayer's duration is approximate, and an exact -to can
            # drop the final frames.
            if (self.gif_range.start > 0.05
                    or self.gif_range.end < dur - 0.05):
                start, end = self.gif_range.start, self.gif_range.end
        args = build_gif_args(self.path, tmp,
                              fps=self.gif_fps_spin.value(),
                              max_width=self.gif_width_spin.value(),
                              start_s=start, end_s=end)
        self._gif_proc = QProcess(self)
        self._gif_proc.finished.connect(
            lambda code, _st: self._gif_done(code, tmp, out))
        self.gif_apply_btn.setEnabled(False)
        self.gif_apply_btn.setText("Converting…")
        self.status.emit("Converting to GIF…", 0)
        self._gif_proc.start(ffmpegutil.ffmpeg_path(), args)

    def _gif_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._gif_proc = self._gif_proc, None
        if proc is not None:
            proc.deleteLater()
        self.gif_apply_btn.setEnabled(True)
        self.gif_apply_btn.setText("Save GIF")
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self.gif_btn.setChecked(False)  # exits GIF mode
            self._notify(f"GIF saved: {os.path.basename(out)}")
            self.file_ready.emit(out)
        else:
            self._notify("GIF conversion failed", 6000)
            if os.path.exists(tmp):
                os.unlink(tmp)
```

  Note: `load()` (line 582) already hides `gif_btn` for GIF sources; the option widgets stay hidden because the mode is unchecked by `_clear_redactions`. Validation that `end > start` is enforced structurally by `RangeBar` (it clamps `start <= end - 0.1` during drags, lines 389–392) plus the full-range fallback — no extra guard needed.

- [ ] **Run:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_pane.py -q` → 12 passed.
- [ ] **Regression check (mandatory — this task touched shipped trim/blur paths):** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` → 212 passed, zero failures.
- [ ] **Commit:** `git add wondershot/video.py tests/test_video_pane.py && git commit -m "Video: GIF fps/width/range options reusing the trim span timeline"`

---

## Task 6: Final regression pass, ROADMAP, desktop-checklist entries

**Files:**
- Modify: `ROADMAP.md` (lines 192–194 only — see cross-track caution in File Structure)

- [ ] **Full suite, clean:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` → 212 passed. Also run the video-touching files verbosely to eyeball nothing was skipped: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_video_filter.py tests/test_video_pane.py tests/test_video_preview.py tests/test_settings_video.py -v`.
- [ ] **Update ROADMAP** — replace lines 192–194:

```
4. **Video backlog** — blur strength setting, GIF options
   (fps/scale/range), true blur preview in the frost.
   (trim/cut moved to WS-A)
```

with:

```
4. **Video backlog** — DONE 2026-06-07: blur strength spinbox (persisted,
   previewed live), GIF fps/max-width/time-range options reusing the trim
   span timeline (persisted defaults), frost rectangles preview the actual
   blur (QImage downscale/upscale approximation — render remains truth).
   (trim/cut moved to WS-A)
```

- [ ] **Hand these manual items to the consolidated desktop checklist** (the orchestrator owns `docs/superpowers/plans/2026-06-07-desktop-checklist.md`; do NOT create a separate checklist file — list them in your final task report): (1) draw a blur on a real recording, drag the Strength spinbox and watch the frost re-blur live; render and compare preview vs output; (2) re-open the app — strength/fps/width remember their last values; (3) Convert to GIF with a sub-range on the timeline, confirm the GIF covers only that range and respects fps/width; (4) confirm trim and frame-grab still behave exactly as before (regression items); (5) confirm blur/trim/GIF buttons mutually exclude on click.
- [ ] **Commit:** `git add ROADMAP.md && git commit -m "ROADMAP: track 3c video backlog done (blur strength, true preview, GIF options)"`
