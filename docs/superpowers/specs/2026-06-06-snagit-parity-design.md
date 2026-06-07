# Snagit Parity: Roadmap + Session Workstreams — Design

_2026-06-06. Approved by Jack. Defines the full parity roadmap (workstreams A–E) and
the three-plus-one tracks being built this session: WS-A (video quick wins),
WS-B (AI foundation), WS-D spike (capture engine), and CI matrix prep for WS-E._

## Context

Wondershot (formerly grabbit) targets Snagit feature parity. Reference:
https://www.techsmith.com/snagit/features. Current state: Qt/PySide6 app, Linux/KDE
Wayland, Spectacle + portal capture (`capture.py`), native Portal
ScreenCast → PipeWire → GStreamer recorder (`record.py`), full markup editor
(`editor.py`, `items.py`), video player with range-blur timeline (`video.py`),
OneDrive/S3/Azure sharing (`share.py`, `msgraph.py`).

Key insight from recon: we already half-own a capture engine — `record.py` streams
frames. Scroll capture does not need input injection (user scrolls, we stitch).
Step capture's global click hooks are the genuinely hard Linux problem.

## Workstreams (full roadmap)

| WS | Items | Size | Gate |
|----|-------|------|------|
| A | Frame-from-video (S), video trim (S/M), cursor halo (M) | small | none |
| B | AI plumbing + redaction (M), bg remover (M), simplifier (L, later) | medium | none |
| C | Post-capture toolbar (M), auto-size-to-window (M, KDE-only) | medium | none |
| D | Scroll capture (XL), step capture (XL), click animation (M) | long pole | input spike |
| E | Windows (XL), then macOS (XL) | largest | Linux feature-complete |

Dependencies: A, B, C mutually independent. D's stitch track is safe; D's input
track (xdg InputCapture portal) decides whether step capture is Linux-viable or
ships Windows-first as part of E. E makes step capture and click animation
trivial (SetWindowsHookEx / CGEventTap).

Explicit scoping calls:
- **Capture toolbar is post-capture only** until we own the region picker
  (selection UI belongs to Spectacle; Wayland windows can't self-position —
  LayerShellQt on KDE when we get there).
- **Auto-size-to-window is KDE-only** (KWin scripting D-Bus); trivial on
  X11/Windows/macOS later. GNOME: not without an extension — documented, not built.
- **Step capture may ship Windows-first** if the InputCapture spike fails.
- **Background removal is local ONNX**, never the LLM endpoint (chat APIs don't
  return alpha mattes).

## This session: WS-A — Video quick wins

All in `video.py` + small `gallery.py` touches. Reuses the existing range-selection
timeline built for blur.

1. **Frame grab.** "Save frame" action in the player at the current position.
   `ffmpeg -ss <pos> -i in.mp4 -frames:v 1 out.png` (sidesteps the documented
   Wayland QVideoSink subsurface landmine). Output named `<video-stem>-frame.png`
   in the library; opens in the editor.
2. **Trim.** New trim mode on the timeline: in/out handles. Default stream-copy
   (`-ss/-to -c copy`) — instant, snaps to keyframes; "Frame-accurate (re-encode)"
   checkbox uses x264 like the blur pass. Output `<stem>-trimmed.mp4` rendered in
   `.rendering/` like blur does. Middle-cut/concat: backlog.
3. **Cursor halo.** Recorder option (Settings → Recording): request portal cursor
   mode *metadata*, composite a translucent halo at cursor position in our
   GStreamer pipeline. Static halo only; click-flash animation gated on WS-D input.
   If metadata cursor mode proves unworkable in gst-launch-style pipelines, fall
   back to documented "not yet" with findings — do not block items 1–2.

Error handling: ffmpeg failures surface like the blur pass does today (no new
patterns). Tests: extend `test_video_filter.py` for trim/frame-grab command
construction; pure functions for timeline math.

## This session: WS-B — AI foundation, redaction, background remover

**Plumbing** (`aiclient.py`, new):
- Settings keys `ai_endpoint`, `ai_api_key`, `ai_model` (property pattern in
  `settings.py`); "AI" tab in `settings_dialog.py` with a "Test connection" button.
- Client: stdlib HTTP (idiom of `share.py`/`msgraph.py` — no new required deps),
  OpenAI-compatible `/v1/chat/completions` with base64 image content. Plaintext
  key storage matches existing S3/Azure precedent.
- Jobs run on QRunnable (mirror `ShareJob`), progress dialog, cancelable.

**Redaction** (editor toolbar action "AI Redact"):
- Pipeline: optional local `tesseract` OCR (binary discovery helper; degrade
  gracefully if absent) yields word boxes → vision LLM is asked *which* text is
  sensitive (returns text spans/labels, not pixel coords) → matched back to OCR
  boxes. Fallback without tesseract: ask LLM for normalized bounding boxes
  directly (sloppier; documented).
- Result: `PixelateItem`s added per region — **non-destructive**, user reviews/
  adjusts/deletes before flattening. No auto-flatten.

**Background remover** (editor toolbar action "Remove Background"):
- Local ONNX matting (rembg/U²-Net) as optional extra `wondershot[ai-local]`
  (onnxruntime + rembg). Menu item disabled with a tooltip when the extra is
  missing.
- Applies via `set_base_image()` wrapped in `FlattenCommand`-style undo; alpha
  output (ARGB32_Premultiplied + checkerboard mat already supported).

**Simplifier:** roadmap-only. Reuses redaction's vision→regions pipeline once proven.

Tests: `aiclient` request construction + response parsing against canned JSON
(idiom of `test_msgraph.py`/`test_share.py`); OCR-box matching as pure functions.

## This session: WS-D — Capture engine spike

Goal: running code answering two questions; shippable UI not required.

