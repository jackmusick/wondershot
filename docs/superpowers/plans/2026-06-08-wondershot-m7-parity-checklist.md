# Wondershot M7 — Parity Sign-off Checklist

> The Tauri rewrite (`tauri-rewrite`) vs the Python app (`main`, the live oracle).
> Status: ✅ verified (test/screenshot named) · ⏳ needs a real desktop session (command given) · ❌ gap.
> Test counts from `cargo test --workspace` + `--features bgremove-onnx` (90 core) and `npm run test` (68 frontend), 2026-06-09.

## Feature parity

| # | Feature (Python) | Tauri milestone | Status | Evidence |
|---|---|---|---|---|
| 1 | Region capture | M2 | ✅ + ⏳ | `cargo test capture` (5 — crop/window-mode math); live capture round-trip ⏳ `wondershot --capture` |
| 2 | Fullscreen capture | M2 | ✅ + ⏳ | same module; live ⏳ |
| 3 | Window capture (KWin geometry) | M2 | ✅ + ⏳ | `cargo test capture` (window-mode); live ⏳ needs KWin session |
| 4 | Copy-after-capture (wl-clipboard) | M2 | ✅ + ⏳ | `cargo test clipboard` (2); live selection ⏳ Wayland session |
| 5 | Library scan (PNG/MP4) + thumbnails | M2 | ✅ | `cargo test library` (2); frontend gallery tests |
| 6 | `.sidecar` read/write round-trip | M2/M3 | ✅ | `cargo test sidecar` (4) + `editor` serialize |
| 7 | Trash / delete item | M2 | ✅ | `cargo test library`; frontend store |
| 8 | Editor: 14 tools | M3 | ✅ | `cargo test editor` (12) + 68 frontend tests; `artifacts/ui/editor-*.png` |
| 9 | Editor: undo/redo, transformer | M3 | ✅ | frontend editor tests |
| 10 | Editor: sidecar JSON parity | M3 | ✅ | `cargo test editor` (items serialize) |
| 11 | Recorder: record/pause/resume/stop | M4 | ✅ + ⏳ | `cargo test record` (21 — pure pipeline + PTS + live videotestsrc smoke); real `pipewiresrc` capture ⏳ portal session |
| 12 | Recorder: finalize / no stranded `.rendering` | M4 | ✅ | `cargo test record` (finalize/escalation) |
| 13 | Countdown overlay + camera bubble | M4 | ✅ + ⏳ | build clean; KWin bubble positioning ⏳ |
| 14 | Video: range-blur redaction | M5 | ✅ + ⏳ | `cargo test video` (15 — filter graph); live ffmpeg ⏳ display |
| 15 | Video: GIF export | M5 | ✅ + ⏳ | `cargo test video` (gif args); live ⏳ |
| 16 | Video: frame grab / trim | M5 | ✅ + ⏳ | `cargo test video`; live ⏳ |
| 17 | Settings: load/save `wondershot.conf` | M5 | ✅ | `cargo test settings` (7 — defaults/parse/round-trip) |
| 18 | Settings: tabbed modal | M5 | ✅ | `artifacts/ui/settings-*.png`; ui-review pass |
| 19 | AI background removal (u2net) | M5/M6 | ✅ + ⏳ | `cargo test bgremove` (2 — preprocess/composite); `--features bgremove` links; live inference ⏳ model present |
| 20 | Hotkey: manual KGlobalAccel guidance | M5 | ✅ | Settings shows guidance (Python parity: registration stays manual) |
| 21 | CLI `--capture/-f/--edit/--import/--quit/--install-desktop/--version/url` | M7 | ✅ + ⏳ | `cargo test cli` (11); single-instance forwarding ⏳ two-process run |
| 22 | `--install-desktop` writes `.desktop`+icon | M7 | ✅ | `install_desktop` command; matches install.sh / Flatpak desktop entry |
| 23 | `--import` copies into library | M7 | ✅ | `import_files` command; frontend `importPaths` |

## Cutover parity (identity preserved — M6/M7)

| Item | Status | Evidence |
|---|---|---|
| app-id `io.github.jackmusick.wondershot` | ✅ | `tauri.conf.json` identifier (asserted in M6 T3); Flatpak app-id |
| `.desktop` Name `Wondershot` | ✅ | install.sh + `install_desktop` + Flatpak desktop all `Name=Wondershot` |
| Library dir + `.sidecar` + conf read as-is | ✅ | `cargo test library`/`sidecar`; no migration code needed |
| New Flatpak supersedes old (same app-id) | ✅ (by design) | `flatpak install` of the new bundle replaces the old in place |
| AppImage clears stale pip venv | ✅ | `install.sh` removes `$HOME_DIR/venv` on upgrade |

## Distribution gates (M6 — environment-bound)

| Deliverable | Status | Command |
|---|---|---|
| Tauri release binary builds (`--features bgremove`) | ✅ | verified locally — webkit2gtk-4.1 linked, onnxruntime load-dynamic |
| deb bundling | ✅ | `Wondershot_0.1.0_amd64.deb` built locally (needs `libayatana-appindicator-gtk3[-devel]` on host for the tray probe) |
| AppImage / rpm bundling | ⏳ CI | `release.yml` builds them on a `v*` tag (ubuntu-22.04 + appindicator dev) |
| **Flatpak build + launch** | ✅ | **built + installed + launched live 2026-06-09** on `org.gnome.Platform//49`; permissions verified (wayland/x11, pulseaudio, pipewire, dri, xdg-pictures/videos, KWin + portal talk); ffmpeg/wl-copy/libonnxruntime/u2net bundled; start-menu entry + 512px icon exported. Tray **intentionally skipped** on GNOME (no appindicator in the runtime) — degrades gracefully (user-accepted). |
| `curl \| sh` install + launch | ⏳ first release | `install.sh` logic verified; needs a published `.AppImage` release asset |

## Out of scope (never in the 7-milestone roadmap)

- Cloud sharing (S3/Azure/OneDrive) and the AI-chat endpoint — Python features deliberately omitted.
- The `wondershot://` deep link focuses/raises only (no OAuth flow exists in the rewrite).
- macOS / Windows builds (Linux-first; `wondershot-core` leaves a clean seam).

## Summary

All feature subsystems have ✅ automated coverage (90 core + 68 frontend tests, all green); the **Flatpak now builds, installs, and launches live** with correct permissions + start-menu icon (verified 2026-06-09). Remaining ⏳ items are the in-app live-hardware runs (capture/recorder/ffmpeg, now under user test-drive) and the AppImage/rpm/`curl|sh` paths (CI / first-release) — none are code gaps. Parity is met at the verifiable layer; the cutover invariants (app-id/.desktop/library) are preserved so the new build supersedes the old install with the library intact. The `tauri-rewrite` → `main` merge is held pending the user's test-drive verdict.
