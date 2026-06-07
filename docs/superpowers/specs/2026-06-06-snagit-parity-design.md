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

---

# Addendum 2 (2026-06-07): Backlog burn-down — batches 3 and 4

Jack: "knock all of this out as soon as possible, preferably without
stopping." Autonomous execution, batched by file ownership (editor.py is
the contention point). One consolidated desktop checklist at the very end.

## Batch 3 (parallel tracks)

### Track 3a: Tray-stop bug + recording polish (record.py, app.py)
- **Tray Stop bug (confirmed by Jack):** tray-menu Stop does not stop a
  recording; toolbar stop works. Diagnose first (read the wiring, write a
  failing test against the real defect), then fix so either control stops
  and both reset. Regression test required.
- **Duration in tray tooltip:** recorder.tick already emits elapsed time —
  mirror it into the tray tooltip alongside the existing action text.
- **Countdown before start:** optional setting (default off, spinbox 0-10s);
  small frameless always-on-top countdown widget (compositor places it —
  no positioning tricks), tick down, then start the portal flow.
- **Pause/resume:** TIMEBOXED investigation — GStreamer pipeline PAUSED
  state vs valve element; mp4mux/PTS behavior on resume is the risk (see
  no-PTS landmine). If clean pause is provable headless-adjacent, ship with
  toolbar+tray Pause; otherwise document findings in ROADMAP and park.
- **Region-only recording:** explicitly OUT of this track (portal has no
  region source; needs crop-in-pipeline design — ROADMAP note only).

### Track 3b: Sidecar persistence (editor.py, gallery.py, items.py, new sidecar.py)
Jack's bar: do everything — including destructive ops — with no save
prompts, and undo it all when revisiting. Own format acceptable.
- **Files:** library file stays the flattened, share-ready PNG (drag-out
  and share unchanged). Per-image sidecar under
  `<library>/.wondershot/<name>.json` plus a base-image stack
  `<name>.base.<N>.png` (N=0 is the original capture).
- **Model:** sidecar = {format version, base stack refs, ordered item list
  (serialized annotation objects), applied-effects record}. items.py
  classes get to_dict/from_dict (pure, headless-testable).
- **Editor open:** sidecar exists → load top-of-stack base + reconstruct
  items as live editable objects. No sidecar → current behavior.
- **Autosave, no prompts:** on editor close and app quit, silently write
  flattened PNG + sidecar. The "unsaved changes?" prompt is removed for
  library files (kept for files opened outside the library, e.g. -e on a
  random path — they have no sidecar home).
- **Destructive ops** (bg remove, effects, flatten): push the pre-op base
  onto the stack before applying; revisit-undo pops it. In-session undo
  (QUndoStack) unchanged.
- **Trash:** trashing the image trashes its sidecar + bases; undo-delete
  restores them.
- **Scope:** images only. Video annotations don't exist yet (blur already
  renders to a new file); ROADMAP note that video sidecars arrive with
  video objects.
- Embedded editor and standalone editor windows both use the same path.

### Track 3c: Video backlog (video.py)
- **Blur strength setting:** slider/spin in the blur pane mapped to the
  boxblur radius used in the ffmpeg pass; persisted default in settings.
- **True blur preview:** the frost rectangles preview the actual blur —
  QImage box-blur of the covered region on the frozen frame (preview-only,
  cheap approximation acceptable; label it if visually different).
- **GIF options:** fps / scale / time-range controls (reuse trim-style
  range UI) on the GIF convert flow; persisted defaults.

## Batch 4 (parallel tracks, after batch 3 merges)

### Track 4a: AI simplifier + editor backlog (editor.py + new simplify.py)
- **Simplifier:** vision LLM (existing aiclient) returns UI regions+types;
  replace regions with clean editable objects (RectItem blocks for text
  runs, palette-matched fills for chrome) — output is OBJECTS on the
  canvas (Snagit-better: fully editable afterwards), single undo macro.
  Reuses redact.py's region-pipeline patterns; same non-destructive rule.
- **Editor backlog:** text alignment (left/center/right) + edge snapping
  in text boxes; style-change undo (color/stroke/font changes go on the
  undo stack); blur-tool variant of pixelate (gaussian region item);
  step renumbering (drag a step badge onto another to swap/insert).
  Custom rotate-cursor polish only if trivial.

