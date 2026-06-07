# Roadmap — Wondershot (formerly grabbit)

_Last updated: 2026-06-06_

## Working today (v0.1.x)

**Capture & library**
- Region/fullscreen capture (Spectacle backend, portal fallback)
- Carousel gallery over multiple watched folders (Screenshots +
  ~/Videos/Screencasts), drag-out to any app, skeleton thumbs, rename,
  trash, pin-on-top, settings dialog, tray, single-instance CLI
- Hotkey via KDE custom shortcut → `wondershot --capture`
  (`grabbit --capture` still works as a legacy alias)

**Editor**
- Arrows, lines, boxes, ellipses, pen, highlighter, text (click label /
  drag box with wrap width), step numbers, live pixelate, crop,
  cut-out V/H
- Objects are layers: select with any tool, move, corner grips,
  rotate grip (smooth, Shift = 15° snap, curved-arrow cursor),
  text width/font grips, step radius grip
- Grip edits and adds/deletes are undoable; properties sidebar
  (color/stroke/text size) applies to selection

**Video**
- Smooth playback (QVideoWidget; frozen-frame overlay while editing —
  Wayland's video subsurface can't be painted over, so we hide it and
  paint the frame ourselves)
- Range blur: boxes on a paused frame, per-blur time spans on the
  timeline bar (edge grips / move / scrub-while-dragging), multiple
  regions, one ffmpeg pass → `-redacted.mp4`; renders isolated in
  `.rendering/` so half-written files never hit the gallery
- GIF conversion (animates + loops in player, GIF badge)

**Recorder (native, no Spectacle)**
- Portal ScreenCast → PipeWire → gst-launch: x264 + AAC mp4 into the
  library; share dialog only on first use (restore token persisted)
- Microphone with measured tuning: webrtcdsp NS very-high, AGC off
  (ambient floor −43dB vs −21dB raw); device picker + toggles in
  Settings; full log at ~/.cache/wondershot/recorder.log
- Camera bubble: circular, frameless, always-on-top, drag to move,
  wheel to resize, bottom-right default via KWin window rule;
  toolbar + tray toggle

## Awaiting Jack's verification

- [ ] Recording audio: voice level OK with AGC off? (if too quiet:
      add fixed makeup gain, not AGC)
- [ ] Bubble lands above the taskbar on first open (96px clearance,
      300ms rule-reload delay)
- [ ] Stop button sync (tray + toolbar both reset after either stops)
- [ ] Recording survives past the first seconds (videorate fix for the
      pipewiresrc no-PTS mux abort) and stop always resolves — the
      watchdog now reports pipeline death instead of "Stopping" forever
- [ ] OneDrive end-to-end: Connect → browser sign-in lands; share a
      shot and a video, link opens. Azure SAS untested against a real
      account (built to spec)

**Wondershot rename (2026-06-06)**
- Package/CLI/config renamed; settings auto-migrate from grabbit;
  `grabbit` CLI alias kept so existing KDE hotkeys still fire
- Old `~/.local/share/grabbit/venv` is orphaned; safe to delete once the
  new install is confirmed good

**Sharing — three providers, one Share button**
- Single Share button, top-right of the gallery's main toolbar (same
  spot for images and videos; acts on the selected item). Confirms on
  the button itself: Uploading… → ✓ Copied link; dialog on failure
