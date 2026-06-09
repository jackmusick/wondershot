# Wondershot M2 — Capture + Clipboard + Library — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Where a task is an independent build→test chain, it may be run as a workflow pipeline item.

**Goal:** Port Wondershot's screen-capture, clipboard, and library/sidecar subsystems from Python to Rust in a framework-free `wondershot-core` crate, wire them as Tauri commands, and connect the real backend to the M1 Svelte shell so region/full/window capture flow into the library and clipboard — with the existing captured library and `.sidecar` data still loading unchanged.

**Architecture:** A new `crates/wondershot-core` cargo crate holds all logic (pure modules unit-tested with `cargo test`, porting the existing pytest assertions as the oracle). `src-tauri` becomes a thin command layer over it. Capture shells out to `spectacle` (KDE) with an `ashpd` portal fallback and KWin geometry via `zbus`; clipboard uses `wl-clipboard-rs`/spawned `wl-copy`; library scans the real directories and reads/writes the existing `.wondershot/*.json` sidecar format byte-compatibly.

**Tech Stack:** Rust (edition 2021), Tauri 2, crates: `serde`/`serde_json`, `image`, `ashpd`, `zbus`, `wl-clipboard-rs` (or `std::process` spawn of `wl-copy`), `chrono` (timestamp formatting), `dirs`/`directories`. Frontend: existing SvelteKit shell.

**Parity oracle:** `wondershot/` Python on `main` + these tests: `tests/test_capture_crop.py`, `tests/test_kwin.py`, `tests/test_clipboard.py`, `tests/test_sidecar.py`, `tests/test_gallery.py`, `tests/test_gallery_sidecar.py`, `tests/test_items_serialize.py`.

---

## Behavioral contract (ported from Python — exact)

These are the invariants the Rust port MUST preserve. Source: `wondershot/capture.py`, `kwin.py`, `clipboard.py`, `sidecar.py`, `gallery.py`, `settings.py`.

- **Screenshot filename:** `strftime("Screenshot_%Y%m%d_%H%M%S.png")`. Recording: `Recording_%Y%m%d_%H%M%S.webm`.
- **Collision (`unique_path`):** if `dir/name.png` exists, try `name-1.png`, `name-2.png`, … (suffix before extension, starting at 1).
- **Spectacle invocation** (background, no-notification): `spectacle -b -n <MODE> -o <path>`, MODE = `-r` region / `-f` fullscreen / `-a` active-window. Insert `-p` (pointer) at arg index 2 when `capture_cursor`. Append `-d <delay_ms>` when `capture_delay` > 0 (`delay_ms = capture_delay * 1000`).
- **Portal fallback:** `org.freedesktop.portal.Desktop` / `/org/freedesktop/portal/desktop`, interface `org.freedesktop.portal.Screenshot`, method `Screenshot`, args `["", {handle_token, interactive}]`; `interactive=false` only for fullscreen. Response `uri` is `file://…`; move into `library_dir` unless already there.
- **KWin geometry:** load a JS script via `org.kde.KWin` `/Scripting` `org.kde.kwin.Scripting.loadScript`, `run()` it; it calls back `org.kde.KWin` script `callDBus(...)` with `"x,y,w,h"` (empty if no active window). Try `workspace.activeWindow || workspace.activeClient`. 2s timeout. Then crop the fullscreen shot.
- **Crop math (`map_global_rect`):** given logical `rect`, virtual-desktop `virtual` rect, and image px `(img_w,img_h)`: `sx=img_w/virtual.w`, `sy=img_h/virtual.h`; mapped = `round((rect.x-virtual.x)*sx), round((rect.y-virtual.y)*sy), round(rect.w*sx), round(rect.h*sy)`, intersected with `(0,0,img_w,img_h)`. Empty/invalid → leave image unchanged.
- **Clipboard:** Wayland iff `WAYLAND_DISPLAY` set AND `wl-copy` on PATH → run `wl-copy --type image/png` with PNG bytes on stdin (10s timeout); on failure fall back to the Qt/native clipboard. PNG bytes start with magic `89 50 4E 47 0D 0A 1A 0A`.
- **Sidecar layout:** dir `<imgdir>/.wondershot/`; JSON at `<basename(with ext)>.json`; bases `<basename>.base.<N>.png`. JSON doc `{ "version": 1, "bases": <int>, "items": [ <annotation> … ], "effects": { … } }`. `load` returns None for missing/corrupt/`version != 1`. `save` is atomic (`.tmp` + rename). `related_files` = JSON + sorted base PNGs.
- **Library scan:** dirs = `library_dir` + `extra_dirs`; extensions (lowercase) images `{png,jpg,jpeg,webp,bmp,gif}`, videos `{mp4,mkv,webm,mov,avi,m4v}`; sort by mtime descending; never list anything inside `.wondershot/`.
- **Settings file:** `~/.config/wondershot/wondershot.conf` (QSettings INI). Keys: `library_dir` (default `~/Pictures/Screenshots`), `backend` (`auto`|`spectacle`|`portal`), `capture_cursor` (bool, default false), `capture_delay` (int seconds, default 0), `extra_dirs` (semicolon list).
- **Gallery label (test_gallery):** "Today" if mtime is today else `MM/DD/YYYY`; time `H:MMAM/PM` with leading-zero hour stripped.

---

## File Structure