### Track 4b: Scroll-capture UI + EI client (gallery.py wiring, scrollsource.py, new ei.py, cli.py)
- **Scroll UI promotion:** "Scrolling capture" entry in tray + capture
  panel (gated like window mode on KDE? No — portal ScreenCast is
  desktop-neutral; gate only on GStreamer availability). Flow: trigger →
  portal pick → unobtrusive "scrolling — Ctrl+click tray or click Stop to
  finish" affordance (frameless stop pill, compositor-placed) → stitched
  PNG lands in library like any capture (quick bar applies). Keep the CLI
  flag for debugging.
- **EI client:** integrate snegg if pip-installable (optional extra
  `wondershot[stepcapture]`), else a minimal ctypes libei binding for the
  receive path only. Deliverable: extend inputcapture_probe.py to complete
  the EIS handshake and print pointer-button events — the semantics
  question (do apps still receive clicks while we observe?) goes into the
  final checklist as the one manual probe run.
- NO step-capture feature UI yet — that waits on the semantics verdict.

## Verification & delivery
Per-track TDD, adversarial review, merge per batch, suite green, reinstall
Jack's app after each merge. ONE consolidated checklist at the end
(replaces/extends docs/superpowers/plans/2026-06-07-desktop-checklist.md).
GitHub repo creation + CI-triggering push: requires Jack's explicit OK
(publishing) — held as the single open question.

---

# Addendum 3 (2026-06-07): WS-E — Windows port, VM-driven

Goal directive from Jack: complete the roadmap through a WORKING Windows
version on the win11-pam VM (copied from the dev box to this host;
libvirt/KVM/default-net verified ready). The agent drives the VM over
SSH/PowerShell end-to-end — including visual verification by
screenshotting the VM's desktop (PowerShell CopyFromScreen → scp → image
read), so no human in the loop for the build-test cycle.

## Architecture decisions (pinned)

- **Stills backend (`WinCaptureManager`)**: `mss` (pure-ctypes pip dep) for
  fullscreen grabs. Active-window mode via ctypes
  `user32.GetForegroundWindow` + `DwmGetWindowAttribute(EXTENDED_FRAME_BOUNDS)`
  (the kwin.py analog, trivially fakeable in tests). Region mode: WE OWN THE
  SCREEN on Windows — frameless fullscreen Qt overlay showing the grabbed
  frame with rubber-band selection (portable Qt code; doubles as the future
  owned region picker that Wayland denies us).
- **Recorder backend (`WinScreenRecorder`)**: ffmpeg `ddagrab` (Desktop
  Duplication; hw path) with `gdigrab` fallback, audio via `dshow`; args
  built like the existing gst string, run through `ffmpegutil` + QProcess
  with the same watchdog/stopping/salvage semantics as Linux. NO GStreamer
  on Windows.
- **Hotkeys**: `RegisterHotKey` ctypes loop behind the existing
  `HotkeyBackend` seam.
- **Backend selection**: `sys.platform` factory in capture.py/record.py
  mirroring `create_hotkey_backend`; Linux behavior byte-identical.
- **Already portable, expect to just work**: editor, gallery, video player
  (QtMultimedia→ffmpeg on Windows), sidecars, AI stack, quick bar, settings,
  trim/GIF/frame-grab (all ffmpeg via ffmpegutil PATH discovery).
- **Out of scope for "working version"**: installer/packaging (runs from a
  synced checkout + venv python in the VM), code signing, step capture
  Windows backend (follow-up), tray autostart.

## VM workflow

- Copy repo to VM per deploy: `git bundle` or tar over scp (no GitHub
  remote). Provision once: winget install Python 3.12+, ffmpeg; pip install
  -e ".[spike]" pytest.
- Verification ladder per milestone: (1) import smoke + pytest over SSH
  (CI guards already make the suite Windows-honest); (2) launch the app in
  the VM's logged-in session, screenshot the desktop, READ the screenshot;
  (3) scripted capture/record smoke writing into the library, file
  assertions over SSH.