- S3-compatible + Azure Blob: stdlib HMAC signers (SigV4 verified
  against AWS's test vector + live MinIO); time-limited presigned/SAS
  URLs; caret menu picks provider + sets default
- OneDrive/SharePoint via Graph (stdlib): browser-redirect sign-in
  (auth-code + PKCE over the `wondershot://auth` scheme handler, no
  secret) with a "Use device code" checkbox fallback; Connect↔Cancel↔
  Disconnect; inline destination (My OneDrive / search a SharePoint
  site → library); client ID hidden as "Wondershot Built-In" w/ Change.
  Public-client toggle on the app registration is confirmed ON.
- Credentials note: S3/Azure keys are plaintext in config; OneDrive
  uses refresh tokens in a 0600 cache instead

**Editor & capture UX**
- Snagit-style zoom: fit-to-window default (tracks window resize, never
  upscales small images); status-bar − / zoom-% combo / + / Fit
- Effects: rounded corners + bottom fade (properties panel, persisted
  defaults). Live preview over a checkerboard mat + padding so the
  transparency reads; applied once, mat excluded at flatten
- Snagit-style capture window (Capture button in gallery toolbar):
  big red Capture + full screen/record, toggles for preview/clipboard/
  cursor/delay that persist as defaults
- Editor toolbar is tools-only (file ops via shortcuts + context menu)
- Deletes are undoable: hover (x) on cards (confirms), Ctrl+Z restores
  from a staging dir, flushed to system trash on quit
- Arrows/lines show endpoint grips only (no dashed box); properties
  panel rows follow the selection; "Camera" replaces "Bubble"

## Snagit-parity workstreams (2026-06-06)

Full design: `docs/superpowers/specs/2026-06-06-snagit-parity-design.md`.
A/B/C are mutually independent; D gates scroll/step capture; E comes
after Linux is feature-complete.

**WS-A — Video quick wins** _(in progress)_
- Capture frame from video (S): ffmpeg single-frame extract — avoids
  the QVideoSink/Wayland subsurface landmine
- Trim (S/M): reuse the blur range timeline; stream-copy default,
  frame-accurate re-encode checkbox; middle-cut/concat → backlog
- Cursor halo (M): **investigated 2026-06-06, parked.** Portal cursor-mode
  *metadata* (4) delivers pointer coordinates as PipeWire `spa_meta_cursor`
  per-buffer stream metadata — but our recorder is a `gst-launch-1.0` argv
  subprocess, and `pipewiresrc` (1.4.11 — zero "cursor" strings in the
  compiled plugin) does not translate that metadata into anything a
  downstream element in a pipeline string can read, so there is nowhere to
  composite a halo. (Probe transcript: `spikes/cursor_halo_probe.md` —
  AvailableCursorModes=7, gst-inspect of pipewiresrc, binary grep; a
  metadata-mode test recording — expected to show the cursor vanish with no
  recoverable coordinates — is written up there as a manual check.)
  Unblocking requires owning the pipeline in-process (appsink/appsrc, or a
  pw_stream consumer) so we can read `spa_meta_cursor` per buffer and draw
  the halo ourselves — that rewrite is the same frame-source seam WS-D's
  scroll capture needs, so the halo rides along with WS-D rather than
  blocking WS-A. Until then, recordings keep cursor-mode *embedded* (2).
  Click *animation* remains gated on WS-D input capture.

**WS-B — AI foundation** _(in progress)_
- BYO OpenAI-compatible endpoint: `ai_endpoint`/`ai_api_key`/`ai_model`
  settings, AI tab, stdlib-HTTP `aiclient.py`, QRunnable jobs
- AI redaction (M): tesseract word boxes (optional dep) + LLM picks
  *which* text is sensitive → PixelateItems, non-destructive
- Background remover (M): local ONNX (rembg) as `wondershot[ai-local]`
  extra — chat endpoints can't return alpha mattes, so never the LLM
- Image simplifier (L): later; reuses redaction's vision→regions pipeline

**WS-C — Capture UX**
- Post-capture quick-action toolbar (M): scoped *post*-capture only —
  selection UI belongs to Spectacle and Wayland windows can't
  self-position (LayerShellQt on KDE when we own the picker)
- Auto-size-to-window (M): KDE-only via KWin scripting D-Bus; trivial
  on X11/Win/mac later; GNOME needs an extension — documented, not built

**WS-D — Capture engine** _(spike in progress)_
- Scroll capture (XL): user scrolls, we stitch — frames from the
  existing ScreenCast pipeline through a portable FrameSource seam,
  numpy overlap-matching stitcher. No input injection needed.
- Step capture (XL): blocked on global click observation. Linux path:
  xdg InputCapture portal (spike running; findings below). If the
  spike fails, step capture ships Windows-first under WS-E.
  AI halves (auto-crop around click, write instructions) are S each
  once WS-B's client exists.
- Click animation in video (M): same input gate as step capture

**WS-E — Cross-platform (Windows, then macOS)**
- Qt UI ports free; per-OS work = CaptureManager/ScreenRecorder
  backends, hotkeys, packaging. Windows first (Snagit-refugee
  audience; step capture trivial via SetWindowsHookEx).
- Windows dev/test against the win11 VM over SSH — no separate box
- Deferred decisions: packaging tool (PyInstaller vs briefcase),
  GStreamer-on-Windows vs native encode, code signing, keyring

### InputCapture portal probe findings

_(pending — filled in by the WS-D spike)_

## Next up (in order)

1. **Sidecar persistence** — annotations stay editable objects when you
   revisit an image (Jack's "can't go back and edit objects").
   Design: library file stays the flattened share-ready PNG; sidecar
   `.wondershot/<name>.json` + original base copy; editor reconstructs
   objects on load.
2. **Recording polish** — countdown before start, region-only
   recording (portal already asks, but in-app choice), pause/resume,
   recording duration in tray tooltip.
3. **Editor backlog** — text alignment + edge snapping in boxes
   (Snagit), style-change undo, blur-tool variant, step renumbering,
   custom rotate cursor polish.
4. **Video backlog** — blur strength setting, GIF options
   (fps/scale/range), true blur preview in the frost.
   (trim/cut moved to WS-A)

## Cross-platform position

UI/editor/video/library are pure Qt (portable as-is). OS-specific code
is quarantined in CaptureManager + ScreenRecorder backends; Windows
(native APIs) and macOS (ScreenCaptureKit) become additional backends,
not rewrites. Electron evaluated and rejected: would forfeit native
drag-out, GPU video path, and tray-app footprint without reducing the
per-OS capture work. Prep rules while building A–D: OS-specific code
stays behind seams (CaptureManager/ScreenRecorder/FrameSource), one
ffmpeg helper with PATH discovery, binary discovery for tesseract,
HotkeyBackend interface, CI matrix on all three OSes.

## Platform landmines (hard-won, do not relearn)

- KGlobalAccel D-Bus: malformed `setShortcutKeys` aborts KWin 6.6.5
  (compositor crash). Report upstream; never auto-register.
- QtDBus signal connects need `SLOT("name(sig)")` — raw strings get
  their first char eaten and fail silently.
- xdg portals demand uint32-typed options; PySide6 can't produce typed
  variants → portal calls go through Gio/GLib (system gi module,
  venvs need --system-site-packages).
- Wayland: windows can't self-position (use KWin rules; no panel
  struts in availableGeometry); video lives in a native subsurface
  above all widget painting; translucent siblings don't composite
  over it.
- QGraphicsVideoItem = CPU paint (lags 60fps); QVideoWidget +
  QOpenGLWidget viewport = blank on Wayland.
- libx264 can't enter WebM containers; transcode webm→mp4 (+AAC).
- pipewiresrc intermittently emits buffers with no PTS near stream start
  (even with do-timestamp=true); mp4mux aborts the whole pipeline on the
  first one ("Buffer has no PTS"). videorate + fixed framerate caps drop
  them and yield CFR output. Watchdog the gst process for its whole
  life — a single startup liveness check misses later death and the UI
  hangs on "Stopping".
- QListView uniformItemSizes caches the first measurement — set
  explicit sizeHints/placeholder icons before the view measures.
- Qt movable-drag moves all selected items with the grabber — freeze
  the parent while dragging child grips.

## WS-D capture-engine spike findings (2026-06-06)

_Template appended by the WS-D plan; fill in after running the two
spikes on the Fedora/KDE box. These results gate scroll capture's
productization and step capture's platform order (Linux-first vs
Windows-first as part of WS-E)._