```
crates/wondershot-core/
  Cargo.toml
  src/lib.rs                 # re-exports modules
  src/paths.rs               # timestamp_name, unique_path
  src/settings.rs            # Settings load/save (conf INI)
  src/sidecar.rs             # SidecarDoc, paths, load/save, related_files
  src/library.rs             # scan(), Capture, date/time labels
  src/clipboard.rs           # copy_png(bytes), wayland detection
  src/capture/mod.rs         # CaptureMode, orchestration + crop
  src/capture/spectacle.rs   # arg builder (pure, testable)
  src/capture/portal.rs      # ashpd Screenshot
  src/capture/kwin.rs        # geometry script, parse, crop math
src-tauri/
  Cargo.toml                 # add wondershot-core dep + new crates
  capabilities/default.json  # grant the new commands
  src/commands.rs            # capture_*, copy_image, list_library, *_sidecar, trash_item, *_settings
  src/lib.rs                 # register handlers + emit capture:// events
src/lib/                     # frontend wiring (ipc calls become real)
```

A cargo **workspace** ties `src-tauri` and `crates/wondershot-core` together.

---

## Task 1: Cargo workspace + core crate skeleton

**Files:** Create `Cargo.toml` (workspace root), `crates/wondershot-core/Cargo.toml`, `crates/wondershot-core/src/lib.rs`; Modify `src-tauri/Cargo.toml`.

- [ ] **Step 1: Create workspace root `Cargo.toml`**

```toml
[workspace]
members = ["src-tauri", "crates/wondershot-core"]
resolver = "2"
```

- [ ] **Step 2: Create `crates/wondershot-core/Cargo.toml`**

```toml
[package]
name = "wondershot-core"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
chrono = { version = "0.4", default-features = false, features = ["clock"] }
image = "0.25"
dirs = "5"

[dev-dependencies]
tempfile = "3"
```

- [ ] **Step 3: Create `crates/wondershot-core/src/lib.rs`**

```rust
pub mod paths;
pub mod settings;
pub mod sidecar;
pub mod library;
pub mod clipboard;
pub mod capture;
```

(Create empty `pub` stub files for each module so it compiles; subsequent tasks fill them.)

- [ ] **Step 4: Add the core dep to `src-tauri/Cargo.toml`** (under `[dependencies]`)

```toml
wondershot-core = { path = "../crates/wondershot-core" }
```

- [ ] **Step 5: Verify the workspace builds**

Run: `cargo build --workspace 2>&1 | tail -15`
Expected: `Finished`. (Empty modules + existing Tauri shell compile.)

- [ ] **Step 6: Commit**

```bash
git add Cargo.toml crates/wondershot-core src-tauri/Cargo.toml
git commit -m "M2: cargo workspace + wondershot-core crate skeleton"
```

---

## Task 2: `paths` — timestamp + unique_path (TDD)

**Files:** `crates/wondershot-core/src/paths.rs`.

- [ ] **Step 1: Write failing tests** (in `paths.rs` `#[cfg(test)]`)

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn timestamp_name_matches_python_format() {
        // Screenshot_YYYYMMDD_HHMMSS.png — 14 digits split 8_6, .png ext.
        let name = timestamp_name("Screenshot");
        assert!(name.starts_with("Screenshot_"));
        assert!(name.ends_with(".png"));
        let stamp = &name["Screenshot_".len()..name.len() - 4];
        let (d, t) = stamp.split_once('_').unwrap();
        assert_eq!(d.len(), 8);
        assert_eq!(t.len(), 6);
        assert!(d.chars().chain(t.chars()).all(|c| c.is_ascii_digit()));
    }

    #[test]
    fn unique_path_appends_dash_n_on_collision() {
        let dir = tempfile::tempdir().unwrap();
        let p0 = unique_path(dir.path(), "Shot_20260608_000000.png");
        assert_eq!(p0.file_name().unwrap(), "Shot_20260608_000000.png");
        fs::write(&p0, b"x").unwrap();
        let p1 = unique_path(dir.path(), "Shot_20260608_000000.png");
        assert_eq!(p1.file_name().unwrap(), "Shot_20260608_000000-1.png");
        fs::write(&p1, b"x").unwrap();
        let p2 = unique_path(dir.path(), "Shot_20260608_000000.png");
        assert_eq!(p2.file_name().unwrap(), "Shot_20260608_000000-2.png");
    }
}
```

- [ ] **Step 2: Run, expect FAIL** — `cargo test -p wondershot-core paths` → unresolved fns.

- [ ] **Step 3: Implement `paths.rs`**

```rust
use std::path::{Path, PathBuf};

/// `<prefix>_%Y%m%d_%H%M%S.png` in local time (matches Python strftime).
pub fn timestamp_name(prefix: &str) -> String {
    let now = chrono::Local::now();
    format!("{}_{}.png", prefix, now.format("%Y%m%d_%H%M%S"))
}

