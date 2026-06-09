# Wondershot M6 — Packaging (Flatpak + curl|sh + ONNX runtime) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (this milestone is **sequential** — packaging has hard cutover ordering; do not fan out). Steps use checkbox (`- [ ]`).

**Goal:** Produce two working end-user installs of the **Tauri** Wondershot — a Flatpak and a `curl | sh` path — and resolve the deferred ONNX runtime so AI background removal builds and ships. Replace the Python-era `install.sh`, Flatpak manifest, and release CI with Tauri equivalents, keeping the same `app-id`, `.desktop` name, and library dir so M7 can cut over cleanly.

**Architecture:** Three deliverables share one binary (`wondershot`, the Tauri bundle): (1) the `ort` ONNX dependency switches from the broken `download-binaries` build script to **`load-dynamic`**, loading a `libonnxruntime.so` resolved at runtime — so `bgremove-onnx` compiles on the host and ships in both packages; (2) a **Flatpak manifest** rewritten for the Tauri app on `org.kde.Platform//6.9` (KDE runtime for KWin/spectacle/portals), with a webkit module resolved as the packaging unknown, reusing the existing x264/ffmpeg/wl-clipboard modules and bundling `libonnxruntime` + the u2net model; (3) an **`install.sh`** that fetches the latest Tauri bundle (AppImage) from GitHub Releases into `~/.local`. A rewritten `release.yml` builds all artifacts on a `v*` tag.

**Tech Stack:** Tauri 2 bundler (AppImage/rpm), `ort` 2.0-rc + ONNX Runtime (load-dynamic), Flatpak (`org.kde.Platform` / `org.kde.Sdk` + `org.freedesktop.Sdk.Extension.rust-stable` + node extension), flatpak-builder, GitHub Actions.

**Parity oracle:** the M5 `bgremove` pure tests must stay green with the feature ON; the Python `packaging/flatpak/*.yml` finish-args (portal/pipewire/pulse/KWin/filesystem grants) are the permission oracle to preserve; `install.sh`'s dependency-check UX is the oracle for the new installer's messaging.

---

## Behavioral contract (preserve)

- **App identity (cutover invariant):** `app-id` / Tauri `identifier` = `io.github.jackmusick.wondershot`; binary/`command` = `wondershot`; `.desktop` Name = `Wondershot`; icon id = `io.github.jackmusick.wondershot`. The library dir + `wondershot.conf` + `.sidecar` files are read as-is (no migration). Do **not** change any of these in M6 — M7 relies on them to supersede the old install.
- **Flatpak permissions (from the Python manifest — keep identical):** `--share=ipc`, `--socket=wayland`, `--socket=fallback-x11`, `--device=dri`, `--filesystem=xdg-run/pipewire-0`, `--socket=pulseaudio`, `--filesystem=xdg-pictures`, `--filesystem=xdg-videos`, `--talk-name=org.kde.KWin`, `--talk-name=org.freedesktop.portal.Desktop`, `--talk-name=org.freedesktop.portal.OpenURI`. (No network grant for the app at runtime — see model handling.)
- **bg-removal model:** u2net.onnx, sha/md5 `60024c5c889badc19c04ad937298a77b`, resolved by `bgremove::model_path()` → `~/.cache/wondershot/u2net.onnx` today. M6 keeps that cache path as the canonical runtime location and adds resolution order: (1) `WONDERSHOT_U2NET` env, (2) bundled resource dir, (3) cache dir, (4) download-on-first-use (md5-checked). The Flatpak **bundles** the model (offline builds); curl|sh keeps **download-on-first-use**.
- **ONNX runtime:** `ort` must NOT pull a binary at build time (the rc `download-binaries` script is broken upstream — ureq `_tls`). Use `ort`'s `load-dynamic` feature; resolve `libonnxruntime.so` at runtime via, in order, `ORT_DYLIB_PATH` env, a path next to the executable / bundled resource, then the system loader. Inference stays behind the `bgremove-onnx` cargo feature, but that feature now **compiles and links cleanly** on the host.
- **ffmpeg discovery (from M2/M5):** the video commands find ffmpeg as bundled-next-to-exe → PATH. Packaging must satisfy one of those (Flatpak builds ffmpeg; curl|sh checks PATH).

---

## File Structure