### Scroll capture (`wondershot --scroll-spike`, stitch.py)

Run it (live KDE session, NOT offscreen), from the ws-d worktree:

```bash
cd /home/jack/GitHub/grabbit-wt/ws-d
.venv/bin/wondershot --scroll-spike
```

1. The portal screen-share picker appears (or is skipped if a restore
   token exists from prior recordings). Window-pick the browser for
   cleaner results than a full-screen cast.
2. Open a long page, wait for "Recording —" to print.
3. Scroll top-to-bottom slowly (one wheel notch every ~0.5 s).
4. Ctrl+C in the terminal; a `ScrollCapture_*.png` should land in the
   library dir (default `~/Pictures/Screenshots`).

- Stitched tall PNG produced from a real scrolled window: YES (ran
  2026-06-06) — pipeline works end to end, output quality fails
- Seam quality: **very jagged** — visible misaligned strips, so
  `detect_offset`'s single 64-row band match is not accurate enough on
  real content (likely confounds: smooth/kinetic scrolling between
  frames, font antialiasing differences, the band landing on uniform
  background with no texture to lock onto)
- **Window targeting wrong**: the capture did not track the window
  being scrolled (portal stream captured something other than the
  intended/active window). Needs investigation: restore-token reuse
  from prior recordings may skip the picker and reuse the previously
  shared source — the spike should request a fresh window pick
  (ignore `screencast_token`) so the user explicitly picks the window
  to scroll