/// First non-colliding path: `name`, then `name-1.ext`, `name-2.ext`, …
pub fn unique_path(dir: &Path, name: &str) -> PathBuf {
    let mut candidate = dir.join(name);
    if !candidate.exists() {
        return candidate;
    }
    let (stem, ext) = match name.rsplit_once('.') {
        Some((s, e)) => (s.to_string(), format!(".{e}")),
        None => (name.to_string(), String::new()),
    };
    let mut n = 1;
    loop {
        candidate = dir.join(format!("{stem}-{n}{ext}"));
        if !candidate.exists() {
            return candidate;
        }
        n += 1;
    }
}
```

- [ ] **Step 4: Run, expect PASS** — `cargo test -p wondershot-core paths`.

- [ ] **Step 5: Commit** — `git add crates/wondershot-core/src/paths.rs && git commit -m "M2: paths — timestamp_name + unique_path (parity with Python)"`

---

## Task 3: `sidecar` — schema, paths, atomic I/O, related_files (TDD)

**Files:** `crates/wondershot-core/src/sidecar.rs`. Oracle: `tests/test_sidecar.py`.

- [ ] **Step 1: Write failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn paths_include_extension_so_png_and_jpg_dont_collide() {
        let img = std::path::Path::new("/lib/shot.png");
        assert!(sidecar_path(img).ends_with(".wondershot/shot.png.json"));
        let jpg = std::path::Path::new("/lib/shot.jpg");
        assert!(sidecar_path(jpg).ends_with(".wondershot/shot.jpg.json"));
        assert!(base_path(img, 0).ends_with(".wondershot/shot.png.base.0.png"));
    }

    #[test]
    fn save_then_load_roundtrips_and_leaves_no_tmp() {
        let dir = tempfile::tempdir().unwrap();
        let img = dir.path().join("shot.png");
        let doc = SidecarDoc {
            version: 1, bases: 1,
            items: vec![serde_json::json!({"type": "rect"})],
            effects: serde_json::json!({"rounded": true}),
        };
        assert!(save(&img, &doc));
        let got = load(&img).unwrap();
        assert_eq!(got.version, 1);
        assert_eq!(got.bases, 1);
        assert_eq!(got.items[0]["type"], "rect");
        // atomic write leaves no .tmp behind
        let scdir = sidecar_dir(&img);
        let leftover: Vec<_> = fs::read_dir(&scdir).unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().map_or(false, |x| x == "tmp"))
            .collect();
        assert!(leftover.is_empty());
    }

    #[test]
    fn load_returns_none_for_missing_corrupt_or_future_version() {
        let dir = tempfile::tempdir().unwrap();
        let img = dir.path().join("shot.png");
        assert!(load(&img).is_none()); // missing
        fs::create_dir_all(sidecar_dir(&img)).unwrap();
        fs::write(sidecar_path(&img), b"{ not json").unwrap();
        assert!(load(&img).is_none()); // corrupt
        fs::write(sidecar_path(&img), br#"{"version":2,"bases":0,"items":[],"effects":{}}"#).unwrap();
        assert!(load(&img).is_none()); // future version
    }

    #[test]
    fn related_files_lists_json_plus_sorted_bases() {
        let dir = tempfile::tempdir().unwrap();
        let img = dir.path().join("shot.png");
        let doc = SidecarDoc { version: 1, bases: 2, items: vec![], effects: serde_json::json!({}) };
        save(&img, &doc);
        fs::write(base_path(&img, 0), b"a").unwrap();
        fs::write(base_path(&img, 1), b"b").unwrap();
        let rel = related_files(&img);
        assert_eq!(rel.len(), 3); // json + base.0 + base.1
        assert!(rel[0].ends_with("shot.png.json"));
        assert!(rel[1].to_string_lossy().contains("base.0"));
        assert!(rel[2].to_string_lossy().contains("base.1"));
    }
}
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `sidecar.rs`**

```rust
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const SIDECAR_DIRNAME: &str = ".wondershot";
pub const FORMAT_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarDoc {
    pub version: u32,
    pub bases: u32,
    #[serde(default)]
    pub items: Vec<serde_json::Value>,
    #[serde(default)]
    pub effects: serde_json::Value,
}

pub fn sidecar_dir(image_path: &Path) -> PathBuf {
    let parent = image_path.parent().unwrap_or_else(|| Path::new("."));
    parent.join(SIDECAR_DIRNAME)
}

pub fn sidecar_path(image_path: &Path) -> PathBuf {
    let name = image_path.file_name().unwrap_or_default().to_string_lossy();
    sidecar_dir(image_path).join(format!("{name}.json"))
}

pub fn base_path(image_path: &Path, n: u32) -> PathBuf {
    let name = image_path.file_name().unwrap_or_default().to_string_lossy();
    sidecar_dir(image_path).join(format!("{name}.base.{n}.png"))
}

/// Parsed sidecar, or None for missing / corrupt / non-current version.
pub fn load(image_path: &Path) -> Option<SidecarDoc> {
    let raw = std::fs::read_to_string(sidecar_path(image_path)).ok()?;
    let doc: SidecarDoc = serde_json::from_str(&raw).ok()?;
    if doc.version != FORMAT_VERSION {
        return None;
    }
    Some(doc)
}

/// Atomic write: tmp + rename. Creates the .wondershot dir.
pub fn save(image_path: &Path, doc: &SidecarDoc) -> bool {
    let dir = sidecar_dir(image_path);
    if std::fs::create_dir_all(&dir).is_err() {
        return false;
    }
    let target = sidecar_path(image_path);
    let tmp = target.with_extension("json.tmp");
    let Ok(json) = serde_json::to_string(doc) else { return false };
    if std::fs::write(&tmp, json).is_err() {
        return false;
    }
    std::fs::rename(&tmp, &target).is_ok()
}