```
crates/wondershot-core/Cargo.toml            # ort: download-binaries → load-dynamic
crates/wondershot-core/src/bgremove.rs        # dylib + model resolution order; init ort env
src-tauri/Cargo.toml                          # forward a `bgremove` feature to wondershot-core
src-tauri/tauri.conf.json                     # bundle resources, rpm/deb deps, category, desktop
src-tauri/src/commands.rs                     # remove_background/ensure_bg_model use new resolution
packaging/flatpak/io.github.jackmusick.wondershot.yml   # REWRITE for Tauri
packaging/flatpak/onnxruntime.json            # (new) prebuilt libonnxruntime module/source
install.sh                                    # REWRITE for the Tauri AppImage
.github/workflows/release.yml                 # REWRITE: Tauri bundle + Flatpak on v* tag
docs/superpowers/plans/...-m6-packaging.md    # this plan; update roadmap on completion
```

---

## Task 1: Switch `ort` to load-dynamic so `bgremove-onnx` compiles

**Files:** `crates/wondershot-core/Cargo.toml`, `crates/wondershot-core/src/bgremove.rs`. Oracle: the existing `bgremove` tests must pass with the feature ON.

- [ ] **Step 1: change the `ort` features** in `crates/wondershot-core/Cargo.toml` — replace `download-binaries` with `load-dynamic`:

```toml
ort = { version = "=2.0.0-rc.12", default-features = false, features = ["load-dynamic"], optional = true }
```

- [ ] **Step 2: verify it now compiles** (was previously broken):

Run: `cargo build -p wondershot-core --features bgremove-onnx`
Expected: SUCCESS (no `ort-sys` build-script download failure). If `ort` errors at *link* time about a missing dylib, that's expected to surface at runtime, not build time — load-dynamic links lazily.

- [ ] **Step 3: add runtime dylib resolution** at the top of `remove_background` (inside `#[cfg(feature = "bgremove-onnx")]`), before building the session. `ort` reads `ORT_DYLIB_PATH`; set it if unset to a resolved path so callers needn't. Add this helper to `bgremove.rs`:

```rust
/// Resolve the onnxruntime shared library: explicit env wins, then a copy
/// shipped next to the executable / in a bundled resource dir, else the
/// system loader's default (returns None → ort uses its built-in name).
#[cfg(feature = "bgremove-onnx")]
fn ensure_ort_dylib() {
    if std::env::var_os("ORT_DYLIB_PATH").is_some() {
        return;
    }
    // Next to the executable (Tauri resource / AppImage layout).
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for name in ["libonnxruntime.so", "libonnxruntime.so.1.16.0"] {
                let cand = dir.join(name);
                if cand.exists() {
                    std::env::set_var("ORT_DYLIB_PATH", &cand);
                    return;
                }
            }
        }
    }
    // Otherwise leave unset: ort will dlopen "libonnxruntime.so" from the
    // system loader path (Flatpak ships it in /app/lib; rpm depends on it).
}
```

- [ ] **Step 4: call it** as the first line of the `#[cfg(feature = "bgremove-onnx")]` `remove_background`:

```rust
    ensure_ort_dylib();
```

- [ ] **Step 5: run the bgremove tests with the feature on:**

Run: `cargo test -p wondershot-core --features bgremove-onnx bgremove`
Expected: PASS — the pure `resize_to_input` / `normalize_input` / `apply_mask` tests are feature-independent and must stay green; no test requires the dylib (inference is gated behind model presence + is not unit-tested).

- [ ] **Step 6: confirm the default build is unchanged** (feature still off by default, no dylib needed):

Run: `cargo build --workspace`
Expected: SUCCESS, no `ort` linkage.

- [ ] **Step 7: Commit**

```bash
git add crates/wondershot-core/Cargo.toml crates/wondershot-core/src/bgremove.rs
git commit -m "M6: ort load-dynamic (fixes broken download-binaries build); runtime libonnxruntime resolution"
```

---

## Task 2: Model + dylib resolution order; forward the feature through src-tauri

**Files:** `crates/wondershot-core/src/bgremove.rs`, `src-tauri/Cargo.toml`, `src-tauri/src/commands.rs`.

- [ ] **Step 1: extend `model_path()` resolution** in `bgremove.rs`. Keep the cache dir as the canonical writable location, but check env + a bundled resource dir first. Replace the body of `model_path()` with resolution order, adding a `resolved_model_path()` that returns the first existing candidate (falling back to the cache path for the download target):

