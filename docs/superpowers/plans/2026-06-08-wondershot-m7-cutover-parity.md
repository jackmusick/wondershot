# Wondershot M7 — Cutover + Parity Sign-off — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (sequential — this is the cutover; ordering matters and it ends in a merge to `main`). Steps use checkbox (`- [ ]`).

**Goal:** Close the remaining behavioral gap with the Python app (CLI/hotkey forwarding, `--install-desktop`, deep link), prove feature + library parity against the Python oracle, make the new build cleanly supersede the old pip/Flatpak install, and merge `tauri-rewrite` → `main`.

**Architecture:** A pure argv parser lands in `wondershot-core` (unit-tested); `src-tauri` dispatches both the launch args and the single-instance *forwarded* args to frontend events (`cli://capture`, `cli://edit`, …) so a global shortcut bound to `wondershot --capture` triggers a capture in the already-running instance — the Python hotkey model. `--install-desktop` writes the user `.desktop` + icon (AppImage path). Cutover keeps the existing app-id / `.desktop` name / library dir (so the Flatpak naturally replaces the old one and the library loads unchanged) and `install.sh` clears the stale Python venv. A parity checklist maps every Python feature to its Tauri verification.

**Tech Stack:** Tauri 2 (`tauri-plugin-single-instance` already wired; `tauri-plugin-deep-link` for `wondershot://`), Rust arg parsing (hand-rolled, no clap — the surface is tiny), the existing `cargo test` oracle ports (M2–M5), Playwright UI review.

**Parity oracle:** the Python `wondershot/cli.py` arg surface (`-c/--capture`, `-f/--fullscreen`, `-e/--edit FILE`, `-i/--import …`, `--quit`, `--install-desktop`, `--version`, positional `url`); `wondershot/__init__.py` launcher-command; the `tests/` pytest suite on `main` as the live reference; the existing captured library + `.sidecar` + `wondershot.conf` as the migration fixture.

---

## Behavioral contract (from cli.py / __init__.py — preserve)

- **CLI surface:** `wondershot [-c|--capture] [-f|--fullscreen] [-e|--edit FILE] [-i|--import F…] [--quit] [--install-desktop] [--version] [URL]`. With no args → launch the window. A second invocation while running **forwards** its args to the running instance (single-instance), which acts on them (capture, edit, import, quit) — it does NOT start a second process.
- **Hotkey model (v1, unchanged):** Wondershot does NOT auto-register a KGlobalAccel shortcut (Plasma 6 landmine). The user binds a global shortcut to `wondershot --capture`; that invocation forwards `--capture` to the running instance. Settings shows this as guidance only (M5 already does).
- **`--capture` / `--fullscreen`:** trigger a region / fullscreen capture (the same path the header buttons call).
- **`--edit FILE`:** open the editor on FILE. **`--import F…`:** copy/scan the given files into the library. **`--quit`:** exit the app. **`URL`** (`wondershot://…`): deep-link; for v1 parity, focus/raise (no cloud-OAuth flow exists in the rewrite — that was out of scope per M5).
- **`--install-desktop`:** write `~/.local/share/applications/io.github.jackmusick.wondershot.desktop` (Exec → this binary, Icon → app-id) + the hicolor icon, then `xdg-mime`/`update-desktop-database` best-effort. Idempotent.
- **Cutover identity (must not change):** app-id `io.github.jackmusick.wondershot`, `.desktop` Name `Wondershot`, library dir + `wondershot.conf` + `.sidecar` read as-is. The new Flatpak (same app-id) replaces the old; the new AppImage reuses `~/.local/share/wondershot` — `install.sh` must remove the **stale Python `venv/`** there so the two don't coexist.

---

## File Structure

```
crates/wondershot-core/src/cli.rs        # PURE argv parser → CliAction enum (unit-tested)
crates/wondershot-core/src/lib.rs         # + pub mod cli;
src-tauri/Cargo.toml                       # + tauri-plugin-deep-link
src-tauri/src/lib.rs                       # dispatch launch args + single-instance argv → cli:// events; deep-link init
src-tauri/src/commands.rs                  # install_desktop command; import_files command
src/routes/+page.svelte (or app shell)     # listen cli://capture|fullscreen|edit|import|quit → existing actions
install.sh                                 # remove stale Python venv on upgrade
docs/superpowers/plans/...-m7-parity-checklist.md   # the parity matrix (filled in)
docs/superpowers/plans/...-roadmap.md       # mark M7 complete on finish
```

