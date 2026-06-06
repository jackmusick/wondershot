# Roadmap

## Done (v0.1.x)

- Capture via Spectacle/portal, gallery carousel with drag-out, markup
  editor (arrows, shapes, pen, highlight, text, steps, pixelate, crop,
  cut-out V/H), properties sidebar, resize grips, any-tool grabbing
- Video playback (QVideoWidget; frozen-frame overlay while editing —
  Wayland's video subsurface sits above all widget painting)
- **Range blur**: draw boxes on a paused frame, set time spans on the
  timeline bar (edge grips / move / scrub-while-dragging), multiple
  regions each with their own span, one ffmpeg pass → `-redacted.mp4`
- GIF conversion (animated preview, loop, GIF badge)
- Multi-folder library (Screenshots + ~/Videos/Screencasts), settings
  dialog, tray, single-instance CLI, hotkey via DE shortcut

## Next up — recorder ("the Loom thing")

Not started yet. Design is settled, work is real:

1. **Screen recording**: xdg-desktop-portal ScreenCast → PipeWire node →
   encode (GStreamer pipeline or ffmpeg with pipewire input). Start/stop
   from tray + hotkey; output lands in the screenshot library (solves
   "why a separate videos folder" — Spectacle picks its own folder, our
   recorder won't).
2. **Camera bubble**: frameless always-on-top circular window rendering
   QCamera (QtMultimedia), draggable, portrait crop. The recording
   captures it for free because it's on screen — no compositing.
3. **Audio**: microphone via the same pipeline (`-f pulse` /
   pipewiresrc audio); device pickers (camera, mic) in Settings.
4. Prototype risk to retire first: portal ScreenCast handshake +
   PipeWire fd → encoder, in a throwaway script before wiring UI.

## Editor backlog

- Rotation handles on annotations (rotate is not currently possible)
- Text: vertical/horizontal centering inside a dragged box, edge snapping
  (Snagit behavior); background/outline chips for text readability
- Style-change undo entries (color/width tweaks aren't undoable)
- Blur tool variant alongside pixelate
- Step-number renumbering when one is deleted mid-sequence

## Video backlog

- Blur strength slider in Settings (currently boxblur=14)
- Trim / cut ranges (same enable-range machinery as blur)
- GIF conversion options (fps, scale, time range)
- True blur preview in the frost (per-frame pixelation of the region)

## Known platform landmines (hard-won)

- KGlobalAccel D-Bus: malformed `setShortcutKeys` call aborts KWin
  6.6.5 (compositor crash!). Never auto-register; report upstream.
- Wayland: video renders in a native subsurface above ALL widget
  painting — overlays must hide the surface and self-paint the frame.
- QGraphicsVideoItem: CPU paint path, lags 60fps VP9; QVideoWidget +
  QOpenGLWidget viewport renders blank on Wayland.
- libx264 cannot go into a .webm container — transcode to .mp4.
- QListView uniformItemSizes caches the first measurement — never let
  it measure an icon-less item.
