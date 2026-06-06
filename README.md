# grabbit 🐇

Snagit-style screenshot tool for Linux/Wayland: **capture → gallery → drag out**.

Built for KDE Plasma on Wayland, works anywhere xdg-desktop-portal does.

## Features

- **Snagit-style layout** — big markup canvas on top, filmstrip carousel of
  your screenshot library along the bottom. Arrow through shots; clicking a
  thumbnail loads it in the editor. **Drag a thumbnail straight into** Slack,
  a browser upload, email, Dolphin, anything that accepts file drops.
- **Markup editor** — arrows, lines, boxes, ellipses, freehand pen, highlighter,
  text, numbered step stamps, pixelate (redact), with full undo/redo.
- **Crop** and Snagit-style **cut out** (remove a horizontal or vertical band
  and join the halves).
- **Capture** via Spectacle's native region picker on KDE (instant, no
  prompts), portal fallback elsewhere. Copies to clipboard automatically.
- Tray icon, hide-to-tray gallery, optional always-on-top pin.
- Library is just a folder (`~/Pictures/Screenshots` by default) — shots from
  Spectacle or anything else show up too.

## Install

```sh
pipx install git+https://github.com/jackmusick/grabbit  # or: pip install .
grabbit --install-desktop   # launcher + icon
grabbit                      # starts tray + gallery
```

For a global capture hotkey, bind a key to `grabbit --capture`
(KDE: System Settings → Shortcuts → Add New → Command). The command talks to
the running instance over a local socket, so it fires instantly.

> Why no automatic hotkey registration? On Plasma 6 the shortcut daemon runs
> inside KWin, and a malformed KGlobalAccel D-Bus call can abort the
> compositor (observed on kwin 6.6.5). grabbit stays out of that API until
> it can do so provably safely.

## CLI

```
grabbit                 show gallery (or start the app)
grabbit -c, --capture   capture a region
grabbit -f, --fullscreen capture the whole screen
grabbit -e FILE         open FILE in the markup editor
grabbit -i FILE...      import images into the library
grabbit --quit          stop the running instance
```

All commands talk to the running instance, so they're cheap to bind to keys.

## Editor keys

| Key | Tool |
|-----|------|
| V | Select / move |
| A | Arrow |
| L | Line |
| R | Box |
| E | Ellipse |
| P | Pen |
| H | Highlighter |
| T | Text |
| N | Step number |
| X | Pixelate |
| C | Crop |
| U | Cut out (drag across; direction picks the band) |

Ctrl+Z/Ctrl+Shift+Z undo/redo · Ctrl+S save · Ctrl+C copy flattened image ·
Ctrl+wheel zoom · Ctrl+0 actual size · Ctrl+9 fit.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/pytest
.venv/bin/grabbit --selftest /tmp/shots   # offscreen UI renders
```

MIT licensed.