---

## Task 1: PURE CLI arg parser in wondershot-core (TDD)

**Files:** `crates/wondershot-core/src/cli.rs` (+ `pub mod cli;` in `lib.rs`). Oracle: `wondershot/cli.py` arg surface.

- [ ] **Step 1: write the failing test** in `cli.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    fn p(args: &[&str]) -> CliAction {
        parse_args(args.iter().map(|s| s.to_string()))
    }
    #[test] fn no_args_launches() { assert_eq!(p(&[]), CliAction::Launch); }
    #[test] fn capture_flag() { assert_eq!(p(&["--capture"]), CliAction::Capture); }
    #[test] fn capture_short() { assert_eq!(p(&["-c"]), CliAction::Capture); }
    #[test] fn fullscreen() { assert_eq!(p(&["-f"]), CliAction::Fullscreen); }
    #[test] fn edit_takes_path() {
        assert_eq!(p(&["--edit", "/a/b.png"]), CliAction::Edit("/a/b.png".into()));
    }
    #[test] fn import_takes_many() {
        assert_eq!(p(&["-i", "/a.png", "/b.png"]),
            CliAction::Import(vec!["/a.png".into(), "/b.png".into()]));
    }
    #[test] fn quit_flag() { assert_eq!(p(&["--quit"]), CliAction::Quit); }
    #[test] fn install_desktop() { assert_eq!(p(&["--install-desktop"]), CliAction::InstallDesktop); }
    #[test] fn version_flag() { assert_eq!(p(&["--version"]), CliAction::Version); }
    #[test] fn url_positional() {
        assert_eq!(p(&["wondershot://open?x=1"]), CliAction::OpenUrl("wondershot://open?x=1".into()));
    }
    #[test] fn ignores_argv0_when_present() {
        // dispatch passes argv WITHOUT argv0; but if a stray flag is unknown, Launch.
        assert_eq!(p(&["--unknown"]), CliAction::Launch);
    }
}
```

- [ ] **Step 2: run, verify it fails** (no `CliAction`/`parse_args`):

Run: `cargo test -p wondershot-core cli`
Expected: FAIL (unresolved).

- [ ] **Step 3: implement** `cli.rs`:

```rust
//! Pure parser for Wondershot's tiny CLI surface (parity with `wondershot/cli.py`).
//! Used both for the launch process args and for the single-instance *forwarded*
//! args of a second invocation. `argv` here EXCLUDES argv0.

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CliAction {
    Launch,
    Capture,
    Fullscreen,
    Edit(String),
    Import(Vec<String>),
    Quit,
    InstallDesktop,
    Version,
    OpenUrl(String),
}

/// Parse already-argv0-stripped args. First recognized intent wins; unknown
/// flags fall back to `Launch` (lenient, matching the desktop-launch case).
pub fn parse_args<I: IntoIterator<Item = String>>(args: I) -> CliAction {
    let args: Vec<String> = args.into_iter().collect();
    let mut i = 0;
    while i < args.len() {
        let a = args[i].as_str();
        match a {
            "-c" | "--capture" => return CliAction::Capture,
            "-f" | "--fullscreen" => return CliAction::Fullscreen,
            "--quit" => return CliAction::Quit,
            "--install-desktop" => return CliAction::InstallDesktop,
            "--version" => return CliAction::Version,
            "-e" | "--edit" => {
                if let Some(p) = args.get(i + 1) {
                    return CliAction::Edit(p.clone());
                }
                return CliAction::Launch;
            }
            "-i" | "--import" => {
                let rest: Vec<String> = args[i + 1..].to_vec();
                if rest.is_empty() {
                    return CliAction::Launch;
                }
                return CliAction::Import(rest);
            }
            s if s.starts_with("wondershot://") => return CliAction::OpenUrl(s.to_string()),
            _ => {}
        }
        i += 1;
    }
    CliAction::Launch
}
```

- [ ] **Step 4: add `pub mod cli;`** to `crates/wondershot-core/src/lib.rs` (next to the other `pub mod` lines).

- [ ] **Step 5: run, verify green:**

Run: `cargo test -p wondershot-core cli`
Expected: PASS (all 11).

- [ ] **Step 6: Commit** — `M7: pure CLI arg parser (CliAction) — parity with cli.py`.

---

## Task 2: Dispatch launch + forwarded args to the frontend

