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

```powershell
irm https://raw.githubusercontent.com/jackmusick/wondershot/main/Install-Wondershot.ps1 | iex
```

Installs the latest Rust/Tauri Windows release silently. Re-run the
same command to update. Or download the `.msi` / `*-setup.exe` asset
from [Releases](https://github.com/jackmusick/wondershot/releases)
yourself.

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

### Linux (one-liner, latest main)

```sh
curl -fsSL https://raw.githubusercontent.com/jackmusick/wondershot/main/install.sh | sh
```

Installs user-locally (no sudo) and tells you if any system packages
are missing. The installer validates the downloaded app before reporting
success, so stale legacy bundles are refused instead of silently installed.
Re-run the same command to update.

### From source (developers)

```powershell
git clone https://github.com/jackmusick/wondershot && cd wondershot
npm ci
npm run tauri dev
```

Linux needs GStreamer with the PipeWire plugin, ffmpeg, and a Rust
toolchain. On Fedora/KDE, the native build packages are:

```sh
sudo dnf install ffmpeg gstreamer1-plugins-ugly \
  gstreamer1-devel gstreamer1-plugins-base-devel \
  webkit2gtk4.1-devel libayatana-appindicator-gtk3-devel
```

Run the Rust/frontend suites with `cargo test --workspace` and
`npm run test`.

## Platform notes

- **Linux**: best on KDE Plasma/Wayland (instant Spectacle region
  picker, window rules, auto-size-to-window); works anywhere
  xdg-desktop-portal does. The capture hotkey is bound in your DE's
  shortcut settings (`wondershot --capture`) — Plasma's shortcut API
  has a compositor-crash landmine, so we won't auto-register until
  that's provably safe.
- **Windows**: capture/record/hotkey are native; the hotkey is set in
  Settings → General. The capture picker supports full screen, drag
  selection, and hover-to-target windows. Recording uses native FFmpeg
  backends for screen, region, microphone, and camera-bubble workflows.

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

[AGPL-3.0-or-later](LICENSE) — free to use, modify, and redistribute;
derivatives must stay open source.