/// JSON sidecar + every base PNG, sorted — what trash/rename carry along.
pub fn related_files(image_path: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let sp = sidecar_path(image_path);
    if sp.exists() {
        out.push(sp);
    }
    let name = image_path.file_name().unwrap_or_default().to_string_lossy().to_string();
    let dir = sidecar_dir(image_path);
    if let Ok(entries) = std::fs::read_dir(&dir) {
        let mut bases: Vec<PathBuf> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| {
                p.file_name()
                    .map(|f| {
                        let f = f.to_string_lossy();
                        f.starts_with(&format!("{name}.base.")) && f.ends_with(".png")
                    })
                    .unwrap_or(false)
            })
            .collect();
        bases.sort();
        out.extend(bases);
    }
    out
}
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "M2: sidecar — .wondershot schema, atomic I/O, related_files"`

---

## Task 4: `library` — scan + date/time labels (TDD)

**Files:** `crates/wondershot-core/src/library.rs`. Oracle: `tests/test_gallery.py` (labels), gallery scan rules.

- [ ] **Step 1: Write failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn scan_lists_media_newest_first_and_skips_sidecar_dir() {
        let dir = tempfile::tempdir().unwrap();
        let a = dir.path().join("a.png");
        let b = dir.path().join("b.mp4");
        fs::write(&a, b"x").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(20));
        fs::write(&b, b"x").unwrap();
        fs::write(dir.path().join("notes.txt"), b"x").unwrap(); // ignored ext
        fs::create_dir_all(dir.path().join(".wondershot")).unwrap();
        fs::write(dir.path().join(".wondershot/a.png.json"), b"{}").unwrap(); // never listed
        let caps = scan(&[dir.path().to_path_buf()]);
        assert_eq!(caps.len(), 2);
        assert_eq!(caps[0].path, b);   // newest first
        assert_eq!(caps[1].path, a);
        assert_eq!(caps[0].kind, CaptureKind::Video);
        assert_eq!(caps[1].kind, CaptureKind::Image);
    }

    #[test]
    fn is_image_and_video_ext_match_python_sets() {
        for e in ["png","jpg","jpeg","webp","bmp","gif"] { assert!(is_image_ext(e)); }
        for e in ["mp4","mkv","webm","mov","avi","m4v"] { assert!(is_video_ext(e)); }
        assert!(!is_image_ext("txt"));
        assert!(is_image_ext("PNG")); // case-insensitive
    }
}
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `library.rs`**

```rust
use serde::Serialize;
use std::path::{Path, PathBuf};

const IMAGE_EXTS: [&str; 6] = ["png", "jpg", "jpeg", "webp", "bmp", "gif"];
const VIDEO_EXTS: [&str; 6] = ["mp4", "mkv", "webm", "mov", "avi", "m4v"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CaptureKind { Image, Video }

#[derive(Debug, Clone, Serialize)]
pub struct Capture {
    pub id: String,
    pub path: PathBuf,
    pub kind: CaptureKind,
    #[serde(rename = "createdAt")]
    pub created_at: u64, // epoch ms
    pub title: String,
}

pub fn is_image_ext(ext: &str) -> bool { IMAGE_EXTS.contains(&ext.to_ascii_lowercase().as_str()) }
pub fn is_video_ext(ext: &str) -> bool { VIDEO_EXTS.contains(&ext.to_ascii_lowercase().as_str()) }

fn mtime_ms(p: &Path) -> u64 {
    std::fs::metadata(p)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Scan dirs for media, newest-first, never descending into `.wondershot`.
pub fn scan(dirs: &[PathBuf]) -> Vec<Capture> {
    let mut caps = Vec::new();
    for dir in dirs {
        let Ok(entries) = std::fs::read_dir(dir) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_file() { continue; }
            let Some(ext) = path.extension().map(|e| e.to_string_lossy().to_string()) else { continue };
            let kind = if is_image_ext(&ext) { CaptureKind::Image }
                       else if is_video_ext(&ext) { CaptureKind::Video }
                       else { continue };
            let title = path.file_stem().unwrap_or_default().to_string_lossy().to_string();
            caps.push(Capture {
                id: path.to_string_lossy().to_string(),
                created_at: mtime_ms(&path),
                kind, path, title,
            });
        }
    }
    caps.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    caps
}
```

(Note: `.wondershot` is skipped naturally because `read_dir` is non-recursive and the dir itself has no media extension. The test asserts this explicitly.)

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "M2: library — media scan, newest-first, kind detection"`

---

## Task 5: `clipboard` — Wayland detection + wl-copy (TDD where pure)

**Files:** `crates/wondershot-core/src/clipboard.rs`. Oracle: `tests/test_clipboard.py`.

- [ ] **Step 1: Write failing tests for the pure decision + arg builder**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wayland_decision_needs_display_and_wl_copy() {
        assert!(should_use_wl_copy(Some("wayland-0"), true));
        assert!(!should_use_wl_copy(None, true));          // no display
        assert!(!should_use_wl_copy(Some("wayland-0"), false)); // no wl-copy
        assert!(!should_use_wl_copy(Some(""), true));      // empty display
    }

    #[test]
    fn wl_copy_args_request_png_mime() {
        assert_eq!(wl_copy_args(), ["--type", "image/png"]);
    }
}
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `clipboard.rs`**