**Files:** `src-tauri/src/lib.rs`, the Svelte app shell (`src/routes/+page.svelte` or the store that owns capture/editor actions), mock. The single-instance plugin is already wired; extend its callback and the startup path.

- [ ] **Step 1: a dispatch helper** in `lib.rs` that maps a `CliAction` to an app effect. Add near the top of `run()`:

```rust
fn dispatch_cli(app: &tauri::AppHandle, action: wondershot_core::cli::CliAction) {
    use tauri::{Emitter, Manager};
    use wondershot_core::cli::CliAction;
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.set_focus();
        let _ = w.show();
    }
    match action {
        CliAction::Capture => { let _ = app.emit("cli://capture", ()); }
        CliAction::Fullscreen => { let _ = app.emit("cli://fullscreen", ()); }
        CliAction::Edit(p) => { let _ = app.emit("cli://edit", p); }
        CliAction::Import(fs) => { let _ = app.emit("cli://import", fs); }
        CliAction::Quit => { app.exit(0); }
        CliAction::InstallDesktop => { let _ = commands::install_desktop(); }
        CliAction::Version => { /* handled before the GUI starts; see step 3 */ }
        CliAction::OpenUrl(_) | CliAction::Launch => { /* focus only */ }
    }
}
```

- [ ] **Step 2: react to forwarded args** — replace the single-instance callback body:

```rust
.plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
    let action = wondershot_core::cli::parse_args(argv.into_iter().skip(1));
    dispatch_cli(app, action);
}))
```

- [ ] **Step 3: handle launch args** — at the very top of `run()`, before building the GUI, short-circuit `--version` (print + exit) so it works headless like Python; then in `.setup(...)` dispatch the launch action:

```rust
pub fn run() {
    let launch = wondershot_core::cli::parse_args(std::env::args().skip(1));
    if launch == wondershot_core::cli::CliAction::Version {
        println!("wondershot {}", env!("CARGO_PKG_VERSION"));
        return;
    }
    if launch == wondershot_core::cli::CliAction::InstallDesktop {
        let _ = commands::install_desktop();
        return;
    }
    tauri::Builder::default()
        // …existing plugins/setup…
        .setup(move |app| {
            // …existing tray setup…
            let handle = app.handle().clone();
            let launch = launch.clone();
            // Defer so the webview is ready to receive the event.
            app.listen_any("app://ready", move |_| dispatch_cli(&handle, launch.clone()));
            Ok(())
        })
        // …
}
```

> The frontend emits `app://ready` once its `cli://*` listeners are attached (avoids a race where the event fires before the listener exists). If the existing shell has no ready signal, add one line in `onMount` after listeners: `emit('app://ready')`.

- [ ] **Step 4: frontend listeners.** In the app shell's `onMount`, after wiring, listen and route to the **existing** actions (the same functions the header buttons / editor open use):

```ts
import { listen, emit } from '@tauri-apps/api/event';
// … inside onMount, after other listeners:
await listen('cli://capture', () => captureRegion());      // existing header action
await listen('cli://fullscreen', () => captureFullscreen());
await listen<string>('cli://edit', (e) => openEditor(e.payload));
await listen<string[]>('cli://import', (e) => importFiles(e.payload));
await emit('app://ready');
```

If `importFiles` doesn't exist yet, add a thin store action calling a new `import_files` command (Task 3 adds the command); otherwise reuse the existing library-add path.

- [ ] **Step 5: mock** — in the browser-dev IPC mock, make `app://ready`/`cli://*` no-ops so dev doesn't crash.

- [ ] **Step 6: build + verify:**

Run: `cargo build -p wondershot && npm run build`
Expected: SUCCESS.

- [ ] **Step 7: UI-review** the shell (no visual change expected, but the goal requires it after a frontend task): run the ui-review workflow; fix any blocker.

- [ ] **Step 8: Commit** — `M7: dispatch launch + single-instance forwarded CLI args to cli:// events (hotkey parity)`.

---

## Task 3: `install_desktop` + `import_files` commands

**Files:** `src-tauri/src/commands.rs`. Oracle: `wondershot/cli.py` lines ~107–131 (desktop install).

- [ ] **Step 1: `install_desktop`** — write the user desktop file + icon, idempotent:

```rust
/// Install the per-user .desktop launcher + icon (parity with Python
/// `--install-desktop`). Idempotent. Best-effort xdg refresh.
#[tauri::command]
pub fn install_desktop() -> Result<(), String> {
    use std::io::Write;
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let data = std::env::var("XDG_DATA_HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            std::path::PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".local/share")
        });
    let apps = data.join("applications");
    std::fs::create_dir_all(&apps).map_err(|e| e.to_string())?;
    let desktop = format!(
        "[Desktop Entry]\nType=Application\nName=Wondershot\n\
         Comment=Screenshot & screen-recording with annotation\n\
         Exec={} %U\nIcon=io.github.jackmusick.wondershot\nTerminal=false\n\
         Categories=Utility;Graphics;\nStartupNotify=true\n",
        exe.display()
    );
    let path = apps.join("io.github.jackmusick.wondershot.desktop");
    let mut f = std::fs::File::create(&path).map_err(|e| e.to_string())?;
    f.write_all(desktop.as_bytes()).map_err(|e| e.to_string())?;
    let _ = std::process::Command::new("update-desktop-database").arg(&apps).status();
    Ok(())
}
```

- [ ] **Step 2: `import_files`** — copy the given files into the library dir (parity with `--import`), reusing the M2 library path:

```rust
/// Copy `paths` into the library dir (parity with Python `--import`). Returns the
/// destination paths. Skips files already inside the library.
#[tauri::command]
pub fn import_files(paths: Vec<String>) -> Result<Vec<String>, String> {
    let lib = wondershot_core::paths::library_dir();   // existing M2 helper
    std::fs::create_dir_all(&lib).map_err(|e| e.to_string())?;
    let mut out = Vec::new();
    for p in paths {
        let src = std::path::PathBuf::from(&p);
        let name = src.file_name().ok_or("bad path")?;
        let dest = lib.join(name);
        if src != dest {
            std::fs::copy(&src, &dest).map_err(|e| e.to_string())?;
        }
        out.push(dest.to_string_lossy().into_owned());
    }
    Ok(out)
}
```

> Verify the actual M2 helper name for the library dir (`paths::library_dir` vs `library::dir` vs reading settings) before committing — read `crates/wondershot-core/src/paths.rs` / `library.rs` and match it.

- [ ] **Step 3: register** both in `lib.rs`'s `invoke_handler![...]`.

- [ ] **Step 4: build:**

Run: `cargo build -p wondershot`
Expected: SUCCESS.

- [ ] **Step 5: Commit** — `M7: install_desktop + import_files commands (--install-desktop / --import parity)`.

---

## Task 4: Cutover migration (stale venv removal) + library-load verification

**Files:** `install.sh`, a verification run. Oracle: an existing captured library + `.sidecar` + `wondershot.conf`.

- [ ] **Step 1: clear the stale Python venv** in `install.sh` — the AppImage reuses `~/.local/share/wondershot`, where the old installer put `venv/`. Before downloading, remove it so the two installs don't coexist. Add after `mkdir -p "$HOME_DIR" …`:

```sh
# Cutover: the old (Python) installer left a venv here; the AppImage replaces it.
if [ -d "$HOME_DIR/venv" ]; then
    say "removing the old Python install ($HOME_DIR/venv)"
    rm -rf "$HOME_DIR/venv"
fi
```

- [ ] **Step 2: re-check the script:** `sh -n install.sh` (and shellcheck if present). Expected: clean.

