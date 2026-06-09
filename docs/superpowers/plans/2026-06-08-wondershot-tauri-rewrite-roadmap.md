# Wondershot Tauri/Svelte Rewrite — Milestone Roadmap

> Spec: `docs/superpowers/specs/2026-06-08-wondershot-tauri-rewrite-design.md`
> Branch: `tauri-rewrite` (Python stays on `main` until cutover)

This rewrite is decomposed into seven milestones. **Each milestone is its own detailed
plan** (`docs/superpowers/plans/2026-06-08-wondershot-<Mn>-<name>.md`) and produces
working, testable software on its own. Write the next milestone's detailed plan only when
the previous one lands — its tasks depend on decisions made building the predecessor.

## Execution model per milestone

| Milestone | Shape | Why |
|---|---|---|
| M1 Foundation + UI-review harness | **Sequential** (single agent) | Scaffolding has hard ordering; nothing to fan out yet |
| M2 Capture + clipboard + library | **Workflow pipeline** | Each backend (spectacle/portal/kwin/wl-copy) is an independent build→test chain |
| M3 Editor (14 tools) | **Workflow pipeline** | Each tool = independent build→screenshot→visual-critique chain |
| M4 Native recorder | **Sequential** (single focused agent) | Highest-risk port; ordering-dependent; do not fan out |
| M5 Video + settings + bg-removal | **Workflow pipeline** | Three independent subsystems |
| M6 Packaging (Flatpak + curl\|sh) | **Sequential** | Cutover ordering; one release pipeline |
| M7 Cutover + parity sign-off | **Sequential** | Final verification against the Python oracle |

The **autonomous UI-review loop** built in M1 (screenshot → vision-critique → structured
findings) is reused as a workflow stage in M2, M3, and M5.

## Milestones

### M1 — Foundation + UI-review harness  *(✅ COMPLETE — tag `m1-foundation`)*
SvelteKit 2 / Svelte 5 / Tauri 2 scaffold on the branch; copy + retint `tokens.css`; app
shell (sidebar=library list, header=capture actions, content view-switcher) with mocked
data; mockable IPC seam; Playwright screenshot harness (light/dark); wonderblob reference
shots; vision-critique workflow stage; minimal Rust (health command, tray stub,
single-instance); Vitest. **Exit:** `npm run build` succeeds, the shell screenshots in
both themes, and the critique stage returns findings.

### M2 — Capture + clipboard + library  *(✅ COMPLETE — tag `m2-capture`; live capture round-trip pending an interactive Wayland session)*
`wondershot-core` crates: `capture` (spectacle subprocess + `ashpd` portal + KWin
geometry via `zbus`), `clipboard` (`wl-clipboard-rs`), `library` (scan existing PNG/MP4 +
`.sidecar` read/write, trash). Wire `capture_*`, `copy_image`, `list_library`,
`save_sidecar`, `load_sidecar`, `trash_item` commands + `capture://` events. Real captures
flow into the library sidebar. **Exit:** region/full/window capture → thumbnail → clipboard,
existing library loads unchanged. Oracle: port `tests/` capture/library assertions to `cargo test`.

### M3 — Editor (Konva, 14 tools)  *(✅ COMPLETE — tag `m3-editor`)*
Deferred to a later pass (noted): multi-base re-edit stack (bases>1 cross-session re-edit of crops/cutouts — M3 writes base.0 only); drag-to-swap step numbers; text drag-to-set-box-width; live effects preview (state is saved, not previewed). Interactive canvas UX validated by JSON-parity tests + screenshots, not headless click-tests.
Konva `Stage` in the content view; tool rail; 14 tools (select, arrow, line, rect,
ellipse, pen, highlighter, text, step-numbers, pixelate, blur, crop, cutout V/H);
`Transformer` handles; snapshot undo/redo; serialize to existing `.sidecar` JSON. Each
tool built as a pipeline item (build → screenshot → visual-critique). **Exit:** every tool
round-trips through `.sidecar` and matches the Python editor's output on a fixture set.

### M4 — Native recorder  *(✅ COMPLETE — tag `m4-recorder`)*
Verified in tests: pure pipeline string + PTS/clock/escalation math; the gstreamer-rs runtime via a videotestsrc→mp4 smoke test AND a live pause→resume→stop PTS-rewrite test; portal/commands/countdown/bubble/Record-control build clean. **Human-present check pending** (the one manual gate): real `pipewiresrc` screen capture through the portal picker, and the GRACE/KILL force-stop + watchdog-error branches (can't fault-inject headlessly). Deferred: mic description→pulse-name resolution, `have_webrtcdsp` element probe (hardcoded false), Wayland bubble KWin positioning. Local dev needs `gstreamer1-devel`+`gstreamer1-plugins-base-devel` (installed); the Flatpak gets GStreamer from the KDE runtime.
`wondershot-core/record`: `ashpd` ScreenCast → `pipewire-rs` fd → `gstreamer-rs` pipeline
(x264+AAC → mp4); pause/resume PTS offset + EOS-finalize escalation ladder ported from
`record.py`; `start_recording`/`stop`/`pause`/`resume` + `recording://` events; countdown
overlay + camera bubble as frameless windows. **Exit:** record→pause→resume→stop produces a
valid mp4; finalize never strands a `.rendering` temp. Highest-risk milestone — single agent.

### M5 — Video + settings + bg-removal  *(✅ COMPLETE — tag `m5-video-settings`)*
M5 notes: bg-removal's `ort`/ONNX inference is **feature-gated `bgremove-onnx` (off)** — the `ort-sys` rc binary-download build script is currently broken upstream (ureq `_tls`); the pure preprocess/composite is tested and the UI disables gracefully. Resolving the ONNX runtime build (via `ort` load-dynamic against a bundled libonnxruntime) + bundling the u2net model is folded into **M6 packaging**. Video blur/gif/frame and the redaction UI are built; live ffmpeg runs need a display-present manual check.
`video` (ffmpeg blur filter graph, GIF export, frame grab) + VideoPlayer UI; `settings`
(serde to existing conf) + tabbed Settings modal; `bgremove` (`ort` + u2net ONNX) +
Output-effects UI. Three independent subsystems → workflow pipeline. **Exit:** GIF export,
range-blur redaction, settings persistence, and bg-removal all match Python behavior.

### M6 — Packaging
Flatpak manifest for the Tauri app (resolve `webkitgtk-6.0` in the KDE runtime; reuse
ffmpeg/x264 modules; bundle u2net model); Tauri bundler `.rpm`/AppImage; `install.sh`
`curl|sh` path. **Exit:** a Flatpak and a `curl|sh` install both launch the app.

### M7 — Cutover + parity sign-off
Same app-id/`.desktop`/library dir so the new build supersedes the Flatpak and removes the
old pip venv; full parity pass against the Python app (every feature in the spec's parity
list); merge `tauri-rewrite` → `main`. **Exit:** parity checklist green; cutover install
replaces the old one with the library intact.
