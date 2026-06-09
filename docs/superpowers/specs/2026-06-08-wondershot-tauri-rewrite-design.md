# Wondershot → Tauri + Svelte Rewrite — Design

**Date:** 2026-06-08
**Status:** Approved design, pending implementation plan
**Branch:** `tauri-rewrite` (Python app stays on `main` until cutover)

## Motivation

Wondershot today is Python + PySide6 (Qt6). It looks at home on Linux/KDE — because
KDE *is* Qt and the app blends in by accident — but lands in the uncanny valley on
Windows (Qt Fusion style: wrong fonts, metrics, no native chrome) and would be worse
on macOS, which has no build today. Qt's structural failure mode is "native-ish but
wrong" on every platform that isn't already Qt. A web UI owns its own aesthetic and
looks identically intentional everywhere — which is the actual goal.

The sibling app `../wonderblob` (SvelteKit 2 / Svelte 5 / Tauri 2, plain scoped CSS
driven by one `tokens.css`, a framework-free `wonderblob-core` Rust crate) already
proves the target stack and ships the exact design language we want to clone.

## Goals

- Full feature + UI parity with the current Python app on **Linux first**.
- Adopt wonderblob's **entire design language** (rich colors, two-plane dark
  backgrounds: sidebar `#141416` / content `#29292c`) by copying `tokens.css`.
- **All-Rust backend** — no Python runtime in the shipped artifact.
- Cutover: the new install **naturally replaces** the existing Flatpak / pip install
  (same app-id, `.desktop`, and library dir). Keep a Flatpak; add `curl | sh`.
- Existing captured library (PNG/MP4 + `.sidecar` annotation JSON + settings conf)
  keeps loading unchanged — nothing already captured is orphaned.

## Non-goals (this phase)

- Windows and macOS builds. The architecture leaves a clean seam for them
  (`wondershot-core` is framework-free), but they are later milestones.

## Keystone decisions

| Decision | Choice | Rationale |
|---|---|---|
| Platform order | Linux-first, cut over the Flatpak | User's daily driver; fastest dogfood |
| Distribution | Keep Flatpak **and** add `curl \| sh` | Flatpaks are nice; curl is convenient |
| Linux recorder | **Native Rust** (`ashpd` + `pipewire-rs` + `gstreamer-rs`) | Single-language build; mature crates |
| AI bg-removal | **Native Rust** (`ort` crate + u2net ONNX) | Consistent all-Rust; ONNX-in-Rust is well-trodden |
| Editor engine | **Konva** (svelte-konva) | Scene-graph model maps ~1:1 onto `QGraphicsScene` |
| Execution shape | Branch in repo, Python parallel on `main` until parity | Side-by-side parity oracle; no loss of daily driver |

## Architecture

### Repo layout (branch `tauri-rewrite`)

```
wondershot/
  src/                      # SvelteKit 2 / Svelte 5 frontend
    lib/styles/tokens.css   # copied from wonderblob, retinted
    lib/components/         # CaptureRail, Gallery, Editor, VideoPlayer, Settings,
                            #   CameraBubble, CountdownOverlay, ContextMenu, Toast
    routes/+layout.svelte   # theme apply (data-theme on <html>)
    routes/+page.svelte     # sidebar + content shell
  src-tauri/
    src/commands.rs         # thin invoke glue
    src/main.rs             # app setup, tray, single-instance, event wiring
    tauri.conf.json
  crates/
    wondershot-core/        # ALL logic, framework-free, cargo-testable
      capture/ record/ clipboard/ hotkey/ video/ bgremove/ library/ settings/
  wondershot/               # existing Python — untouched on this branch
```

`wondershot-core` holds all real logic (framework-free, unit-tested); `src-tauri` is
glue only. This mirrors wonderblob's `wonderblob-core` split and is the seam where a
future Windows/macOS backend slots in.

### Rust command surface (Svelte `invoke` targets)

| Command(s) | Implementation |
|---|---|
| `capture_region` / `capture_fullscreen` / `capture_window` | spawn `spectacle -b -n` (KDE); `ashpd` portal Screenshot fallback; KWin geometry via `zbus` |
| `start_recording` / `stop` / `pause` / `resume` | native Rust: `ashpd` ScreenCast → `pipewire-rs` fd → `gstreamer-rs` pipeline (x264+AAC → mp4); pause/resume PTS offset + EOS-finalize escalation ladder ported from `record.py` |
| `copy_image` | `wl-clipboard-rs` (focus-independent on Wayland), `arboard` elsewhere |
| `bind_hotkey` / `rebind_hotkey` | `KGlobalAccel` via `zbus` |
| `apply_video_blur` / `export_gif` / `grab_frame` | spawn bundled `ffmpeg` |
| `remove_background` | native Rust: `ort` crate + bundled u2net ONNX model |
| `list_library` / `save_sidecar` / `load_sidecar` / `trash_item` | `wondershot-core/library`; reads existing PNG/MP4 + `.sidecar` JSON unchanged |
| `get_settings` / `set_settings` | serde to `~/.config/wondershot/`; reads existing conf for continuity |