1. **Scroll-capture prototype** (`wondershot/stitch.py` + a `--scroll-capture-spike`
   hidden CLI flag or test harness):
   - Frame source abstraction: stitcher consumes `QImage`s from a `FrameSource`
     interface; the Linux impl taps the existing ScreenCast pipeline (appsink or
     equivalent). **The stitcher must never see PipeWire/GStreamer types** — this
     is the WS-E portability seam.
   - Stitch: detect vertical offset between consecutive frames via overlap
     band-matching (numpy, dev/optional dependency for the spike; no OpenCV),
     accumulate into a tall image. Handle: no-motion frames (drop), fixed
     headers/footers (crop band heuristic — best effort for the spike).
   - Success criterion: one stitched tall PNG from a real manually-scrolled window.
2. **InputCapture portal probe** (`spikes/inputcapture_probe.py`): does this
   Fedora/KDE box expose org.freedesktop.portal.InputCapture, and can we observe
   click events? Write findings into ROADMAP.md — this decides step capture's
   platform order. Defensive D-Bus posture per the KWin landmine history in
   `hotkey.py`.

## This session: WS-E prep (constraints + CI)

Constraints on the code written above:
1. New OS-specific code stays behind seams (`CaptureManager`, `ScreenRecorder`,
   `FrameSource`). Stitcher is pure image math.
2. One `ffmpeg` invocation helper (PATH discovery now, bundled later) — WS-A
   should route through it; existing call sites migrate opportunistically.
3. `HotkeyBackend` interface extracted from `hotkey.py` (shape only; no new
   backends).
4. Binary discovery helpers for tesseract/ffmpeg (no hardcoded paths).
5. CI: GitHub Actions matrix (ubuntu/windows/macos-latest) — install + import
   smoke + pytest. Capture isn't testable headless; import/path/case bugs are.

Deferred deliberately: packaging tool choice, GStreamer-on-Windows vs native
encode, code signing, key storage hardening (keyring).

Windows development can target the existing win11 VM over SSH (windev flow) —
no separate physical machine needed for WS-E's Windows track.

## Execution

Four parallel worktree-isolated tracks (A, B, D, CI+ROADMAP), each: TDD where
testable, self-review, tests green. Jack reviews branches at the end.

---

# Addendum (2026-06-07): WS-C + Stitch v2

Session 2, approved by Jack. Two parallel tracks. Rule of engagement: nothing
reaches Jack until done — code complete, tests green, reviewed; desktop-only
verification batched into one checklist at the end.

## Session 2: WS-C — Capture UX

1. **Post-capture quick-action bar.** After a capture lands (and preview is
   enabled), show a small frameless always-on-top bar near the capture flow's
   existing surfaces (no self-positioning tricks — Wayland; a plain
   always-on-top window the compositor places is acceptable, KWin rule if
   needed per the bubble precedent): thumbnail + actions Edit / Copy /
   Save-as / Share / Trash / dismiss. Acts on the just-captured file;
   auto-dismiss timeout (setting, default ~8s); Esc dismisses. Edit opens the
   editor as today; Copy puts the image on the clipboard; Share triggers the
   existing share path on that file. Keyboard-light, mouse-first.
2. **Auto-size-to-window.** A "Window" capture mode that grabs the active
   window without an interactive pick: query the active window's frame
   geometry via KWin scripting D-Bus (registerScript + tiny JS returning
   `workspace.activeWindow` geometry — defensive posture per the KGlobalAccel
   landmine: typed variants, timeouts, never crash the compositor; feature
   probes at startup and hides itself off-KDE), then fullscreen-capture and
   crop to that rect (multi-monitor aware via QScreen geometry union).
   KDE-only by design; off-KDE the option doesn't appear.

Both live in `capture.py` / `capture_window.py` / `app.py` (+ a new
`kwin.py` for the geometry query). Crop math and KWin-script plumbing are
unit-testable headless; the bar's GUI glue is not — explicit in the plan.

## Session 2: Stitch v2 — make scroll capture real

Findings from Jack's first run (ROADMAP): output jagged; captured the wrong
window. Fixes, in priority order:

1. **Fresh source pick per scroll session.** The spike subclasses
   `ScreenRecorder`, which reuses the persisted ScreenCast restore token —
   so it streamed the previously-shared source, not the window Jack wanted.
   Scroll sessions must ignore the stored token (request a fresh pick) and
   must NOT overwrite the recorder's token with the scroll session's grant
   (separate token key or none).
2. **Matching that survives real content.** Replace single 64-row-band
   matching with: multiple bands sampled at different x-positions, chosen by
   texture (variance threshold — skip flat regions); offset consensus across
   bands with outlier rejection; full-overlap correlation fallback when bands
   disagree. Handle smooth/kinetic scrolling: frames land at fractional
   offsets — match at integer resolution but score confidence, and skip
   frames mid-animation (low confidence) rather than stitching them.
3. **Realistic test fixtures.** Generate text-like pages with QPainter
   (lines of varying-width rounded rects or actual text rendering, margins,
   a fixed header) instead of noise; simulate kinetic scroll with fractional
   offsets via smooth-scaled sampling. The synthetic-noise tests stay; the
   new fixtures are the bar to clear.
4. **Seam quality.** Stitch at the consensus offset; on low-confidence seams
   prefer dropping the frame over visible misalignment (a longer scroll with
   more frames beats a jagged seam).

Out of scope for v2: header/footer auto-crop improvements beyond what exists,
horizontal scrolling, UI polish (still CLI-flag spike harness; promotion to a
real UI happens once Jack's next run looks clean).

All in `stitch.py` / `scrollsource.py` / `cli.py` / tests — no overlap with
WS-C's files; the two tracks can run in parallel worktrees.