```rust
/// Canonical writable cache location for the model (download target).
pub fn model_path() -> PathBuf {
    let base = std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
            home.join(".cache")
        });
    base.join("wondershot").join("u2net.onnx")
}

/// First existing model across env / bundled resource / cache — what inference loads.
pub fn resolved_model_path() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("WONDERSHOT_U2NET") {
        let p = PathBuf::from(p);
        if p.exists() { return Some(p); }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // Tauri resources land beside the exe under a known subdir; also
            // accept a sibling file for the AppImage layout.
            for cand in [dir.join("u2net.onnx"), dir.join("resources").join("u2net.onnx")] {
                if cand.exists() { return Some(cand); }
            }
        }
    }
    let cache = model_path();
    if cache.exists() { return Some(cache); }
    None
}

pub fn model_available() -> bool {
    resolved_model_path().is_some()
}
```

- [ ] **Step 2: run the affected tests** (resolution is env/fs based; existing tests should still pass):

Run: `cargo test -p wondershot-core bgremove`
Expected: PASS.

- [ ] **Step 3: point the command at the resolved path.** In `src-tauri/src/commands.rs`, wherever `remove_background`/`ensure_bg_model`/`model_available` reference `bgremove::model_path()` for *loading*, switch the load site to `bgremove::resolved_model_path()` (download target stays `model_path()`). Read the file first; adjust the existing call. Expected shape:

```rust
let model = wondershot_core::bgremove::resolved_model_path()
    .ok_or_else(|| "background-removal model not installed".to_string())?;
// ... remove_background(&rgba, &model)
```

- [ ] **Step 4: add a `bgremove` feature to `src-tauri/Cargo.toml`** that forwards to the core crate, so release builds can opt in without editing the dep line:

```toml
[features]
bgremove = ["wondershot-core/bgremove-onnx"]

# (existing) wondershot-core dep stays as-is:
# wondershot-core = { path = "../crates/wondershot-core" }
```

- [ ] **Step 5: verify both build modes:**

Run: `cargo build -p wondershot --features bgremove` then `cargo build -p wondershot`
Expected: both SUCCESS.

- [ ] **Step 6: Commit**

```bash
git add crates/wondershot-core/src/bgremove.rs src-tauri/Cargo.toml src-tauri/src/commands.rs
git commit -m "M6: model resolution order (env/bundled/cache) + src-tauri bgremove feature forward"
```

---

## Task 3: Tauri bundle config — rpm/AppImage deps, resources, desktop metadata

**Files:** `src-tauri/tauri.conf.json`. No new code. This makes the Tauri bundler emit installable artifacts with correct runtime dependencies and category/desktop metadata. (Actual `tauri build` of the bundle is a heavy/manual gate at Task 7; this task makes the **config** correct and schema-valid.)

- [ ] **Step 1: read the current bundle block** (already `"targets": ["appimage","rpm"]`). Expand it to declare Linux runtime deps and desktop metadata. Edit the `"bundle"` object to:

```json
"bundle": {
  "active": true,
  "targets": ["appimage", "rpm"],
  "icon": ["icons/icon.png"],
  "category": "Utility",
  "shortDescription": "Screenshot & screen-recording with annotation",
  "longDescription": "Capture, annotate, record, and redact your screen on Wayland/KDE.",
  "linux": {
    "rpm": {
      "depends": ["ffmpeg", "wl-clipboard", "gstreamer1-plugin-pipewire", "onnxruntime"]
    }
  }
}
```

Note: `onnxruntime` is the Fedora package name; if it is not in the target repos the rpm install will fail on that dep — Task 7 verification decides whether to drop it to a documented optional. Keep it for now (Fedora ships `onnxruntime` in recent releases).

- [ ] **Step 2: validate the config is well-formed JSON and matches the Tauri schema:**

Run: `node -e "JSON.parse(require('fs').readFileSync('src-tauri/tauri.conf.json','utf8')); console.log('ok')"`
Expected: `ok`. (A full schema check happens implicitly when `tauri build` runs in Task 7.)

- [ ] **Step 3: confirm the identifier/productName are unchanged** (cutover invariant):

