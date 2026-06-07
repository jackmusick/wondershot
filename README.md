# Wondershot

**Capture → mark up → drag it into your doc.** A Snagit-inspired
screenshot and screen-recording tool for Linux and Windows.

## Why this exists

If you write a lot of technical documentation, the loop you live in is:
capture a region, annotate it (arrows, boxes, step numbers, redaction),
and get it *into the document you're writing* — ideally by dragging it
straight from the editor into your wiki, Slack, or email. Almost no
screenshot tool delivers that whole flow, and on Linux none do.
Flameshot comes closest, but handing the image off to a separate editor
breaks the loop. Wondershot's gallery/editor *is* the workflow: a big
markup canvas, your screenshot library as a filmstrip underneath, and
every thumbnail drags out as a file.

The second gap is **lightweight video**. Producing instructions often
means recording a screen where something sensitive scrolls past — and
nobody building docs has time to stand up a clean demo environment for
every recording. Wondershot records your screen (with an optional
camera bubble), then lets you **box-blur regions of the video across
time spans, right in the player** — one pass, one file out. In Snagit
and friends that's an add-on or a second editing app; here it's the
point.

## Features

**Stills**
- Region / full-screen / active-window capture; scrolling capture
  (Linux); capture hotkey configurable in Settings
- Markup: arrows, lines, boxes, ellipses, pen, highlighter, text,
  numbered steps, pixelate, blur, crop, cut-out — all objects stay
  editable layers, with full undo/redo
- Annotations persist: reopen a library image later and your objects
  are still live (sidecar files; no save prompts, ever)
- Effects: rounded corners, bottom fade; background removal (local AI)
- Drag any thumbnail straight into Slack, a browser upload, your wiki
- Post-capture quick-action bar: Edit / Copy / Save as / Share / Trash

**Video**
- One-click screen recording (mic + camera bubble optional)
- Range blur: pause, box the sensitive bits, set time spans on the
  timeline, render — `-redacted.mp4` lands next to the original
- GIF conversion with fps/width/time-range options

**Sharing**
- One Share button: S3-compatible storage, Azure Blob, or
  OneDrive/SharePoint — returns a time-limited link on your clipboard

**AI (bring your own endpoint)**
- Point Settings → AI at any OpenAI-compatible endpoint
- AI Redact: finds sensitive text and pixelates it (as editable objects)
- AI Simplify: replaces UI regions with clean editable blocks

## Install

### Windows

Download `WondershotSetup-<version>.exe` from
[Releases](https://github.com/jackmusick/wondershot/releases) and run
it. Fully self-contained — no runtimes to install. Supports
`/VERYSILENT` for unattended installs.

> The installer isn't code-signed yet, so SmartScreen will interject —
> **More info → Run anyway**.

### Linux (Flatpak)

Download `wondershot.flatpak` from
[Releases](https://github.com/jackmusick/wondershot/releases), then:

```sh
flatpak install wondershot.flatpak
```

One bundle, zero distro packages. (Flathub submission is planned —
then it's just `flatpak install wondershot` with automatic updates.)

### From source (developers)

```sh
git clone https://github.com/jackmusick/wondershot && cd wondershot
python -m venv --system-site-packages .venv   # system gi/GStreamer
.venv/bin/pip install -e .
.venv/bin/wondershot
```

Linux needs `python3-gobject`, GStreamer with the PipeWire plugin, and
ffmpeg from your distro. Run the suite with `pytest tests/`.

## Platform notes

- **Linux**: best on KDE Plasma/Wayland (instant Spectacle region
  picker, window rules, auto-size-to-window); works anywhere
  xdg-desktop-portal does. The capture hotkey is bound in your DE's
  shortcut settings (`wondershot --capture`) — Plasma's shortcut API
  has a compositor-crash landmine, so we won't auto-register until
  that's provably safe.
- **Windows**: capture/record/hotkey are native; the hotkey is set in
  Settings → General. Cursor-in-capture and a window picker are in
  progress.

## CLI

```
wondershot                  show gallery (or start the app)
wondershot -c, --capture    capture a region
wondershot -f, --fullscreen capture the whole screen
wondershot -e FILE          open FILE in the markup editor
wondershot -i FILE...       import images into the library
wondershot --quit           stop the running instance
```

All commands talk to the running instance over a local socket, so
they're cheap to bind to keys.

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
| N | Numbered step |
| X | Pixelate |
| B | Blur |
| C | Crop |
| U / Shift+U | Cut out (vertical / horizontal) |

## License

MIT
