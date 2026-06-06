# Roadmap

## v2 — recording ("spare no expense" tier)

- **Screen recording with a movable camera bubble** (Loom-style):
  - Frameless, always-on-top, circular camera window — QtMultimedia
    `QCamera` → `QVideoWidget`, draggable anywhere, portrait crop.
  - Screen recording via xdg-desktop-portal **ScreenCast** → PipeWire node →
    GStreamer/ffmpeg encode. The bubble is simply on screen, so the recording
    captures it composited for free — no video mixing needed.
  - Stop button in tray; output lands in the library like any capture.
- **Range blur in videos** (redact a region for a time span):
  - Scrub the existing player, draw a rect on the frame, set in/out points.
  - Each redaction becomes an ffmpeg filter:
    `crop=w:h:x:y,boxblur=12[b];[0][b]overlay=x:y:enable='between(t,IN,OUT)'`
  - Multiple ranges chain into one filtergraph; single re-encode pass,
    saved as a new file in the library.
- Trim / cut for videos (same enable-range machinery).
- GIF conversion options (fps, scale, range) — building on the v1 button.

## v1 polish backlog

- Safe KGlobalAccel registration (typed QtDBus args, test in a nested
  `kwin_wayland --virtual` session first — see hotkey.py for why).
- Resize handles on annotations (arrows/boxes currently move, not reshape).
- Style-change undo entries (color/width tweaks currently aren't undoable).
- Blur tool variant alongside pixelate.
- Report the KWin crash upstream: a `setShortcutKeys` D-Bus call with
  signature `asa(ai)u` from an unprivileged client aborts kwin 6.6.5
  (libdbus `type invalid 0 not a basic type` → `_dbus_abort`).