Run: `node -e "const c=require('./src-tauri/tauri.conf.json'); if(c.identifier!=='io.github.jackmusick.wondershot'||c.productName!=='Wondershot') throw new Error('identity changed'); console.log('identity ok')"`
Expected: `identity ok`.

- [ ] **Step 4: Commit**

```bash
git add src-tauri/tauri.conf.json
git commit -m "M6: Tauri bundle config — rpm runtime deps, desktop category/description"
```

---

## Task 4: Rewrite the Flatpak manifest for the Tauri app

**Files:** `packaging/flatpak/io.github.jackmusick.wondershot.yml` (rewrite), `packaging/flatpak/onnxruntime.json` (new). Oracle: keep the Python manifest's `finish-args` permissions verbatim; reuse its x264/ffmpeg/wl-clipboard modules.

The Python `wondershot` pip module is replaced by a Tauri build module: SvelteKit frontend (node) + Rust binary (rust-stable extension), installed plus the `.desktop`/icon, the bundled u2net model, and `libonnxruntime`.

- [ ] **Step 1: write the new manifest.** Replace the file with (keep x264/ffmpeg/wl-clipboard modules as they are in the current file — repeated here so the file is self-contained):

```yaml
# Flatpak manifest — the Tauri Wondershot bundle on the KDE runtime.
#
# Local build + run:
#   flatpak install flathub org.kde.Platform//6.9 org.kde.Sdk//6.9 \
#     org.freedesktop.Sdk.Extension.rust-stable//24.08 \
#     org.freedesktop.Sdk.Extension.node20//24.08
#   flatpak-builder --user --install --force-clean build-dir \
#     packaging/flatpak/io.github.jackmusick.wondershot.yml
#   flatpak run io.github.jackmusick.wondershot
#
# Flathub builds are offline: the node + cargo modules below need
# vendored sources (flatpak-node-generator / flatpak-cargo-generator)
# before submission. The --share=network build form here is for local
# builds and CI artifacts.
app-id: io.github.jackmusick.wondershot
runtime: org.kde.Platform
runtime-version: '6.9'
sdk: org.kde.Sdk
sdk-extensions:
  - org.freedesktop.Sdk.Extension.rust-stable
  - org.freedesktop.Sdk.Extension.node20
command: wondershot

build-options:
  append-path: /usr/lib/sdk/rust-stable/bin:/usr/lib/sdk/node20/bin
  env:
    CARGO_HOME: /run/build/wondershot/cargo

finish-args:
  - --share=ipc
  - --socket=wayland
  - --socket=fallback-x11
  - --device=dri
  - --filesystem=xdg-run/pipewire-0
  - --socket=pulseaudio
  - --filesystem=xdg-pictures
  - --filesystem=xdg-videos
  - --talk-name=org.kde.KWin
  - --talk-name=org.freedesktop.portal.Desktop
  - --talk-name=org.freedesktop.portal.OpenURI

modules:
  # --- webkit: the packaging unknown -------------------------------------
  # Tauri 2's Linux webview needs webkit2gtk-4.1 (gtk3). The KDE runtime
  # is Qt-based and does NOT ship it. We pull the shared GTK/webkit module
  # set from the flathub shared-modules + a webkitgtk build, OR (preferred,
  # if available) the org.freedesktop runtime's webkit. Task 4 step 3
  # resolves which path the runtime actually supports.
  - name: webkitgtk-placeholder
    # RESOLVED IN STEP 3 — replaced with either a shared-modules include or
    # a webkitgtk module. Left as a buildless no-op until verified so the
    # rest of the manifest is reviewable.
    buildsystem: simple
    build-commands:
      - "true"

  # --- onnxruntime: prebuilt shared lib for ort load-dynamic --------------
  - onnxruntime.json

  # --- libx264 (unchanged from the Python manifest) ----------------------
  - name: x264
    config-opts:
      - --enable-shared
      - --disable-cli
    sources:
      - type: archive
        url: https://code.videolan.org/videolan/x264/-/archive/b35605ace3ddf7c1a5d67a2eb553f034aef41d55/x264-b35605ace3ddf7c1a5d67a2eb553f034aef41d55.tar.bz2
        sha256: 6eeb82934e69fd51e043bd8c5b0d152839638d1ce7aa4eea65a3fedcf83ff224

  # --- ffmpeg CLI (unchanged) --------------------------------------------
  - name: ffmpeg
    config-opts:
      - --disable-debug
      - --disable-doc
      - --disable-ffplay
      - --enable-gpl
      - --enable-libx264
      - --enable-shared
    sources:
      - type: archive
        url: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz
        sha256: 40973d44970dbc83ef302b0609f2e74982be2d85916dd2ee7472d30678a7abe6

  # --- wl-clipboard (unchanged) ------------------------------------------
  - name: wl-clipboard
    buildsystem: meson
    sources:
      - type: archive
        url: https://github.com/bugaevc/wl-clipboard/archive/refs/tags/v2.2.1.tar.gz
        sha256: 6eb8081207fb5581d1d82c4bcd9587205a31a3d47bea3ebeb7f41aa1143783eb

  # --- u2net model (bundled; offline-safe) -------------------------------
  - name: u2net-model
    buildsystem: simple
    build-commands:
      - install -Dm644 u2net.onnx /app/share/wondershot/u2net.onnx
    sources:
      - type: file
        url: https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx
        sha256: 8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491

  # --- the Tauri app -----------------------------------------------------
  - name: wondershot
    buildsystem: simple
    build-options:
      build-args:
        - --share=network   # cargo + npm fetch; remove for Flathub (vendored)
    build-commands:
      - npm ci
      - npm run tauri build -- --no-bundle --features bgremove
      - install -Dm755 src-tauri/target/release/wondershot /app/bin/wondershot
      - install -Dm644 src-tauri/icons/icon.png
        /app/share/icons/hicolor/512x512/apps/${FLATPAK_ID}.png
      - install -Dm644 packaging/flatpak/${FLATPAK_ID}.desktop
        /app/share/applications/${FLATPAK_ID}.desktop
      # u2net is resolved via WONDERSHOT_U2NET → /app/share/wondershot
    sources:
      - type: dir
        path: ../..
```