- Verdict: **NEEDS algorithm work** — concept proven (portal→appsink→
  stitcher produces a tall PNG), productization needs (a) better
  matching: multi-band or full-overlap cross-correlation, subpixel/
  integer refinement, texture-aware band selection; (b) fresh source
  pick per scroll session; (c) seam blending. The FrameSource seam and
  test harness are sound — iterate on `detect_offset`/`ScrollStitcher`
  against captured real-frame fixtures, not just synthetic noise

### InputCapture portal (`spikes/inputcapture_probe.py`)

Run it (live KDE session; uses the system python for gi):

```bash
cd /home/jack/GitHub/grabbit-wt/ws-d
python3 spikes/inputcapture_probe.py
```

If a permission dialog appears, accept it. The probe never touches
KWin directly; worst case is a failed portal request. Copy the
`FINDING:` lines into the blanks below.

- Portal interface present: YES — version: 1
  _(pre-filled via non-interactive property read during plan
  execution; no session was created)_
- SupportedCapabilities: 7 (KEYBOARD|POINTER|TOUCHSCREEN) _(pre-filled,
  same property read)_
- CreateSession: OK (granted capabilities=3 = KEYBOARD|POINTER;
  touchscreen not granted) _(run 2026-06-06)_
- GetZones: OK — zones=[(2560,1440,3440,0), (3440,1440,0,0)]
  (both monitors reported)
- ConnectToEIS fd obtained: YES (fd=8)
- Pointer button events observed: NOT YET — no python libei bindings
  (snegg) installed, so the EI protocol handshake couldn't be spoken;
  raw read returned 20 bytes without a handshake (the EIS server
  talking first — expected for EI, the probe's "unexpected" warning is
  just its own conservatism)
- Blocking gaps: (1) need an EI client — snegg (python libei bindings)
  or ctypes against libei — to handshake and decode button events;
  (2) must verify capture *semantics*: InputCapture is designed to
  intercept (input stops reaching apps while a capture is active,
  normally triggered via pointer barriers + Enable). Step capture
  needs observe-without-stealing — either confirm events flow without
  Enable/barriers, or re-emit captured input instantly via the
  RemoteDesktop portal. This is the next spike question.
- **Verdict: step capture LINUX-VIABLE (provisional)** — every portal
  step succeeds end to end on Fedora 43/KDE: session granted,
  zones reported, EIS fd handed over. Remaining work is client-side
  (EI protocol library) plus the interception-semantics question
  above, not platform capability. Keep Windows-first as fallback only
  if the semantics check fails.