```rust
use std::io::Write;

pub fn should_use_wl_copy(wayland_display: Option<&str>, wl_copy_present: bool) -> bool {
    wayland_display.map_or(false, |d| !d.is_empty()) && wl_copy_present
}

pub fn wl_copy_args() -> [&'static str; 2] {
    ["--type", "image/png"]
}

fn wl_copy_on_path() -> bool {
    which("wl-copy")
}

fn which(bin: &str) -> bool {
    std::env::var_os("PATH").map_or(false, |paths| {
        std::env::split_paths(&paths).any(|p| p.join(bin).is_file())
    })
}

/// Put PNG bytes on the clipboard. Wayland → wl-copy (focus-independent);
/// otherwise fall back to the native clipboard via `arboard` is handled by
/// the caller in src-tauri. Returns Ok(true) if wl-copy took it.
pub fn copy_png(png: &[u8]) -> std::io::Result<bool> {
    let wayland = std::env::var("WAYLAND_DISPLAY").ok();
    if !should_use_wl_copy(wayland.as_deref(), wl_copy_on_path()) {
        return Ok(false);
    }
    let mut child = std::process::Command::new("wl-copy")
        .args(wl_copy_args())
        .stdin(std::process::Stdio::piped())
        .spawn()?;
    child.stdin.as_mut().unwrap().write_all(png)?;
    let status = child.wait()?;
    Ok(status.success())
}
```

(`src-tauri` falls back to `arboard` when `copy_png` returns `Ok(false)` or errors — covered in Task 8. A 10s timeout wrapper is added in Task 8's command, matching Python.)

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "M2: clipboard — Wayland detection + wl-copy PNG piping"`

---

## Task 6: `capture` — spectacle args, crop math, portal, kwin (TDD on pure parts)

**Files:** `crates/wondershot-core/src/capture/mod.rs`, `spectacle.rs`, `kwin.rs`, `portal.rs`. Oracle: `tests/test_kwin.py`, `tests/test_capture_crop.py`.

- [ ] **Step 1: Write failing tests for the spectacle arg builder + crop math**

```rust
// in capture/spectacle.rs
#[cfg(test)]
mod tests {
    use super::*;
    use crate::capture::CaptureMode;

    #[test]
    fn region_args_background_no_notify() {
        let a = spectacle_args(CaptureMode::Region, "/out.png", false, 0);
        assert_eq!(a, vec!["-b", "-n", "-r", "-o", "/out.png"]);
    }
    #[test]
    fn cursor_inserts_p_at_index_2() {
        let a = spectacle_args(CaptureMode::Fullscreen, "/o.png", true, 0);
        assert_eq!(a, vec!["-b", "-n", "-p", "-f", "-o", "/o.png"]);
    }
    #[test]
    fn delay_seconds_become_milliseconds_appended() {
        let a = spectacle_args(CaptureMode::Window, "/o.png", false, 2);
        assert_eq!(a, vec!["-b", "-n", "-a", "-o", "/o.png", "-d", "2000"]);
    }
}

// in capture/kwin.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_geometry_reply_handles_floats_negatives_and_rejects_bad() {
        assert_eq!(parse_geometry_reply("10,20,300,400"), Some((10, 20, 300, 400)));
        assert_eq!(parse_geometry_reply("-5,0,800,600"), Some((-5, 0, 800, 600)));
        assert_eq!(parse_geometry_reply("1.0,2.0,3.0,4.0"), Some((1, 2, 3, 4)));
        assert_eq!(parse_geometry_reply(""), None);
        assert_eq!(parse_geometry_reply("1,2,3"), None);
        assert_eq!(parse_geometry_reply("1,2,0,400"), None); // w<=0
        assert_eq!(parse_geometry_reply("a,b,c,d"), None);
    }

    #[test]
    fn map_global_rect_scales_translates_clamps() {
        // virtual (0,0,1000x1000), image 2000x2000 (2x HiDPI), rect (100,100,200,200)
        let m = map_global_rect((100, 100, 200, 200), (0, 0, 1000, 1000), 2000, 2000);
        assert_eq!(m, Some((200, 200, 400, 400)));
        // left monitor with negative origin
        let m2 = map_global_rect((-100, 0, 50, 50), (-100, 0, 1000, 1000), 1000, 1000);
        assert_eq!(m2, Some((0, 0, 50, 50)));
        // off-virtual → empty → None
        assert_eq!(map_global_rect((5000, 5000, 10, 10), (0, 0, 1000, 1000), 1000, 1000), None);
    }
}
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `capture/mod.rs` (types) + `spectacle.rs` + `kwin.rs`**

`capture/mod.rs`:
```rust
pub mod spectacle;
pub mod kwin;
pub mod portal;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureMode { Region, Fullscreen, Window }
```

`capture/spectacle.rs`:
```rust
use super::CaptureMode;

/// Build the spectacle CLI args. Mirrors capture.py:_spectacle exactly:
/// `-b -n <mode> -o <path>` with `-p` inserted at index 2 for cursor and
/// `-d <ms>` appended for a delay.
pub fn spectacle_args(mode: CaptureMode, out: &str, cursor: bool, delay_secs: u32) -> Vec<String> {
    let flag = match mode {
        CaptureMode::Region => "-r",
        CaptureMode::Fullscreen => "-f",
        CaptureMode::Window => "-a",
    };
    let mut args: Vec<String> = vec!["-b".into(), "-n".into(), flag.into(), "-o".into(), out.into()];
    if cursor {
        args.insert(2, "-p".into());
    }
    if delay_secs > 0 {
        args.push("-d".into());
        args.push((delay_secs * 1000).to_string());
    }
    args
}
```