- [ ] **Step 2: create `packaging/flatpak/onnxruntime.json`** — a prebuilt onnxruntime that installs `libonnxruntime.so` into `/app/lib` (where the system loader finds it for `ort` load-dynamic). Use the official linux-x64 release tarball:

```json
{
  "name": "onnxruntime",
  "buildsystem": "simple",
  "build-commands": [
    "install -Dm755 lib/libonnxruntime.so.1.16.3 /app/lib/libonnxruntime.so.1.16.3",
    "ln -s libonnxruntime.so.1.16.3 /app/lib/libonnxruntime.so"
  ],
  "sources": [
    {
      "type": "archive",
      "url": "https://github.com/microsoft/onnxruntime/releases/download/v1.16.3/onnxruntime-linux-x64-1.16.3.tgz",
      "sha256": "dd6e4e26b288d3b6ceb805f6bd0b80fa8b76cbee8f6cfd3c8b8d6e0f5b7c4f7a",
      "strip-components": 1
    }
  ]
}
```

> Note: the two `sha256` values above (u2net model, onnxruntime tarball) are placeholders that MUST be replaced with the real digests in Step 4 — flatpak-builder fails closed on a mismatch, so a wrong hash cannot ship silently. Do not commit until verified.

- [ ] **Step 3: resolve the webkit unknown.** Determine whether `org.kde.Platform//6.9` provides `webkit2gtk-4.1`:

Run: `flatpak run --command=sh --devel org.kde.Sdk//6.9 -c 'pkg-config --exists webkit2gtk-4.1 && echo HAVE_WEBKIT || echo NO_WEBKIT'`
- If `HAVE_WEBKIT`: delete the `webkitgtk-placeholder` module entirely.
- If `NO_WEBKIT` (expected): replace `webkitgtk-placeholder` with the flathub **shared-modules** webkitgtk include or a pinned `webkitgtk` module. Add the shared-modules submodule path or inline the module; document the choice in a comment.
- If `flatpak`/the runtime isn't installed on this machine: leave the placeholder, mark this step **BLOCKED — manual** in the commit message, and note it in the roadmap; the manifest is still reviewable and the rest of M6 proceeds.

- [ ] **Step 4: fetch the real sha256 digests** for the u2net model and the onnxruntime tarball (only if network is available), and replace the placeholders:

Run: `curl -fsSL https://github.com/microsoft/onnxruntime/releases/download/v1.16.3/onnxruntime-linux-x64-1.16.3.tgz | sha256sum` (and similarly for the model URL).
Expected: a 64-hex digest; paste it in. If offline, leave the placeholder and mark **BLOCKED — needs network** in the commit message.

- [ ] **Step 5: create the Tauri `.desktop` file** at `packaging/flatpak/io.github.jackmusick.wondershot.desktop` (the Python one lived in `wondershot/data/`; the Tauri build references this path). Content:

```ini
[Desktop Entry]
Type=Application
Name=Wondershot
Comment=Screenshot & screen-recording with annotation
Exec=wondershot
Icon=io.github.jackmusick.wondershot
Terminal=false
Categories=Utility;Graphics;
StartupNotify=true
```

- [ ] **Step 6: validate YAML + JSON parse** (no flatpak-builder run here — that's Task 7):

Run: `python3 -c "import yaml,json; yaml.safe_load(open('packaging/flatpak/io.github.jackmusick.wondershot.yml')); json.load(open('packaging/flatpak/onnxruntime.json')); print('parse ok')"`
Expected: `parse ok`.

- [ ] **Step 7: Commit**

```bash
git add packaging/flatpak/
git commit -m "M6: rewrite Flatpak manifest for Tauri (rust/node SDK, onnxruntime+u2net bundled, webkit resolution)"
```

---

## Task 5: Rewrite `install.sh` for the Tauri AppImage

**Files:** `install.sh` (rewrite). Oracle: keep the Python installer's dependency-check UX (check, don't sudo; print the exact dnf/apt command). The new path downloads the latest AppImage from GitHub Releases into `~/.local`, no venv.

- [ ] **Step 1: rewrite `install.sh`** to fetch the latest release AppImage:

```sh
#!/bin/sh
# Wondershot installer/updater for Linux (Tauri AppImage path).
#
#   curl -fsSL https://raw.githubusercontent.com/jackmusick/wondershot/main/install.sh | sh
#
# User-local, no sudo: the AppImage lands in ~/.local/share/wondershot,
# a `wondershot` launcher in ~/.local/bin, and a .desktop entry. Re-run to
# update to the latest release. Flatpak remains the recommended install;
# this is the convenient path.
#
# System packages are CHECKED, not installed (a piped script can't sudo
# safely) — you get the exact command to run.
set -eu

REPO="jackmusick/wondershot"
HOME_DIR="${WONDERSHOT_HOME:-$HOME/.local/share/wondershot}"
BIN_DIR="${WONDERSHOT_BIN:-$HOME/.local/bin}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
APPIMAGE="$HOME_DIR/Wondershot.AppImage"

say() { printf '\033[1m[wondershot]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[wondershot]\033[0m %s\n' "$*" >&2; exit 1; }

# -- dependency checks ---------------------------------------------------------
missing=""
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"
gst-inspect-1.0 pipewiresrc >/dev/null 2>&1 || missing="$missing gst-pipewire"
if [ -n "${WAYLAND_DISPLAY:-}" ] && ! command -v wl-copy >/dev/null 2>&1; then
    missing="$missing wl-clipboard"
fi

if [ -n "$missing" ]; then
    say "missing system packages:$missing"
    if command -v dnf >/dev/null 2>&1; then
        say "install them with:"
        say "  sudo dnf install ffmpeg gstreamer1-plugin-pipewire wl-clipboard"
    elif command -v apt-get >/dev/null 2>&1; then
        say "install them with:"
        say "  sudo apt install ffmpeg gstreamer1.0-pipewire wl-clipboard"
    else
        say "install ffmpeg, the GStreamer PipeWire plugin, and wl-clipboard"
        say "with your distro's package manager."
    fi
    fail "re-run this script once they're installed"
fi
# onnxruntime is optional (AI background removal only); not a hard requirement.

# -- download latest AppImage --------------------------------------------------
mkdir -p "$HOME_DIR" "$BIN_DIR" "$APP_DIR"

say "finding latest release"
ASSET_URL=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | grep -o '"browser_download_url": *"[^"]*\.AppImage"' \
    | head -n1 | sed 's/.*"browser_download_url": *"\([^"]*\)"/\1/')
[ -n "$ASSET_URL" ] || fail "no .AppImage asset in the latest release yet"

say "downloading $ASSET_URL"
curl -fsSL "$ASSET_URL" -o "$APPIMAGE.tmp"
chmod +x "$APPIMAGE.tmp"
mv "$APPIMAGE.tmp" "$APPIMAGE"

ln -sf "$APPIMAGE" "$BIN_DIR/wondershot"

# -- desktop entry -------------------------------------------------------------
cat > "$APP_DIR/io.github.jackmusick.wondershot.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Wondershot
Comment=Screenshot & screen-recording with annotation
Exec=$BIN_DIR/wondershot
Icon=io.github.jackmusick.wondershot
Terminal=false
Categories=Utility;Graphics;
StartupNotify=true
EOF

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) say "NOTE: $BIN_DIR is not on your PATH — add it to use 'wondershot'" ;;
esac

say "done. Run: wondershot"
say "  update later: re-run this same command"
```

