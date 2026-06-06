# Roadmap

_Last updated: 2026-06-06_

## Working today (v0.1.x)

**Capture & library**
- Region/fullscreen capture (Spectacle backend, portal fallback)
- Carousel gallery over multiple watched folders (Screenshots +
  ~/Videos/Screencasts), drag-out to any app, skeleton thumbs, rename,
  trash, pin-on-top, settings dialog, tray, single-instance CLI
- Hotkey via KDE custom shortcut → `grabbit --capture`

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
  Settings; full log at ~/.cache/grabbit/recorder.log
- Camera bubble: circular, frameless, always-on-top, drag to move,
  wheel to resize, bottom-right default via KWin window rule;
  toolbar + tray toggle

## Awaiting Jack's verification

- [ ] Recording audio: voice level OK with AGC off? (if too quiet:
      add fixed makeup gain, not AGC)
- [ ] Bubble lands above the taskbar on first open (96px clearance,
      300ms rule-reload delay)
- [ ] Stop button sync (tray + toolbar both reset after either stops)

## Next up (in order)

1. **Sidecar persistence** — annotations stay editable objects when you
   revisit an image (Jack's "can't go back and edit objects").
   Design: library file stays the flattened share-ready PNG; sidecar
   `.grabbit/<name>.json` + original base copy; editor reconstructs
   objects on load.
2. **Recording polish** — countdown before start, region-only
   recording (portal already asks, but in-app choice), pause/resume,
   recording duration in tray tooltip.
3. **Editor backlog** — text alignment + edge snapping in boxes
   (Snagit), style-change undo, blur-tool variant, step renumbering,
   custom rotate cursor polish.
4. **Video backlog** — blur strength setting, trim/cut ranges, GIF
   options (fps/scale/range), true blur preview in the frost.

## Cross-platform position

UI/editor/video/library are pure Qt (portable as-is). OS-specific code
is quarantined in CaptureManager + ScreenRecorder backends; Windows
(native APIs) and macOS (ScreenCaptureKit) become additional backends,
not rewrites. Electron evaluated and rejected: would forfeit native
drag-out, GPU video path, and tray-app footprint without reducing the
per-OS capture work.

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
- QListView uniformItemSizes caches the first measurement — set
  explicit sizeHints/placeholder icons before the view measures.
- Qt movable-drag moves all selected items with the grabber — freeze
  the parent while dragging child grips.