- [ ] **Step 3: verify the existing library loads unchanged.** Point `list_library` / `load_sidecar` at a real fixture dir (the user's library or `tests/` fixtures) and confirm items + annotations parse. If a cargo oracle test for this already exists (M2 ported `test_gallery*`/`test_items_serialize`), run it:

Run: `cargo test -p wondershot-core library && cargo test -p wondershot-core sidecar`
Expected: PASS. Document that existing PNG/MP4 + `.sidecar` + conf round-trip.

- [ ] **Step 4: document the Flatpak supersede** — the new Flatpak shares the app-id `io.github.jackmusick.wondershot`, so `flatpak install` of the new bundle replaces the old Python one in place (no separate uninstall needed). Note this in the parity checklist (Task 5).

- [ ] **Step 5: Commit** — `M7: install.sh clears the stale Python venv on cutover; library-load parity verified`.

---

## Task 5: Parity checklist (the sign-off matrix)

**Files:** `docs/superpowers/plans/2026-06-08-wondershot-m7-parity-checklist.md` (new). Enumerate every Python feature and record its Tauri status + evidence.

- [ ] **Step 1: write the checklist** with one row per feature area, each marked ✅ (verified — name the cargo test or screenshot) / ⏳ (manual/display gate) / ❌ (gap). Cover, at minimum:
  - Capture: region / fullscreen / window (M2) — `cargo test capture*`
  - Clipboard copy-after-capture (M2) — `cargo test clipboard`
  - Library: scan, thumbnails, `.sidecar` read/write, trash (M2) — `cargo test library/gallery/sidecar`
  - Editor 14 tools + undo/redo + sidecar round-trip (M3) — `cargo test editor/items_serialize`
  - Recorder: record/pause/resume/stop, finalize, countdown, bubble (M4) — `cargo test record*`
  - Video: blur redaction / GIF / frame / trim (M5) — `cargo test video`
  - Settings: load/save conf, tabbed modal (M5) — `cargo test settings`
  - BG-removal: u2net inference (M6 — `--features bgremove`) — `cargo test bgremove`
  - CLI: `--capture/-f/--edit/--import/--quit/--install-desktop/--version/url` (M7 T1–T3) — `cargo test cli`
  - Cutover: app-id/.desktop/library identity, stale-venv removal, Flatpak supersede (M6/M7 T4)
  - Hotkey guidance (manual KGlobalAccel, Settings) (M5)
- [ ] **Step 2: run the full oracle** to back the ✅ rows:

Run: `cargo test --workspace && cargo test -p wondershot-core --features bgremove-onnx`
Expected: all PASS; record counts in the checklist.

- [ ] **Step 3: list the explicit display/human gates** (capture round-trip, live recorder via portal, live ffmpeg, Flatpak/AppImage launch, curl|sh) as ⏳ with the command to run them — honest, matching the M2/M4/M5/M6 precedent.
- [ ] **Step 4: Commit** — `M7: parity checklist (feature → Tauri verification matrix)`.

---

## Task 6: Exit verification + merge to main

**Files:** roadmap, branch.

- [ ] **Step 1: full green:** `cargo build --workspace && cargo test --workspace && cargo build -p wondershot --features bgremove && npm run test && npm run build`. Expected: all SUCCESS.
- [ ] **Step 2: UI-review** the final shell (light + dark) one last time; fix any blocker.
- [ ] **Step 3: mark M7 complete** in the roadmap with notes (what's verified vs the display/human gates that remain for a real desktop session), then `git tag m7-cutover`.
- [ ] **Step 4: finish the branch** — REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch. Present the merge options (the goal targets `tauri-rewrite` → `main`); the Python app on `main` is replaced by the Tauri tree per the cutover. Do NOT delete the Python `wondershot/` tree or `tests/` without confirming the merge strategy — they are the live parity oracle until the merge lands.
- [ ] **Step 5: Commit** the roadmap update; perform the merge per the chosen strategy.

---

## Self-Review notes (author)

- **Spec coverage:** "full feature + UI parity" → the parity checklist (T5) enumerates every subsystem and its evidence; CLI/hotkey forwarding (the one un-ported behavior) → T1–T3; "supersede the Flatpak / remove the old pip venv" → T4 + the preserved app-id; "library/.sidecar/conf load unchanged" → T4 step 3; "merge tauri-rewrite → main" → T6.
- **Placeholder scan:** the only deferred specifics are the M2 library-dir helper name (T3 step 2, flagged to verify against the real source) and the app-shell action names (`captureRegion`/`openEditor`/`importFiles` — T2 step 4, reuse the existing store actions; verify names when wiring). No invented APIs.
- **Type consistency:** `CliAction` (T1) is consumed by `dispatch_cli` (T2) and the launch short-circuit (T2 step 3); `install_desktop`/`import_files` (T3) are called from `dispatch_cli` and registered in the same `invoke_handler!` list; the `.desktop` content matches `install.sh`'s (M6) and the Flatpak's (M6) — same Name/Icon/Categories.
- **Deferred (out of scope, consistent with the rewrite roadmap):** cloud sharing + AI-chat (never in the 7-milestone plan); the `wondershot://` deep link focuses-only (no OAuth flow exists in the rewrite); macOS/Windows packaging.
- **Honest gates:** capture/recorder/ffmpeg/Flatpak/AppImage/curl|sh live runs need a real desktop session — listed as ⏳ in T5 with their commands, not silently claimed.
```
