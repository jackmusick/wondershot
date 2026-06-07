# Wondershot desktop verification checklist

Consolidated across the whole Snagit-parity effort (batches A–E). Linux
items need a live KDE session (NOT offscreen); the Windows section runs
on the win11-pam VM. Nothing here is required for the build to be
"done" — it's human-eye confirmation of things that can't be asserted
headlessly.

## Linux — WS-C capture UX (live KDE session)

1. Quick bar: Settings → General → "Quick-action bar after capture" ON,
   "Show Wondershot window after capture" OFF. Capture a region — a
   frameless bar should appear bottom-center, above other windows, with
   a thumbnail of the shot. Verify: Edit opens the editor on the file;
   Copy → paste into another app; Save as → file lands where chosen;
   Share → URL on clipboard (with a provider configured) or a tray hint
   (without); Trash → file gone from the gallery, Ctrl+Z in the gallery
   restores it; Esc dismisses; left alone it dismisses after the
   configured timeout; hovering pauses the countdown.
2. Bar does NOT appear when "Show Wondershot window after capture" is ON.
3. Window mode: tray menu shows "Capture window" (KDE). Focus a window,
   trigger it — the saved PNG is exactly that window's frame, correct
   monitor, correct under HiDPI scaling. Repeat with a window on the
   second monitor. KWin must remain alive throughout (the whole point).
4. Off-KDE sanity (optional, any GNOME/wlroots session or
   XDG_CURRENT_DESKTOP unset): no "Capture window" in the tray, no
   "Window" button in the capture panel.

## Reviewer additions (quick bar / window mode)

5. Two captures back-to-back (<1 s apart, gallery hidden): the first
   quick bar is replaced cleanly by the second (no orphan/flash).
6. Quick-bar Esc under Wayland specifically: the bar is a frameless
   Qt.Tool window and may never get keyboard focus from KWin — confirm
   Esc actually dismisses (the ✕ and timeout are the fallbacks).
7. Share from the bar when the default provider is unconfigured but
   another is: toast flow works; note it rewrites your default provider
   (existing "clicking selects default" semantics).
8. If you ever run mixed per-monitor scale factors (1x + 2x): window
   capture crop alignment on the scaled monitor (uniform-scale
   assumption in the crop math).

## Stitch v2 (scroll capture)

9. `wondershot --scroll-spike` from a terminal: the portal picker MUST
   appear even though a recorder restore token is stored (the wrong-
   window bug fix). Pick the window you'll scroll.
10. After the scroll spike, start a normal recording: the picker must
    NOT appear (scroll session didn't clobber the recorder's token).
11. Scroll a long page with normal kinetic scrolling, Ctrl+C: inspect
    the stitched PNG — seams should now be clean (multi-band consensus
    + drop-on-low-confidence replaced the single-band matcher).
12. One deliberately fast flick-scroll mid-run: should just report
    dropped frames at exit (pre-review this could crash the stitcher).

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

## Windows (win11-pam VM) — WS-E definition of done (2026-06-07)

Executed on the VM's real interactive console session (developer, session 1).
Branch session/win-port @ Task 14. Evidence is screenshots that were
visually inspected and ffprobe dimension/codec checks.

1. Suite green on Windows — PASS. `381 passed, 16 skipped` (offscreen,
   ffmpeg on PATH). Baseline was 329/16; +52 new WS-E tests. Skips are
   the pre-existing POSIX/portal/D-Bus honest skips (unchanged at 16).
2. App launches with tray — PASS. `wondershot.cli.main([])` via schtasks
   /it: two python.exe in Console session 1; app.log clean; console
   screenshot shows the full gallery window (toolbar Capture/Record/
   Camera/Share, annotation tools, Properties panel, "No screenshots
   yet") and the tray icon.
3. Hotkey fires a capture — PASS. keybd_event Ctrl+Shift+PrintScreen →
   the desktop dims under the region overlay (frozen-grab + dim visible
   in the console screenshot); Esc cancels silently (no stray file).
4. Region capture produces a correct PNG — PASS. Hotkey + mouse_event
   drags: 400x300 drag → 401x301 PNG; 350x150 drag → 351x151 PNG with
   blue wallpaper visible at the edge (real pixels, exact crop, not full
   screen).
5. Fullscreen + window capture produce correct PNGs — PASS. Fullscreen
   via the running app's single-instance socket (`--fullscreen`):
   1280x800 PNG of the real desktop. Active-window via
   WinCaptureManager.capture_active_window() on the desktop:
   active_window_rect=(129,130,1115,628), crop PNG = 1115x628 = exactly
   the foreground window frame (DWM shadow excluded), not the desktop.
6. Recording produces a playable mp4 — PASS via AUTOMATIC ddagrab→gdigrab
   fallback (re-verified 2026-06-07 through the real probe path — no
   forced builder). ddagrab filter present but fails at runtime on the VM
   (no D3D11VA device); the recorder now detects the early death and
   transparently relaunches gdigrab. Real path: create_screen_recorder()
   → started → cand_idx advances 0→1 → finished, Recording_*.mp4 =
   h264 1280x800 3.13s (ffprobe). Mic: no dshow audio devices on the VM →
   video-only. (This closes the review's BIG finding: the fallback was
   advertised but didn't exist; it does now, with 4 regression tests.)
7. Editor annotates + sidecar persists — PASS. On Windows, offscreen:
   `test_editor test_sidecar test_editor_sidecar test_items_serialize`
   = 63 passed (case-insensitivity + backslash paths exercised).

Deviations from the plan recorded in the plan's VERIFICATION-LOG.