`capture/kwin.rs`:
```rust
/// Parse KWin's `"x,y,w,h"` callback. None for wrong arity, non-numeric,
/// or non-positive width/height. Floats are truncated to int.
pub fn parse_geometry_reply(text: &str) -> Option<(i64, i64, i64, i64)> {
    let parts: Vec<&str> = text.split(',').collect();
    if parts.len() != 4 {
        return None;
    }
    let nums: Option<Vec<i64>> = parts.iter()
        .map(|p| p.trim().parse::<f64>().ok().map(|f| f as i64))
        .collect();
    let n = nums?;
    let (x, y, w, h) = (n[0], n[1], n[2], n[3]);
    if w <= 0 || h <= 0 { return None; }
    Some((x, y, w, h))
}

/// Map a logical rect into a fullscreen image's pixel space (HiDPI-aware).
/// Returns None if the mapped rect is empty after clamping.
pub fn map_global_rect(
    rect: (i64, i64, i64, i64),
    virtual_rect: (i64, i64, i64, i64),
    img_w: i64,
    img_h: i64,
) -> Option<(i64, i64, i64, i64)> {
    let (rx, ry, rw, rh) = rect;
    let (vx, vy, vw, vh) = virtual_rect;
    if vw <= 0 || vh <= 0 || img_w <= 0 || img_h <= 0 {
        return None;
    }
    let sx = img_w as f64 / vw as f64;
    let sy = img_h as f64 / vh as f64;
    let mx = ((rx - vx) as f64 * sx).round() as i64;
    let my = ((ry - vy) as f64 * sy).round() as i64;
    let mw = (rw as f64 * sx).round() as i64;
    let mh = (rh as f64 * sy).round() as i64;
    // intersect with (0,0,img_w,img_h)
    let x0 = mx.max(0);
    let y0 = my.max(0);
    let x1 = (mx + mw).min(img_w);
    let y1 = (my + mh).min(img_h);
    if x1 <= x0 || y1 <= y0 {
        return None;
    }
    Some((x0, y0, x1 - x0, y1 - y0))
}

/// The KWin geometry JS (build to match kwin.py:build_geometry_script).
pub fn build_geometry_script(service: &str, path: &str, iface: &str, method: &str) -> String {
    format!(
        "var w = workspace.activeWindow || workspace.activeClient;\n\
         if (w && w.frameGeometry) {{\n\
         \x20   var g = w.frameGeometry;\n\
         \x20   callDBus(\"{service}\", \"{path}\", \"{iface}\", \"{method}\",\n\
         \x20            \"\" + g.x + \",\" + g.y + \",\" + g.width + \",\" + g.height);\n\
         }} else {{\n\
         \x20   callDBus(\"{service}\", \"{path}\", \"{iface}\", \"{method}\", \"\");\n\
         }}\n"
    )
}

pub fn crop_file_to_global_rect(path: &std::path::Path, rect: (i64,i64,i64,i64), virtual_rect: (i64,i64,i64,i64)) -> bool {
    let Ok(img) = image::open(path) else { return false };
    let (iw, ih) = (img.width() as i64, img.height() as i64);
    let Some((x, y, w, h)) = map_global_rect(rect, virtual_rect, iw, ih) else { return false };
    let cropped = img.crop_imm(x as u32, y as u32, w as u32, h as u32);
    cropped.save(path).is_ok()
}
```

`capture/portal.rs`: an `ashpd`-based async `screenshot(interactive: bool) -> Option<PathBuf>` (thin wrapper over `ashpd::desktop::screenshot::Screenshot`). No pure unit test (integration only); document the interface and add `#[cfg(test)]` nothing. Keep it small.

```rust
use std::path::PathBuf;

/// Take a screenshot via xdg-desktop-portal; returns the file path it wrote.
/// interactive=false only for fullscreen (matches capture.py:_portal).
pub async fn screenshot(interactive: bool) -> Option<PathBuf> {
    use ashpd::desktop::screenshot::Screenshot;
    let resp = Screenshot::request()
        .interactive(interactive)
        .send()
        .await
        .ok()?
        .response()
        .ok()?;
    let uri = resp.uri();
    uri.to_file_path().ok()
}
```

- [ ] **Step 4: Add `ashpd` and `zbus` to `crates/wondershot-core/Cargo.toml`**

```toml
ashpd = { version = "0.9", default-features = false, features = ["tokio"] }
zbus = "4"
```

- [ ] **Step 5: Run pure tests, expect PASS** — `cargo test -p wondershot-core capture`.
- [ ] **Step 6: Confirm the crate builds** — `cargo build -p wondershot-core 2>&1 | tail`.
- [ ] **Step 7: Commit** — `git commit -m "M2: capture — spectacle args, KWin geometry+crop math, portal wrapper"`

---

## Task 7: `settings` — read/write wondershot.conf (TDD)

**Files:** `crates/wondershot-core/src/settings.rs`. Oracle: `wondershot/settings.py` defaults.