### Events (Rust → Svelte, mirroring Qt signals)

`recording://tick`, `recording://state`, `capture://done`, `capture://failed`.

Single-instance + tray use Tauri's `single-instance` plugin and native tray, replacing
the `QLocalServer` socket and `QSystemTrayIcon`.

## UI shell

Two-plane layout from wonderblob. **Sidebar** (`--bg-sidebar`): capture actions
(Region / Full screen / Window / Scrolling), Record control with live timer, library
navigation (recent / by date), settings gear pinned bottom. **Content** (`--bg-content`)
behind a 44px toolbar: a view-switcher across Gallery / Editor / Video.

```
┌────────────┬─────────────────────────────────────┐
│ ▢ Region   │  [toolbar: tools · color · stroke]   │
│ ▢ Full     ├─────────────────────────────────────┤
│ ▢ Window   │                                     │
│ ▢ Scroll   │     Gallery │ Editor │ Video         │
│ ● Record   │     (Konva stage when editing)       │
│  00:14     │                                     │
│ ──────────  │                                     │
│ Library     │                                     │
│  Today      ├─────────────────────────────────────┤
│ ⚙ Settings │  [filmstrip carousel]                │
└────────────┴─────────────────────────────────────┘
```

### Components

- **CaptureRail** — sidebar; capture/record actions + library nav.
- **Gallery** — carousel filmstrip + selected-item view.
- **Editor** — Konva `Stage` + tool rail + color/stroke/font controls. 14 tools
  (select, arrow, line, rect, ellipse, pen, highlighter, text, step-numbers, pixelate,
  blur, crop, cutout V/H). Konva nodes + `Transformer` handles; undo/redo as a snapshot
  stack; serialize to existing `.sidecar` JSON. Pixelate/blur = filtered raster nodes;
  crop/cutout = stage transforms.
- **VideoPlayer** — HTML5 `<video>` + timeline redaction boxes + GIF export dialog.
- **Settings** — tabbed overlay using wonderblob's `.panel` modal pattern.
- **CameraBubble** / **CountdownOverlay** — separate frameless Tauri windows. Bubble
  uses `getUserMedia` directly (no Rust webcam plumbing); the on-screen bubble is
  captured by the screen recorder just as today.
- **ContextMenu**, **Toast**.

### Data flow

Svelte stores: `captures`, `view`, `activeItem`, `recording`, `settings`. `invoke` for
commands, `listen` for events. `capture://done` pushes a thumbnail and opens the editor;
`recording://tick` drives the sidebar timer.

## Packaging & cutover

- **Flatpak:** Tauri webview needs `webkitgtk-6.0`; reuse existing ffmpeg/x264 Flatpak
  modules, add the u2net model, use the KDE runtime's GStreamer for the recorder.
- **curl | sh:** Tauri bundler emits `.rpm`/AppImage; `install.sh` pulls the latest
  release asset into `~/.local`.
- **Cutover:** same `app-id` (`io.github.jackmusick.wondershot`), `.desktop` name, and
  library dir, so the new build supersedes the Flatpak and removes the old pip venv.
- **Migration:** library + `.sidecar` + settings conf read as-is.

## Testing

- `cargo test` in `wondershot-core`: ffmpeg arg/filter builders, crop & redaction math,
  sidecar serde round-trips, library scan, hotkey chord parsing — **porting existing
  pytest assertions as the oracle**.
- Vitest: stores, editor tool logic.
- Manual integration: capture→clipboard→thumbnail, record→pause→stop→finalize,
  bg-removal, gif export.
- Python pytest suite stays on `main` as a live parity reference.

## Risks

1. **webkitgtk in the KDE Flatpak runtime** — the packaging unknown; verify the runtime
   provides `webkitgtk-6.0` or add a module.
2. **Native recorder port** (`pipewire-rs` / `gstreamer-rs`) — hardest engineering;
   where schedule risk concentrates. The pause/resume PTS handling and EOS-finalize
   ladder must be ported faithfully from `record.py`.
3. **Konva fidelity** on pixelate/blur/cutout raster effects.

The Windows cmd-window flash the user flagged is resolved *by construction* in the
eventual all-Rust Windows backend (`std::process` + `CREATE_NO_WINDOW`), not patched in
the Qt app.