- [ ] **Step 2: shellcheck / syntax-check** the script:

Run: `sh -n install.sh && (command -v shellcheck >/dev/null && shellcheck install.sh || echo "shellcheck not installed — sh -n passed")`
Expected: `sh -n` passes (exit 0); shellcheck clean if present.

- [ ] **Step 3: dry verify the asset-URL parse** against a sample GitHub releases JSON (no real release needed) to confirm the grep/sed extracts an `.AppImage` url:

Run:
```sh
printf '%s' '{"assets":[{"browser_download_url":"https://x/Wondershot_0.1.0_amd64.AppImage"}]}' \
  | grep -o '"browser_download_url": *"[^"]*\.AppImage"' \
  | sed 's/.*"browser_download_url": *"\([^"]*\)"/\1/'
```
Expected: `https://x/Wondershot_0.1.0_amd64.AppImage`. (GitHub's real JSON has a space after the colon; the sample includes it to match.)

> If the sample prints nothing, the spacing in the grep pattern doesn't match GitHub's format — adjust the pattern to tolerate optional whitespace and re-run before committing.

- [ ] **Step 4: Commit**

```bash
git add install.sh
git commit -m "M6: rewrite install.sh for the Tauri AppImage (download latest release, no venv)"
```

---

## Task 6: Rewrite `release.yml` to build Tauri bundles + Flatpak on tag

**Files:** `.github/workflows/release.yml` (rewrite the Linux job; the Windows PyInstaller job is Python-era and out of scope for the Linux-first rewrite — remove it or leave a comment that Windows packaging is deferred to a later milestone). Per the roadmap, M6 targets the Flatpak + curl|sh (Linux). Replace the workflow with a Linux Tauri bundle job and a Flatpak job.

- [ ] **Step 1: rewrite `.github/workflows/release.yml`:**

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  tauri-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - uses: dtolnay/rust-toolchain@stable
      - name: Tauri Linux build deps
        run: |
          sudo apt-get update
          sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev \
            libayatana-appindicator3-dev librsvg2-dev patchelf \
            ffmpeg libgstreamer1.0-dev gstreamer1.0-pipewire \
            libonnxruntime-dev || true
      - run: npm ci
      - name: Build Tauri bundles
        run: npm run tauri build -- --features bgremove
      - name: Collect artifacts
        run: |
          mkdir -p dist
          find src-tauri/target/release/bundle -name '*.AppImage' -exec cp {} dist/ \;
          find src-tauri/target/release/bundle -name '*.rpm' -exec cp {} dist/ \;
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/*

  flatpak:
    runs-on: ubuntu-latest
    container:
      image: bilelmoussaoui/flatpak-github-actions:kde-6.9
      options: --privileged
    steps:
      - uses: actions/checkout@v4
      - uses: flatpak/flatpak-github-actions/flatpak-builder@v6
        with:
          bundle: wondershot.flatpak
          manifest-path: packaging/flatpak/io.github.jackmusick.wondershot.yml
          cache-key: flatpak-builder-${{ github.sha }}
      - uses: softprops/action-gh-release@v2
        with:
          files: wondershot.flatpak
```

- [ ] **Step 2: validate the workflow YAML parses:**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "M6: rewrite release.yml — Tauri Linux bundles + Flatpak on v* tag"
```

---

## Task 7: M6 exit verification (build + launch gates)

These gates need a full toolchain / display and may run on the host or be deferred to a manual run; document the outcome honestly (the roadmap pattern: "X verified; Y pending a manual run").

- [ ] **Step 1: workspace still green** with and without the AI feature:

Run: `cargo build --workspace && cargo test --workspace && cargo build -p wondershot --features bgremove`
Expected: all SUCCESS; tests PASS.

- [ ] **Step 2: frontend green:**

Run: `npm run test && npm run build`
Expected: SUCCESS.

- [ ] **Step 3 (heavy/manual gate): Tauri bundle build.** Requires the apt deps from Task 6 on the host:

Run: `npm run tauri build -- --features bgremove`
Expected: an `.AppImage` and an `.rpm` under `src-tauri/target/release/bundle/`. Document the artifact paths. If host build deps are missing, mark **PENDING — CI gate** (the release.yml job covers it) and proceed.

- [ ] **Step 4 (heavy/manual gate): Flatpak build + launch.** Requires flatpak + the KDE runtime + SDK extensions:

Run: `flatpak-builder --user --install --force-clean build-dir packaging/flatpak/io.github.jackmusick.wondershot.yml && flatpak run io.github.jackmusick.wondershot`
Expected: the app window opens (the same shell as the Tauri dev app). Document whether the webkit module resolved and the app launched. If flatpak/runtime unavailable, mark **PENDING — manual** and note in the roadmap.

- [ ] **Step 5 (manual gate): curl|sh launch.** After a release exists (or simulate by pointing `REPO` at a fork with an AppImage), run `install.sh` and confirm `wondershot` launches. Until a real release asset exists this is **PENDING — needs first release**; verify the script logic via Task 5 Step 3 in the meantime.

- [ ] **Step 6: update the roadmap** — mark M6 status (✅ COMPLETE or the honest partial, e.g. "config + manifests + installer landed and parse-verified; live Flatpak/bundle builds pending a toolchain/display run") and add the M6 notes block (webkit resolution outcome, model bundling decision, what's CI-gated vs host-verified). Then tag:

```bash
git add docs/superpowers/plans/2026-06-08-wondershot-tauri-rewrite-roadmap.md
git commit -m "roadmap: M6 packaging status + notes"
git tag m6-packaging && git commit --allow-empty -m "M6 complete: Flatpak + curl|sh + ONNX runtime resolved (live builds gated)"
```

---

## Self-Review notes (author)

- **Spec coverage:** Flatpak for the Tauri app (webkitgtk-6.0/webkit resolution, reuse ffmpeg/x264, bundle u2net) ✓ T4; `.rpm`/AppImage via Tauri bundler ✓ T3 (config) + T7 (build); `curl|sh` ✓ T5; cutover invariants (app-id/.desktop/library) preserved ✓ T3 step 3 + the contract; the deferred ONNX-runtime resolution (load-dynamic + bundled libonnxruntime, u2net bundling) folded in from M5 ✓ T1/T2/T4.
- **Placeholder scan:** the only deliberate placeholders are the two flatpak `sha256` digests (T4 step 2) and the webkit module (T4 step 1), each with an explicit resolution step (T4 step 3/4) and a fail-closed note — flatpak-builder rejects wrong hashes, so they cannot ship silently. The Tauri rpm `onnxruntime` dep name is flagged for T7 verification.
- **Type consistency:** `model_path()` (writable cache / download target) vs `resolved_model_path()` (first-existing loader path) are distinct and used consistently — commands load via `resolved_model_path()`, download via `model_path()`. `ensure_ort_dylib()` sets `ORT_DYLIB_PATH`; the Flatpak ships `libonnxruntime.so` in `/app/lib` (system loader) and the model in `/app/share/wondershot` resolved via `WONDERSHOT_U2NET`. The `bgremove` src-tauri feature → `wondershot-core/bgremove-onnx`.
- **Sequential, no UI:** M6 has no new UI surfaces (packaging infra), so the ui-review workflow does not apply here; the goal's "ui-review after every UI task" is vacuously satisfied. Execution is inline/sequential per the roadmap's M6 shape.
- **Honest gates:** the three heavy steps (Tauri bundle build, flatpak-builder, curl|sh launch) depend on toolchain/display/first-release and are explicitly marked manual/CI gates — config and scripts are made correct and parse-verified now; live builds are documented as pending where the environment can't run them, matching the M2/M4/M5 precedent.
```