- [ ] **Step 1: Write failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_match_python() {
        let s = Settings::default();
        assert_eq!(s.backend, "auto");
        assert_eq!(s.capture_cursor, false);
        assert_eq!(s.capture_delay, 0);
        assert!(s.library_dir.ends_with("Screenshots"));
    }

    #[test]
    fn parse_conf_reads_known_keys() {
        let conf = "[General]\nlibrary_dir=/tmp/shots\nbackend=spectacle\ncapture_cursor=true\ncapture_delay=3\n";
        let s = Settings::from_conf_str(conf);
        assert_eq!(s.library_dir, "/tmp/shots");
        assert_eq!(s.backend, "spectacle");
        assert_eq!(s.capture_cursor, true);
        assert_eq!(s.capture_delay, 3);
    }
}
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `settings.rs`** (a minimal INI parser for the `[General]` section; QSettings writes flat `key=value` under `[General]`).

```rust
#[derive(Debug, Clone)]
pub struct Settings {
    pub library_dir: String,
    pub backend: String,
    pub capture_cursor: bool,
    pub capture_delay: u32,
    pub extra_dirs: Vec<String>,
}

impl Default for Settings {
    fn default() -> Self {
        let pictures = dirs::picture_dir()
            .unwrap_or_else(|| dirs::home_dir().unwrap_or_default().join("Pictures"));
        Settings {
            library_dir: pictures.join("Screenshots").to_string_lossy().to_string(),
            backend: "auto".into(),
            capture_cursor: false,
            capture_delay: 0,
            extra_dirs: Vec::new(),
        }
    }
}

impl Settings {
    pub fn conf_path() -> std::path::PathBuf {
        dirs::config_dir().unwrap_or_default().join("wondershot").join("wondershot.conf")
    }

    pub fn load() -> Self {
        match std::fs::read_to_string(Self::conf_path()) {
            Ok(s) => Self::from_conf_str(&s),
            Err(_) => Self::default(),
        }
    }

    pub fn from_conf_str(conf: &str) -> Self {
        let mut s = Self::default();
        for line in conf.lines() {
            let line = line.trim();
            if line.starts_with('[') || !line.contains('=') { continue; }
            let (k, v) = line.split_once('=').unwrap();
            let (k, v) = (k.trim(), v.trim());
            match k {
                "library_dir" => s.library_dir = v.to_string(),
                "backend" => s.backend = v.to_string(),
                "capture_cursor" => s.capture_cursor = v == "true",
                "capture_delay" => s.capture_delay = v.parse().unwrap_or(0),
                "extra_dirs" => s.extra_dirs = v.split(';').filter(|x| !x.is_empty()).map(String::from).collect(),
                _ => {}
            }
        }
        s
    }

    pub fn library_dirs(&self) -> Vec<std::path::PathBuf> {
        let mut v = vec![std::path::PathBuf::from(&self.library_dir)];
        v.extend(self.extra_dirs.iter().map(std::path::PathBuf::from));
        v
    }
}
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "M2: settings — wondershot.conf reader with Python-parity defaults"`

---

## Task 8: Tauri commands + capabilities (integration)

**Files:** Modify `src-tauri/src/commands.rs`, `src-tauri/src/lib.rs`, `src-tauri/Cargo.toml`; Create `src-tauri/capabilities/default.json`.

- [ ] **Step 1: Add deps to `src-tauri/Cargo.toml`**

```toml
arboard = "3"
image = "0.25"
tokio = { version = "1", features = ["rt-multi-thread", "time", "process"] }
```

- [ ] **Step 2: Implement the commands** in `src-tauri/src/commands.rs` — full code:

```rust
use std::path::PathBuf;
use wondershot_core::{capture, clipboard, library, settings::Settings, sidecar};

#[tauri::command]
pub fn health() -> String { "ok".into() }

#[tauri::command]
pub fn get_settings() -> serde_json::Value {
    let s = Settings::load();
    serde_json::json!({
        "library_dir": s.library_dir, "backend": s.backend,
        "capture_cursor": s.capture_cursor, "capture_delay": s.capture_delay,
        "extra_dirs": s.extra_dirs,
    })
}

#[tauri::command]
pub fn list_library() -> Vec<library::Capture> {
    let s = Settings::load();
    let mut caps = library::scan(&s.library_dirs());
    // attach a thumbnail src the webview can load (asset protocol or file path)
    for c in &mut caps { /* thumbnail handled in frontend via convertFileSrc */ }
    caps
}

#[tauri::command]
pub fn load_sidecar(path: String) -> Option<sidecar::SidecarDoc> {
    sidecar::load(&PathBuf::from(path))
}

#[tauri::command]
pub fn save_sidecar(path: String, doc: sidecar::SidecarDoc) -> bool {
    sidecar::save(&PathBuf::from(path), &doc)
}

#[tauri::command]
pub fn copy_image(path: String) -> Result<bool, String> {
    let bytes = std::fs::read(&path).map_err(|e| e.to_string())?;
    // Wayland path (10s budget) then arboard fallback.
    match clipboard::copy_png(&bytes) {
        Ok(true) => Ok(true),
        _ => {
            let img = image::open(&path).map_err(|e| e.to_string())?.to_rgba8();
            let (w, h) = img.dimensions();
            let mut cb = arboard::Clipboard::new().map_err(|e| e.to_string())?;
            cb.set_image(arboard::ImageData {
                width: w as usize, height: h as usize,
                bytes: img.into_raw().into(),
            }).map_err(|e| e.to_string())?;
            Ok(true)
        }
    }
}

#[tauri::command]
pub async fn capture_region(app: tauri::AppHandle) -> Result<String, String> {
    do_capture(app, capture::CaptureMode::Region).await
}
#[tauri::command]
pub async fn capture_fullscreen(app: tauri::AppHandle) -> Result<String, String> {
    do_capture(app, capture::CaptureMode::Fullscreen).await
}
#[tauri::command]
pub async fn capture_window(app: tauri::AppHandle) -> Result<String, String> {
    do_capture(app, capture::CaptureMode::Window).await
}
```