- Definition of done for the goal: on the VM — app launches with tray,
  hotkey fires a capture, region/fullscreen/window capture produce correct
  PNGs in the library, recording produces a playable mp4, editor
  annotates + sidecar-persists, suite green (Windows skips honest).

## Sequencing

1. Batch 4 merges first (owns cli.py/capture_window.py surfaces).
2. VM: define domain from dumped XML (path fixups), boot, snapshot
   "pristine", provision, baseline suite run.
3. Plan→review→execute→review workflow for the backends (worktree), with
   on-VM verification steps embedded in the plan.
4. Iterate on-VM until the definition of done holds; consolidated checklist
   updated; windev skill updated (VM now lives on this host too).

---

# Addendum 4 (2026-06-07): In-process recorder pipeline — unlock the parked cluster

Honest-accounting follow-up. Four roadmap items are parked on ONE root
cause: the Linux recorder is a `gst-launch-1.0 -e` subprocess
(record.py), so nothing can reach the stream mid-flight. Converting it to
an in-process GStreamer pipeline (the same appsink technique
scrollsource.py already uses for scroll capture) unlocks three of them.
Step capture's click-animation needs the EI verdict too, so it stays out.

## Foundation (must land first, behavior-preserving)

Rewrite `ScreenRecorder` to drive an **in-process** Gst pipeline instead
of spawning gst-launch:
- Build via `Gst.parse_launch` (or element-by-element) ending in the
  same encode→mux→filesink chain; keep the `videorate` + fixed-framerate
  no-PTS fix VERBATIM (ROADMAP landmine — pipewiresrc emits PTS-less
  buffers; mp4mux aborts on them).
- Replace QProcess/subprocess lifecycle with `GstBus` watching +
  pipeline state. Preserve EVERY existing observable: `started`,
  `stopping`, `finished`, `failed`, `tick` signals; the watchdog
  (detect pipeline death, salvage partial, never hang on "Stopping");
  graceful stop = send EOS and wait for it (the in-process analog of
  `-e` + SIGINT), with the same terminate→kill escalation timer; the
  `.rendering` tmp + salvage-on-crash + `sweep_stale_tmp`.
- Audio (mic) mux path unchanged in behavior.
- Existing tests/test_record.py must stay green (adapt the harness from
  "fake subprocess" to "fake/real Gst pipeline" — keep assertions on
  observable behavior, not on argv). This is the riskiest part; if a
  test pins argv, rewrite it to pin behavior.
- Windows recorder (winrecord.py) is UNTOUCHED — it stays QProcess+ffmpeg.

## Unlocked features (layer on the in-process pipeline)

1. **Cursor halo** (the WS-A item parked twice): request portal
   cursor-mode *metadata* (mode 4) in SelectSources; read the
   `spa_meta_cursor` position per buffer off the appsink sample; composite
   a translucent halo (cairo/QPainter overlay element, or a pad-probe
   draw) at that position. Setting in Settings→Recording, default off.
   If metadata cursor coords still prove unreadable through gi bindings,
   document precisely why and park AGAIN (but this time from the
   in-process vantage, which is the one that's supposed to work).
2. **Pause/resume**: toolbar + tray Pause/Resume. Implement by gating the
   stream into the encoder (a `valve` element drop=true, or
   set the pipeline to PAUSED) while keeping output PTS continuous — the
   resumed segment must not break mp4mux (test the PTS continuity; this
   is the real risk). Tick clock pauses too.
3. **Region-only recording**: an in-app region choice that inserts
   `videocrop`/`videobox` (or a capsfilter on a cropped src) so only the
   chosen rect is encoded. Portal still streams the whole monitor; we
   crop in-pipeline. UI: reuse the owned-region selection overlay pattern
   from wincapture's RegionOverlay (it's portable Qt).

## Out (still gated/parked)
- Click *animation* (needs EI click events — same gate as step capture).
- Step capture feature UI (needs the interception-semantics verdict).
- macOS (hardware).
- During-capture toolbar (don't own the Wayland picker).

## Verification
Linux suite green throughout (behavior-preserving foundation first).
Live-desktop checks (actual recording, halo visible, pause/resume
produces a continuous playable mp4, region crop correct) append to the
consolidated desktop checklist — not blocking, per the testing rule.