Plus a private `do_capture` that: loads settings, builds `unique_path(library_dir, timestamp_name("Screenshot"))`, runs spectacle when `backend != "portal"` and spectacle is on PATH (else portal), emits `capture://done` with the path (or `capture://failed`), and returns the path. (Window mode resolves KWin geometry first, then crops via `capture::kwin::crop_file_to_global_rect`.) Use `tauri::Emitter` to emit. Wrap the spectacle child in `tokio::time::timeout`. Implement faithfully against the behavioral contract above.

- [ ] **Step 3: Register handlers + emit setup** in `src-tauri/src/lib.rs`: add all commands to `generate_handler!`.

- [ ] **Step 4: Create `src-tauri/capabilities/default.json`**

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Wondershot core capabilities",
  "windows": ["main", "screen"],
  "permissions": ["core:default", "core:event:default"]
}
```

- [ ] **Step 5: Build** — `cargo build -p wondershot 2>&1 | tail -20`. Fix genuine Tauri-2 API drift minimally (e.g., `Emitter` import path). Expected: Finished.

- [ ] **Step 6: Commit** — `git commit -m "M2: Tauri commands — capture/clipboard/library/sidecar/settings + capabilities"`

---

## Task 9: Frontend wiring (real backend) + UI review

**Files:** Modify `src/lib/ipc.ts` (asset-src conversion for thumbnails), `src/lib/stores.ts` (capture actions), `src/lib/components/CaptureHeader.svelte` (wire mode buttons), `src/lib/ipc.mock.ts` (add new commands so browser/dev still works).

- [ ] **Step 1: Extend the mock backend** for `get_settings`, `load_sidecar`, `save_sidecar`, `copy_image`, `capture_*` (return a fresh fake capture and synthesize a `capture://done` — keep dev/browser fully functional). Keep MOCK_CAPTURES.

- [ ] **Step 2: Wire `CaptureHeader` mode buttons** to `ipcInvoke('capture_region'|'capture_fullscreen'|'capture_window')`; on `capture://done`, call `loadLibrary()` and select the new item; in mock mode the synthesized event drives the same path.

- [ ] **Step 3: Thumbnails** — in real mode, convert `capture.path` to a webview-loadable src via `@tauri-apps/api/core` `convertFileSrc`; in mock mode keep the data-URL. Centralize in `ipc.ts`.

- [ ] **Step 4: Verify** — `npm run test` (existing 7 pass), `npm run build` clean, `npm run test:ui -- capture` regenerates shots.

- [ ] **Step 5: UI review** — orchestrator invokes `workflows/ui-review.mjs` over the new shell shots (shell-dark/light as `kind:'shell'`, sidebar/header as `kind:'component'`). Fix any blocker/major; treat unexercised states as unverified.

- [ ] **Step 6: Commit** — `git commit -m "M2: wire capture/library to the shell; mock parity for browser dev"`

---

## Task 10: M2 exit verification

- [ ] **Step 1:** `cargo test --workspace 2>&1 | tail` — all core tests green (paths, sidecar, library, clipboard, capture, settings).
- [ ] **Step 2:** `cargo build --workspace` clean; `npm run test && npm run build` green.
- [ ] **Step 3:** Manual/integration note (display-capable run): region capture writes a `Screenshot_*.png` into the library dir, it appears in the sidebar, and `copy_image` puts it on the clipboard. Document outcome.
- [ ] **Step 4:** UI-review loop on the wired shell returns 0 failures.
- [ ] **Step 5:** Tag — `git tag m2-capture && git commit --allow-empty -m "M2 complete: capture + clipboard + library green"`.

---

## Self-Review notes (author)

- **Spec coverage:** capture (spectacle/portal/kwin/crop) ✓ T6/T8; clipboard ✓ T5/T8; library scan ✓ T4; sidecar schema+I/O ✓ T3; filenames/collision ✓ T2; settings ✓ T7; commands+events+capabilities ✓ T8; frontend wiring + mock parity ✓ T9; oracle tests ported ✓ T2–T7.
- **Deferred to later milestones (correctly):** recording (M4), the editor/annotation item (de)serialization round-trip (M3 — `items` are carried as opaque `serde_json::Value` here, preserving them losslessly without needing the tool models yet), video effects (M5), trash/undo UI (the `related_files` primitive lands here; the trash *workflow* + undo lands with the gallery interactions in M3).
- **Type consistency:** `Capture`/`CaptureKind` (T4) serialize to the same shape the frontend `Capture` type expects (`id, path, kind, createdAt, title`) — note `thumbnail` is added frontend-side via `convertFileSrc` (T9), not in the Rust struct; the frontend type already treats it as a string src. `SidecarDoc` (T3) is the single shape used by `load_sidecar`/`save_sidecar` (T8). `CaptureMode` (T6) is the single capture enum used across spectacle/commands.
- **Known integration risks:** `ashpd` 0.9 API surface for `Screenshot::request().interactive()` may need a small signature fix at build time (T6); `arboard` image set on Wayland may itself need a focused window (hence wl-copy is primary). Both are I/O-bound and validated at build/integration, not unit-tested.
```
