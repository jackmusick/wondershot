use std::path::Path;
use std::sync::Mutex;
use wondershot_core::{bgremove, capture, clipboard, library, paths, settings::Settings, sidecar, video};
use wondershot_core::record::{files, pipeline, portal, recorder};
use crate::graph;

#[tauri::command]
pub fn health() -> String {
    "ok".into()
}

#[tauri::command]
pub fn get_settings() -> serde_json::Value {
    let s = Settings::load();
    let mut out = serde_json::json!({
        "library_dir": s.library_dir,
        "backend": s.backend,
        "capture_cursor": s.capture_cursor,
        "capture_delay": s.capture_delay,
        "extra_dirs": s.extra_dirs,
        "mic_enabled": s.mic_enabled,
        "mic_device": s.mic_device,
        "noise_suppression": s.noise_suppression,
        "record_cursor_halo": s.record_cursor_halo,
        "record_countdown": s.record_countdown,
        "camera_device": s.camera_device,
        "hotkey_capture": s.hotkey_capture,
        "copy_after_capture": s.copy_after_capture,
        "show_gallery_after_capture": s.show_gallery_after_capture,
        "pin_on_top": s.pin_on_top,
        "quick_bar_enabled": s.quick_bar_enabled,
        "quick_bar_timeout": s.quick_bar_timeout,
        "stroke_width": s.stroke_width,
        "font_size": s.font_size,
        "tool_color": s.tool_color,
        "video_blur_strength": s.video_blur_strength,
        "gif_fps": s.gif_fps,
        "gif_max_width": s.gif_max_width,
        "effect_rounded": s.effect_rounded,
        "effect_corner_radius": s.effect_corner_radius,
        "effect_fade": s.effect_fade,
        "effect_fade_height": s.effect_fade_height,
    });
    // Surface the preserved-but-unmodeled keys (sharing creds, AI endpoint, …)
    // so the Settings Sharing/AI tabs can read them. They round-trip via `extra`.
    if let Some(obj) = out.as_object_mut() {
        for (k, v) in &s.extra {
            obj.insert(k.clone(), serde_json::Value::String(v.clone()));
        }
    }
    out
}

/// Overlay the provided keys onto the current Settings and persist. Only keys
/// present in `values` are applied; JSON numbers/bools/strings are coerced to
/// the field types.
#[tauri::command]
pub fn set_settings(
    app: tauri::AppHandle,
    watch: tauri::State<crate::watcher::LibWatch>,
    values: serde_json::Value,
) -> Result<(), String> {
    let mut s = Settings::load();
    let obj = values
        .as_object()
        .ok_or_else(|| "set_settings expects an object".to_string())?;

    let get_str = |v: &serde_json::Value| v.as_str().map(|x| x.to_string());
    let get_bool = |v: &serde_json::Value| v.as_bool();
    let get_u32 = |v: &serde_json::Value| {
        v.as_u64()
            .map(|n| n as u32)
            .or_else(|| v.as_str().and_then(|x| x.parse::<u32>().ok()))
    };

    for (k, v) in obj {
        match k.as_str() {
            "library_dir" => if let Some(x) = get_str(v) { s.library_dir = x },
            "backend" => if let Some(x) = get_str(v) { s.backend = x },
            "capture_cursor" => if let Some(x) = get_bool(v) { s.capture_cursor = x },
            "capture_delay" => if let Some(x) = get_u32(v) { s.capture_delay = x },
            "extra_dirs" => {
                if let Some(arr) = v.as_array() {
                    s.extra_dirs = arr
                        .iter()
                        .filter_map(|x| x.as_str().map(String::from))
                        .filter(|x| !x.is_empty())
                        .collect();
                } else if let Some(x) = v.as_str() {
                    s.extra_dirs = x
                        .split(';')
                        .filter(|x| !x.is_empty())
                        .map(String::from)
                        .collect();
                }
            }
            "mic_enabled" => if let Some(x) = get_bool(v) { s.mic_enabled = x },
            "mic_device" => if let Some(x) = get_str(v) { s.mic_device = x },
            "noise_suppression" => if let Some(x) = get_bool(v) { s.noise_suppression = x },
            "record_cursor_halo" => if let Some(x) = get_bool(v) { s.record_cursor_halo = x },
            "record_countdown" => if let Some(x) = get_u32(v) { s.record_countdown = x },
            "camera_device" => if let Some(x) = get_str(v) { s.camera_device = x },
            "hotkey_capture" => if let Some(x) = get_str(v) { s.hotkey_capture = x },
            "copy_after_capture" => if let Some(x) = get_bool(v) { s.copy_after_capture = x },
            "show_gallery_after_capture" => if let Some(x) = get_bool(v) { s.show_gallery_after_capture = x },
            "pin_on_top" => if let Some(x) = get_bool(v) { s.pin_on_top = x },
            "quick_bar_enabled" => if let Some(x) = get_bool(v) { s.quick_bar_enabled = x },
            "quick_bar_timeout" => if let Some(x) = get_u32(v) { s.quick_bar_timeout = x },
            "stroke_width" => if let Some(x) = get_u32(v) { s.stroke_width = x },
            "font_size" => if let Some(x) = get_u32(v) { s.font_size = x },
            "tool_color" => if let Some(x) = get_str(v) { s.tool_color = x },
            "video_blur_strength" => if let Some(x) = get_u32(v) { s.video_blur_strength = x },
            "gif_fps" => if let Some(x) = get_u32(v) { s.gif_fps = x },
            "gif_max_width" => if let Some(x) = get_u32(v) { s.gif_max_width = x },
            "effect_rounded" => if let Some(x) = get_bool(v) { s.effect_rounded = x },
            "effect_corner_radius" => if let Some(x) = get_u32(v) { s.effect_corner_radius = x },
            "effect_fade" => if let Some(x) = get_bool(v) { s.effect_fade = x },
            "effect_fade_height" => if let Some(x) = get_u32(v) { s.effect_fade_height = x },
            // Unmodeled keys (sharing creds, AI endpoint, …): store as strings in
            // `extra` so they persist back to the shared conf. Numbers/bools are
            // stringified to match QSettings' text format.
            _ => {
                let sval = match v {
                    serde_json::Value::String(x) => Some(x.clone()),
                    serde_json::Value::Bool(b) => Some(b.to_string()),
                    serde_json::Value::Number(n) => Some(n.to_string()),
                    serde_json::Value::Null => Some(String::new()),
                    _ => None,
                };
                if let Some(x) = sval {
                    s.extra.insert(k.clone(), x);
                }
            }
        }
    }
    s.save().map_err(|e| e.to_string())?;
    // Library / extra dirs may have changed — rebind the live folder watcher.
    crate::watcher::rewatch(&app, watch.inner());
    Ok(())
}

#[tauri::command]
pub fn list_library() -> Vec<library::Capture> {
    let s = Settings::load();
    library::scan(&s.library_dirs())
}

#[tauri::command]
pub fn load_sidecar(path: String) -> Option<sidecar::SidecarDoc> {
    sidecar::load(Path::new(&path))
}

#[tauri::command]
pub fn save_sidecar(path: String, doc: sidecar::SidecarDoc) -> bool {
    sidecar::save(Path::new(&path), &doc)
}

#[tauri::command]
pub fn copy_image(path: String) -> Result<bool, String> {
    let bytes = std::fs::read(&path).map_err(|e| e.to_string())?;
    match clipboard::copy_png(&bytes) {
        Ok(true) => Ok(true),
        _ => {
            // Native clipboard fallback (X11 / non-Wayland).
            let img = image::open(&path).map_err(|e| e.to_string())?.to_rgba8();
            let (w, h) = img.dimensions();
            let mut cb = arboard::Clipboard::new().map_err(|e| e.to_string())?;
            cb.set_image(arboard::ImageData {
                width: w as usize,
                height: h as usize,
                bytes: std::borrow::Cow::Owned(img.into_raw()),
            })
            .map_err(|e| e.to_string())?;
            Ok(true)
        }
    }
}

fn in_flatpak() -> bool {
    std::env::var_os("FLATPAK_ID").is_some() || Path::new("/.flatpak-info").exists()
}

/// Whether the KDE Spectacle capture tool is reachable. In a Flatpak the sandbox
/// PATH won't have it, but the HOST does — probe via `flatpak-spawn --host`.
fn spectacle_on_path() -> bool {
    if in_flatpak() {
        return std::process::Command::new("flatpak-spawn")
            .args(["--host", "which", "spectacle"])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
    }
    std::env::var_os("PATH").map_or(false, |paths| {
        std::env::split_paths(&paths).any(|p| p.join("spectacle").is_file())
    })
}

async fn run_spectacle(mode: capture::CaptureMode, out: &str, cursor: bool, delay: u32) -> Result<(), String> {
    let args = capture::spectacle::spectacle_args(mode, out, cursor, delay);
    // In a Flatpak, run the HOST spectacle (its rectangular drag-selection UI)
    // via flatpak-spawn; the output path is under the user's home, which both the
    // host and the sandbox (--filesystem=home) can see.
    let mut cmd = if in_flatpak() {
        let mut c = tokio::process::Command::new("flatpak-spawn");
        c.arg("--host").arg("spectacle").args(&args);
        c
    } else {
        let mut c = tokio::process::Command::new("spectacle");
        c.args(&args);
        c
    };
    let status = cmd
        .status()
        .await
        .map_err(|e| format!("could not start spectacle: {e}"))?;
    if !status.success() {
        return Err("spectacle exited non-zero (cancelled?)".into());
    }
    if !Path::new(out).exists() {
        return Err("spectacle produced no output file".into());
    }
    Ok(())
}

async fn do_capture(app: tauri::AppHandle, mode: capture::CaptureMode) -> Result<String, String> {
    use tauri::Emitter;
    let s = Settings::load();
    let _ = std::fs::create_dir_all(&s.library_dir);
    let out = paths::unique_path(Path::new(&s.library_dir), &paths::timestamp_name("Screenshot"));
    let out_str = out.to_string_lossy().to_string();

    let result: Result<String, String> = if s.backend != "portal" && spectacle_on_path() {
        match run_spectacle(mode, &out_str, s.capture_cursor, s.capture_delay).await {
            Ok(()) => Ok(out_str.clone()),
            Err(e) => Err(e),
        }
    } else {
        // Portal fallback: interactive for region/window, non-interactive for fullscreen.
        let interactive = mode != capture::CaptureMode::Fullscreen;
        match capture::portal::screenshot(interactive).await {
            Some(p) => {
                if p.parent() == Some(Path::new(&s.library_dir)) {
                    Ok(p.to_string_lossy().to_string())
                } else {
                    match std::fs::rename(&p, &out).or_else(|_| std::fs::copy(&p, &out).map(|_| ())) {
                        Ok(()) => Ok(out_str.clone()),
                        Err(e) => Err(format!("could not move screenshot: {e}")),
                    }
                }
            }
            None => Err("portal screenshot cancelled or failed".into()),
        }
    };

    match &result {
        Ok(path) => { let _ = app.emit("capture://done", path.clone()); }
        Err(msg) => { let _ = app.emit("capture://failed", msg.clone()); }
    }
    result
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

// --- imageops: raster pixel operations -------------------------------------

/// PNG-encode an RGBA image and base64-encode the result.
fn encode_png_b64(img: &image::RgbaImage) -> Result<String, String> {
    use base64::Engine;
    use std::io::Cursor;
    let mut buf: Vec<u8> = Vec::new();
    img.write_to(&mut Cursor::new(&mut buf), image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(base64::engine::general_purpose::STANDARD.encode(&buf))
}

/// The image pixelate/blur patches must be computed from: the EDITABLE base
/// (`.wondershot/<name>.base.0.png`) when one exists, not the flattened
/// library PNG — after a save the library file has annotations (including the
/// redact boxes themselves) baked in, so patching from it would blur the
/// already-redacted pixels instead of the original image.
fn open_patch_source(path: &str) -> Result<image::RgbaImage, String> {
    let p = Path::new(path);
    let base0 = sidecar::base_path(p, 0);
    let src = if base0.exists() { base0 } else { p.to_path_buf() };
    Ok(image::open(&src).map_err(|e| e.to_string())?.to_rgba8())
}

/// Pixelate the rect region of the base PNG; returns the patch as base64 PNG.
#[tauri::command]
pub fn pixelate_patch(path: String, rect: (u32, u32, u32, u32), block: u32) -> Result<String, String> {
    let img = open_patch_source(&path)?;
    let patch = wondershot_core::imageops::pixelated_patch(&img, rect, block);
    encode_png_b64(&patch)
}

/// Gaussian-blur the rect region of the base PNG; returns the patch as base64 PNG.
#[tauri::command]
pub fn blur_patch(path: String, rect: (u32, u32, u32, u32), radius: u32) -> Result<String, String> {
    let img = open_patch_source(&path)?;
    let patch = wondershot_core::imageops::blurred_patch(&img, rect, radius);
    encode_png_b64(&patch)
}

/// Crop the base PNG to `rect`, write the result as a NEW base file, and
/// return the new base file's path. The next base index is derived from the
/// sidecar's `bases` count (falling back to 0).
#[tauri::command]
pub fn crop_base(path: String, rect: (u32, u32, u32, u32)) -> Result<String, String> {
    let img = image::open(&path).map_err(|e| e.to_string())?.to_rgba8();
    let (x, y, w, h) = rect;
    let out = wondershot_core::imageops::crop(&img, x, y, w, h);
    write_new_base(&path, &out)
}

/// Remove a band from the base PNG (rows if `horizontal`, else columns),
/// join the halves, write the result as a NEW base file, and return its path.
#[tauri::command]
pub fn cutout_base(path: String, a: u32, b: u32, horizontal: bool) -> Result<String, String> {
    let img = image::open(&path).map_err(|e| e.to_string())?.to_rgba8();
    let out = wondershot_core::imageops::cut_out(&img, a, b, horizontal);
    write_new_base(&path, &out)
}

// --- AI background removal (M5 T3) ------------------------------------------

/// Whether the u2net model is installed (gates the editor "Remove BG" button).
///
/// The model is NOT downloaded by the app in M5 — packaging (M6) acquires it.
/// Until a `u2net.onnx` lands at `~/.cache/wondershot/u2net.onnx`, the editor's
/// Remove BG button stays disabled.
#[tauri::command]
pub fn bg_model_available() -> bool {
    bgremove::model_available()
}

/// Run u2net background removal on the image at `path`, returning the result as
/// a base64 PNG (RGBA with the background made transparent). Errors if the model
/// is missing or the ONNX runtime was not compiled in (`bgremove-onnx` feature).
#[tauri::command]
pub fn remove_background(path: String) -> Result<String, String> {
    let img = image::open(&path).map_err(|e| e.to_string())?.to_rgba8();
    let model = bgremove::resolved_model_path()
        .ok_or_else(|| "background-removal model not installed".to_string())?;
    let out = bgremove::remove_background(&img, &model)?;
    encode_png_b64(&out)
}

// --- save / flatten / base persistence (T14) -------------------------------

/// Decode a base64 PNG body, refusing payloads that aren't a real PNG. A
/// tainted/failed canvas export reaches us as zero bytes (`data:,`) — writing
/// that through would truncate the user's original screenshot.
fn decode_png_b64(png_b64: &str) -> Result<Vec<u8>, String> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(png_b64.as_bytes())
        .map_err(|e| e.to_string())?;
    const PNG_MAGIC: [u8; 8] = [0x89, b'P', b'N', b'G', b'\r', b'\n', 0x1a, b'\n'];
    if bytes.len() < PNG_MAGIC.len() || bytes[..PNG_MAGIC.len()] != PNG_MAGIC {
        return Err(format!(
            "refusing to write a non-PNG payload ({} bytes) — canvas export failed?",
            bytes.len()
        ));
    }
    Ok(bytes)
}

/// Write via a temp file + rename so an interrupted save can never leave a
/// truncated image behind.
fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(".tmp-wondershot");
    let tmp = std::path::PathBuf::from(tmp);
    std::fs::write(&tmp, bytes).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        e.to_string()
    })
}

/// Base64-decode `png_b64` and write the raw PNG bytes to the library image at
/// `path` (the flattened, annotations-baked result). Overwrites in place —
/// atomically, and only after the payload validates as a real PNG.
#[tauri::command]
pub fn flatten_save(path: String, png_b64: String) -> Result<(), String> {
    let bytes = decode_png_b64(&png_b64)?;
    write_atomic(Path::new(&path), &bytes)
}

/// Base64-decode `png_b64` and write it as base `n` in the sidecar dir,
/// creating `.wondershot/` if needed. This is the editable base the editor
/// reopens (base + items), distinct from the flattened library image.
#[tauri::command]
pub fn write_base(path: String, n: u32, png_b64: String) -> Result<(), String> {
    let bytes = decode_png_b64(&png_b64)?;
    let p = Path::new(&path);
    let base = sidecar::base_path(p, n);
    if let Some(parent) = base.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    write_atomic(&base, &bytes)
}

/// Read an image file, returning its base64 body (no `data:` prefix). The
/// editor loads its base image through this rather than the asset protocol:
/// WebKit treats `asset.localhost` as cross-origin (no CORS fetch on a plain
/// `Image`), which taints the Konva canvas and silently breaks
/// `stage.toDataURL()` — and with it save/flatten.
#[tauri::command]
pub fn read_image_b64(path: String) -> Result<String, String> {
    use base64::Engine;
    let bytes = std::fs::read(&path).map_err(|e| e.to_string())?;
    Ok(base64::engine::general_purpose::STANDARD.encode(&bytes))
}

/// Read base `n` from the sidecar dir, returning it as base64 PNG body (no
/// `data:` prefix) if it exists, else `None`.
#[tauri::command]
pub fn read_base(path: String, n: u32) -> Result<Option<String>, String> {
    use base64::Engine;
    let base = sidecar::base_path(Path::new(&path), n);
    if !base.exists() {
        return Ok(None);
    }
    let bytes = std::fs::read(&base).map_err(|e| e.to_string())?;
    Ok(Some(base64::engine::general_purpose::STANDARD.encode(&bytes)))
}

// --- screen recording (M4 T6) ----------------------------------------------

/// Managed Tauri state holding the live recorder. `Recorder` is not `Clone`
/// and `stop(self)` consumes it, so we store an `Option` and `.take()` on stop.
pub struct RecState(pub Mutex<Option<recorder::Recorder>>);

impl Default for RecState {
    fn default() -> Self {
        RecState(Mutex::new(None))
    }
}

/// Map a `RecEvent` to a `recording://` webview event.
///
/// Payloads:
///   - `recording://state`  { status: "recording"|"stopping"|"idle", paused: bool }
///   - `recording://tick`   "M:SS" elapsed string
///   - `recording://done`   the finished file path
///   - `recording://failed` the error message
fn emit_rec_event(app: &tauri::AppHandle, ev: recorder::RecEvent) {
    use recorder::RecEvent;
    use tauri::Emitter;
    match ev {
        RecEvent::Started => {
            let _ = app.emit(
                "recording://state",
                serde_json::json!({ "status": "recording", "paused": false }),
            );
        }
        RecEvent::Stopping => {
            let _ = app.emit(
                "recording://state",
                serde_json::json!({ "status": "stopping", "paused": false }),
            );
        }
        RecEvent::PausedChanged(paused) => {
            let _ = app.emit(
                "recording://state",
                serde_json::json!({ "status": "recording", "paused": paused }),
            );
        }
        RecEvent::Tick(elapsed) => {
            let _ = app.emit("recording://tick", elapsed);
        }
        RecEvent::Finished(path) => {
            let _ = app.emit("recording://done", path.to_string_lossy().to_string());
            let _ = app.emit(
                "recording://state",
                serde_json::json!({ "status": "idle", "paused": false }),
            );
        }
        RecEvent::Failed(msg) => {
            let _ = app.emit("recording://failed", msg);
            let _ = app.emit(
                "recording://state",
                serde_json::json!({ "status": "idle", "paused": false }),
            );
        }
    }
}

/// Remove `.rendering` tmp files older than 1h (orphaned by a crash).
/// Ports the effect of record.py's `sweep_stale_tmp`.
fn sweep_stale_tmp(rendering: &Path) {
    let _ = std::fs::create_dir_all(rendering);
    let Ok(entries) = std::fs::read_dir(rendering) else { return };
    for entry in entries.flatten() {
        let Ok(meta) = entry.metadata() else { continue };
        if !meta.is_file() {
            continue;
        }
        let age = meta
            .modified()
            .ok()
            .and_then(|m| m.elapsed().ok())
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        if files::is_stale(age, 3600) {
            let _ = std::fs::remove_file(entry.path());
        }
    }
}

/// Start a screen recording: open the portal, build the gstreamer pipeline,
/// launch the recorder, and store it in managed state. Events flow back to the
/// webview via `recording://` topics.
#[tauri::command]
pub async fn start_recording(
    app: tauri::AppHandle,
    state: tauri::State<'_, RecState>,
) -> Result<(), String> {
    use std::os::fd::AsRawFd;

    let s = Settings::load();
    let library_dir = Path::new(&s.library_dir);

    // Sweep stale tmp renders (>1h old) before starting a fresh one.
    let rendering = files::rendering_dir(library_dir);
    sweep_stale_tmp(&rendering);

    // Portal: pick a screen/window and obtain the PipeWire fd + node id. KEEP
    // `fd` (OwnedFd) alive across launch — pipewiresrc dups it during launch.
    let (fd, node) = portal::open_screencast().await?;

    // Same base name for tmp and out; the out path is uniquified.
    let name = files::recording_name();
    let tmp = rendering.join(&name);
    let out = paths::unique_path(library_dir, &name);

    // NOTE: have_webrtcdsp is hardcoded false for M4 — src-tauri has no
    // gstreamer dependency to probe ElementFactory::find("webrtcdsp").
    // NOTE: mic_device is passed through as the pulse device string. Resolving
    // a human-readable description -> pulse name (Python does this via Qt) is
    // deferred to a pipewire/pulse enumeration follow-up. Empty = default mic.
    let opts = pipeline::PipelineOpts {
        mic_enabled: s.mic_enabled,
        mic_device: s.mic_device.clone(),
        noise_suppression: s.noise_suppression,
        have_webrtcdsp: false,
        crop: None,
        halo: s.record_cursor_halo,
    };

    let tmp_str = tmp
        .to_str()
        .ok_or("tmp path is not valid UTF-8")?
        .to_string();
    let desc = pipeline::build_pipeline_description(fd.as_raw_fd(), node, &tmp_str, &opts);

    let app_for_cb = app.clone();
    let rec = recorder::Recorder::launch(&desc, tmp, out, move |ev| {
        emit_rec_event(&app_for_cb, ev)
    })?;

    // `fd` (OwnedFd) was kept alive through launch; pipewiresrc has dup'd it,
    // so it may drop now.
    drop(fd);

    *state.0.lock().map_err(|e| e.to_string())? = Some(rec);
    Ok(())
}

/// Stop the active recording. `stop()` consumes the recorder and emits
/// `Finished`/`Failed` through the event callback.
#[tauri::command]
pub fn stop_recording(state: tauri::State<'_, RecState>) -> Result<(), String> {
    let rec = state.0.lock().map_err(|e| e.to_string())?.take();
    if let Some(rec) = rec {
        rec.stop();
    }
    Ok(())
}

/// Pause the active recording (drops frames until resumed).
#[tauri::command]
pub fn pause_recording(state: tauri::State<'_, RecState>) -> Result<(), String> {
    if let Some(rec) = state.0.lock().map_err(|e| e.to_string())?.as_ref() {
        rec.pause();
    }
    Ok(())
}

/// Resume a paused recording.
#[tauri::command]
pub fn resume_recording(state: tauri::State<'_, RecState>) -> Result<(), String> {
    if let Some(rec) = state.0.lock().map_err(|e| e.to_string())?.as_ref() {
        rec.resume();
    }
    Ok(())
}

// --- video: ffmpeg-driven operations (M5 T2) -------------------------------

/// Locate the ffmpeg binary. M2/M4 have no bundled-ffmpeg helper, so resolve
/// it on PATH (the flatpak ships ffmpeg in the runtime; dev hosts have it too).
fn find_ffmpeg() -> Result<String, String> {
    std::env::var_os("PATH")
        .and_then(|paths| {
            std::env::split_paths(&paths)
                .map(|p| p.join("ffmpeg"))
                .find(|p| p.is_file())
        })
        .map(|p| p.to_string_lossy().into_owned())
        .or_else(|| {
            // Common absolute fallbacks if PATH is sparse.
            ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/app/bin/ffmpeg"]
                .into_iter()
                .find(|p| Path::new(p).is_file())
                .map(|s| s.to_string())
        })
        .ok_or_else(|| "ffmpeg not found on PATH".to_string())
}

/// The library dir and the `.rendering` tmp dir (created), as paths.
fn library_and_rendering() -> (std::path::PathBuf, std::path::PathBuf) {
    let s = Settings::load();
    let library_dir = std::path::PathBuf::from(&s.library_dir);
    let _ = std::fs::create_dir_all(&library_dir);
    let rendering = files::rendering_dir(&library_dir);
    let _ = std::fs::create_dir_all(&rendering);
    (library_dir, rendering)
}

/// Basename (file_name) of a path as a String.
fn basename(path: &str) -> String {
    Path::new(path)
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string())
}

/// Lowercase extension (no dot) of a path.
fn ext_of(path: &str) -> String {
    Path::new(path)
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default()
}

/// Run ffmpeg with `args`, then atomically move `tmp` → a unique path in the
/// library named `out_name`. Returns the final path. On failure the tmp is
/// removed and ffmpeg's stderr tail is surfaced.
async fn run_ffmpeg_to_library(
    args: &[String],
    tmp: &Path,
    library_dir: &Path,
    out_name: &str,
) -> Result<String, String> {
    let ffmpeg = find_ffmpeg()?;
    let output = tokio::process::Command::new(&ffmpeg)
        .args(args)
        .output()
        .await
        .map_err(|e| format!("could not start ffmpeg: {e}"))?;
    if !output.status.success() {
        let _ = std::fs::remove_file(tmp);
        let stderr = String::from_utf8_lossy(&output.stderr);
        let tail: String = stderr.lines().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
        return Err(format!("ffmpeg failed: {tail}"));
    }
    if !tmp.exists() {
        return Err("ffmpeg produced no output file".into());
    }
    let out = paths::unique_path(library_dir, out_name);
    std::fs::rename(tmp, &out)
        .or_else(|_| std::fs::copy(tmp, &out).map(|_| ()).and_then(|_| std::fs::remove_file(tmp)))
        .map_err(|e| format!("could not move render into library: {e}"))?;
    Ok(out.to_string_lossy().into_owned())
}

/// Grab a single frame at `position` seconds, saved as `<stem>-frame.png` in
/// the library. Returns the new file's path.
#[tauri::command]
pub async fn grab_frame(path: String, position: f64) -> Result<String, String> {
    let (library_dir, rendering) = library_and_rendering();
    let out_name = video::frame_name(&basename(&path));
    let tmp = rendering.join(&out_name);
    let args = video::build_frame_grab_args(&path, position, &tmp.to_string_lossy());
    run_ffmpeg_to_library(&args, &tmp, &library_dir, &out_name).await
}

/// Apply time-gated blur redactions and re-encode to H.264.
///
/// CONTAINER COERCION: H.264 cannot live in a webm, so the output extension is
/// the source ext only when it is already an mp4/m4v/mov container; otherwise
/// it is forced to `.mp4`. Output name is `<stem>-redacted.<coerced-ext>`.
#[tauri::command]
pub async fn apply_blur(
    path: String,
    redactions: Vec<video::Redaction>,
    blur: u32,
) -> Result<String, String> {
    if redactions.is_empty() {
        return Err("no redactions to apply".into());
    }
    let (library_dir, rendering) = library_and_rendering();

    let src_ext = ext_of(&path);
    let coerced_ext = if matches!(src_ext.as_str(), "mp4" | "m4v" | "mov") {
        src_ext
    } else {
        "mp4".to_string()
    };
    let stem = Path::new(&path)
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "video".into());
    let out_name = format!("{stem}-redacted.{coerced_ext}");
    let tmp = rendering.join(&out_name);

    // video_w/video_h = 0 ⇒ the filter does not clamp (the UI already mapped
    // boxes into valid frame coords).
    let (graph, label) = video::build_blur_filter(&redactions, blur as i64, 0, 0);

    let args: Vec<String> = vec![
        "-y".into(),
        "-i".into(),
        path.clone(),
        "-filter_complex".into(),
        graph,
        "-map".into(),
        format!("[{label}]"),
        "-map".into(),
        "0:a?".into(),
        "-c:v".into(),
        "libx264".into(),
        "-crf".into(),
        "20".into(),
        "-preset".into(),
        "veryfast".into(),
        "-movflags".into(),
        "+faststart".into(),
        tmp.to_string_lossy().into_owned(),
    ];
    run_ffmpeg_to_library(&args, &tmp, &library_dir, &out_name).await
}

/// Export the video (optionally a sub-range) to a palette-optimized GIF named
/// `<stem>.gif`. Returns the new file's path.
#[tauri::command]
pub async fn export_gif(
    path: String,
    fps: u32,
    max_width: u32,
    start: Option<f64>,
    end: Option<f64>,
) -> Result<String, String> {
    let (library_dir, rendering) = library_and_rendering();
    let out_name = video::gif_name(&basename(&path));
    let tmp = rendering.join(&out_name);
    let args = video::build_gif_args(
        &path,
        &tmp.to_string_lossy(),
        fps as i64,
        max_width as i64,
        start,
        end,
    );
    run_ffmpeg_to_library(&args, &tmp, &library_dir, &out_name).await
}

/// Trim the video to `[start, end]`. Stream-copy keeps the source container;
/// re-encode lands in `.mp4` (always x264). Returns the new file's path.
#[tauri::command]
pub async fn trim_video(
    path: String,
    start: f64,
    end: f64,
    reencode: bool,
) -> Result<String, String> {
    let (library_dir, rendering) = library_and_rendering();
    let out_name = video::trimmed_name(&basename(&path), reencode);
    let tmp = rendering.join(&out_name);
    let args = video::build_trim_args(
        &path,
        start,
        end,
        &tmp.to_string_lossy(),
        reencode,
        "libx264",
    );
    run_ffmpeg_to_library(&args, &tmp, &library_dir, &out_name).await
}

/// Write `img` as the next base file alongside `path` and return its path.
fn write_new_base(path: &str, img: &image::RgbaImage) -> Result<String, String> {
    let p = Path::new(path);
    let next_n = sidecar::load(p).map(|d| d.bases).unwrap_or(0);
    let base = sidecar::base_path(p, next_n);
    if let Some(parent) = base.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    img.save_with_format(&base, image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(base.to_string_lossy().into_owned())
}

// --- M7 cutover: CLI-driven commands ---------------------------------------

/// Install the per-user `.desktop` launcher + point its Icon at the app-id
/// (parity with Python `--install-desktop`). Idempotent; best-effort xdg
/// database refresh. The AppImage path uses this to register a menu entry.
#[tauri::command]
pub fn install_desktop() -> Result<(), String> {
    use std::io::Write;
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let data = std::env::var_os("XDG_DATA_HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
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
    let _ = std::process::Command::new("update-desktop-database")
        .arg(&apps)
        .status();
    Ok(())
}

/// Copy `paths` into the library dir (parity with Python `--import`), returning
/// the destination paths. Files already inside the library are left in place.
#[tauri::command]
pub fn import_files(paths: Vec<String>) -> Result<Vec<String>, String> {
    let lib = Settings::load().library_dir;
    std::fs::create_dir_all(&lib).map_err(|e| e.to_string())?;
    let lib_dir = Path::new(&lib);
    let mut out = Vec::new();
    for p in paths {
        let src = std::path::PathBuf::from(&p);
        let name = src
            .file_name()
            .ok_or_else(|| format!("bad import path: {p}"))?;
        let dest = lib_dir.join(name);
        if src != dest {
            std::fs::copy(&src, &dest).map_err(|e| e.to_string())?;
        }
        out.push(dest.to_string_lossy().into_owned());
    }
    Ok(out)
}

/// Show/hide the frameless camera-bubble window (header "Camera" toggle). The
/// window is declared in tauri.conf (label "bubble", visible:false at startup).
#[tauri::command]
pub fn toggle_camera_bubble(app: tauri::AppHandle) -> Result<bool, String> {
    use tauri::Manager;
    let Some(w) = app.get_webview_window("bubble") else {
        return Err("camera bubble window not found".into());
    };
    let visible = w.is_visible().unwrap_or(false);
    if visible {
        w.hide().map_err(|e| e.to_string())?;
        Ok(false)
    } else {
        w.show().map_err(|e| e.to_string())?;
        let _ = w.set_focus();
        Ok(true)
    }
}

// --- pins (filmstrip pin affordance) ---------------------------------------

/// Where the pinned-paths list lives (next to wondershot.conf).
fn pins_path() -> std::path::PathBuf {
    Settings::conf_path()
        .parent()
        .map(|p| p.join("pins.json"))
        .unwrap_or_else(|| std::path::PathBuf::from("pins.json"))
}

/// The list of pinned capture paths (most-recently-pinned last).
#[tauri::command]
pub fn list_pinned() -> Vec<String> {
    std::fs::read_to_string(pins_path())
        .ok()
        .and_then(|s| serde_json::from_str::<Vec<String>>(&s).ok())
        .unwrap_or_default()
}

/// Pin or unpin a capture by path; returns the updated pinned list.
#[tauri::command]
pub fn set_pinned(path: String, pinned: bool) -> Result<Vec<String>, String> {
    let mut list = list_pinned();
    list.retain(|p| p != &path);
    if pinned {
        list.push(path);
    }
    let p = pins_path();
    if let Some(parent) = p.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string(&list).map_err(|e| e.to_string())?;
    std::fs::write(&p, json).map_err(|e| e.to_string())?;
    Ok(list)
}

// --- right-click actions: Save as / Show in folder -------------------------

/// "Save as…": open the desktop file-chooser (portal) and copy the capture to
/// the chosen path. Returns the destination, or `None` if the user cancelled.
#[tauri::command]
pub async fn save_image_as(path: String) -> Result<Option<String>, String> {
    let src = std::path::PathBuf::from(&path);
    let name = src
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "screenshot.png".into());
    let chosen = rfd::AsyncFileDialog::new()
        .set_file_name(&name)
        .save_file()
        .await;
    let Some(dest) = chosen else { return Ok(None) };
    let dest = dest.path().to_path_buf();
    std::fs::copy(&src, &dest).map_err(|e| e.to_string())?;
    Ok(Some(dest.to_string_lossy().into_owned()))
}

/// Folder picker via the portal file chooser (Settings → Browse…/Add…).
/// Returns the chosen directory, or None if cancelled.
#[tauri::command]
pub async fn pick_folder() -> Result<Option<String>, String> {
    let chosen = rfd::AsyncFileDialog::new().pick_folder().await;
    Ok(chosen.map(|d| d.path().to_string_lossy().into_owned()))
}

/// Open the desktop's global-shortcut settings (Qt parity: the Settings
/// "Open KDE Shortcuts settings" button). KDE-only, like the Python app;
/// errors if neither systemsettings nor kcmshell6 is on PATH.
#[tauri::command]
pub fn open_shortcut_settings() -> Result<(), String> {
    let candidates: [(&str, &[&str]); 2] =
        [("systemsettings", &["kcm_keys"]), ("kcmshell6", &["kcm_keys"])];
    for (bin, args) in candidates {
        let mut cmd = if in_flatpak() {
            // The sandbox has no systemsettings; run the host's.
            let mut c = std::process::Command::new("flatpak-spawn");
            c.arg("--host").arg(bin).args(args);
            c
        } else {
            let mut c = std::process::Command::new(bin);
            c.args(args);
            c
        };
        if cmd.spawn().is_ok() {
            return Ok(());
        }
    }
    Err("no systemsettings/kcmshell6 found — open your desktop's shortcut settings manually".into())
}

/// Open the capture's containing folder in the file manager (host file manager
/// when sandboxed, via flatpak-spawn).
#[tauri::command]
pub fn show_in_folder(path: String) -> Result<(), String> {
    let p = Path::new(&path);
    let dir = p.parent().unwrap_or(p);
    open_target(&dir.to_string_lossy())
}

/// Open a URL (e.g. the OneDrive device-code sign-in page) in the default browser.
#[tauri::command]
pub fn open_url(url: String) -> Result<(), String> {
    open_target(&url)
}

/// xdg-open a path/URL, routing through the host opener when sandboxed.
fn open_target(target: &str) -> Result<(), String> {
    let res = if in_flatpak() {
        std::process::Command::new("flatpak-spawn")
            .args(["--host", "xdg-open", target])
            .spawn()
    } else {
        std::process::Command::new("xdg-open").arg(target).spawn()
    };
    res.map(|_| ()).map_err(|e| e.to_string())
}

// --- OneDrive / SharePoint (Microsoft Graph, device-code OAuth) -------------

/// Connected account label ('' when not signed in). Drives the Sharing → OneDrive
/// "Status:" row.
#[tauri::command]
pub fn graph_status() -> serde_json::Value {
    serde_json::json!({
        "account": graph::connected_account(),
        "default_client_id": graph::DEFAULT_CLIENT_ID,
    })
}

/// Begin device-code sign-in: returns the user_code + verification_uri to show,
/// and the device_code + interval the frontend polls with.
#[tauri::command]
pub fn graph_connect_start(client_id: String) -> Result<serde_json::Value, String> {
    let cid = if client_id.trim().is_empty() {
        graph::DEFAULT_CLIENT_ID.to_string()
    } else {
        client_id.trim().to_string()
    };
    let dc = graph::request_device_code(&cid)?;
    Ok(serde_json::json!({
        "client_id": cid,
        "device_code": dc.get("device_code"),
        "user_code": dc.get("user_code"),
        "verification_uri": dc.get("verification_uri"),
        "interval": dc.get("interval"),
        "expires_in": dc.get("expires_in"),
    }))
}

/// One poll of the device-code flow. `status` is `pending` | `connected`;
/// errors propagate as a command error.
#[tauri::command]
pub fn graph_connect_poll(client_id: String, device_code: String) -> Result<serde_json::Value, String> {
    match graph::poll_token(&client_id, &device_code)? {
        None => Ok(serde_json::json!({ "status": "pending" })),
        Some(tokens) => {
            let token = tokens
                .get("access_token")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let account = graph::whoami(&token).unwrap_or_else(|_| "connected".into());
            graph::save_tokens(&tokens, &client_id, &account)?;
            Ok(serde_json::json!({ "status": "connected", "account": account }))
        }
    }
}

#[tauri::command]
pub fn graph_disconnect() -> Result<(), String> {
    graph::disconnect();
    Ok(())
}

#[tauri::command]
pub fn graph_sites_search(query: String) -> Result<Vec<serde_json::Value>, String> {
    let token = graph::ensure_access_token()?;
    graph::sites_search(&token, &query)
}

#[tauri::command]
pub fn graph_site_drives(site_id: String) -> Result<Vec<serde_json::Value>, String> {
    let token = graph::ensure_access_token()?;
    graph::site_drives(&token, &site_id)
}

// --- AI endpoint connectivity test (Settings → AI → Test) ------------------

/// Probe the OpenAI-compatible AI endpoint for reachability/auth by GETting its
/// `/v1/models` (or `/models`) listing. Returns a short status string on success.
#[tauri::command]
pub fn test_ai_endpoint(endpoint: String, model: String, api_key: String) -> Result<String, String> {
    let base = endpoint.trim().trim_end_matches('/');
    if base.is_empty() {
        return Err("No endpoint set".into());
    }
    let url = if base.ends_with("/v1") {
        format!("{base}/models")
    } else {
        format!("{base}/v1/models")
    };
    let mut req = ureq::get(&url).timeout(std::time::Duration::from_secs(15));
    if !api_key.trim().is_empty() {
        req = req.set("Authorization", &format!("Bearer {}", api_key.trim()));
    }
    match req.call() {
        Ok(resp) => {
            let m = model.trim();
            let suffix = if m.is_empty() { String::new() } else { format!(" · model “{m}” will be used") };
            Ok(format!("Connected (HTTP {}){suffix}", resp.status()))
        }
        Err(ureq::Error::Status(code, _)) => {
            Err(format!("Endpoint reachable but returned HTTP {code} (check API key/model)"))
        }
        Err(e) => Err(format!("Could not reach endpoint: {e}")),
    }
}

/// Show + focus the framed capture window (header "Capture"). Mirrors
/// `toggle_camera_bubble`'s proven show path rather than a JS getByLabel lookup.
#[tauri::command]
pub fn show_capture_window(app: tauri::AppHandle) -> Result<(), String> {
    use tauri::Manager;
    if let Some(w) = app.get_webview_window("capture") {
        w.show().map_err(|e| e.to_string())?;
        let _ = w.unminimize();
        let _ = w.set_focus();
        return Ok(());
    }
    // The window was natively closed (X destroys it) — recreate it so the
    // header "Capture" button always reopens a fresh, movable window.
    tauri::WebviewWindowBuilder::new(&app, "capture", tauri::WebviewUrl::App("/capture".into()))
        .title("Capture")
        .inner_size(380.0, 224.0)
        .resizable(false)
        .decorations(false)
        .center()
        .build()
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Move a library item to the desktop trash (filmstrip hover-delete). Best-effort
/// also trashes the item's `.<stem>` sidecar dir (annotations/base stack).
#[tauri::command]
pub fn trash_item(path: String) -> Result<(), String> {
    let p = Path::new(&path);
    if let (Some(dir), Some(stem)) = (p.parent(), p.file_stem()) {
        let sidecar = dir.join(format!(".{}", stem.to_string_lossy()));
        if sidecar.is_dir() {
            let _ = trash::delete(&sidecar);
        }
    }
    trash::delete(p).map_err(|e| format!("could not trash {}: {e}", path))
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;

    /// 1x1 transparent PNG.
    fn png_b64() -> String {
        base64::engine::general_purpose::STANDARD.encode([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48,
            0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00,
            0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41, 0x54, 0x78,
            0x9C, 0x63, 0x00, 0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00,
            0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
        ])
    }

    #[test]
    fn flatten_save_rejects_empty_payload() {
        // A tainted canvas exports `data:,` → empty base64. The original file
        // must survive untouched.
        let dir = std::env::temp_dir().join("ws-flatten-guard");
        std::fs::create_dir_all(&dir).unwrap();
        let target = dir.join("orig.png");
        std::fs::write(&target, b"ORIGINAL").unwrap();
        let err = flatten_save(target.to_string_lossy().into(), String::new());
        assert!(err.is_err(), "empty payload must be rejected");
        assert_eq!(std::fs::read(&target).unwrap(), b"ORIGINAL");
    }

    #[test]
    fn flatten_save_rejects_non_png() {
        let dir = std::env::temp_dir().join("ws-flatten-guard2");
        std::fs::create_dir_all(&dir).unwrap();
        let target = dir.join("orig.png");
        std::fs::write(&target, b"ORIGINAL").unwrap();
        let not_png = base64::engine::general_purpose::STANDARD.encode(b"hello");
        let err = flatten_save(target.to_string_lossy().into(), not_png);
        assert!(err.is_err(), "non-PNG payload must be rejected");
        assert_eq!(std::fs::read(&target).unwrap(), b"ORIGINAL");
    }

    #[test]
    fn flatten_save_writes_valid_png_atomically() {
        let dir = std::env::temp_dir().join("ws-flatten-ok");
        std::fs::create_dir_all(&dir).unwrap();
        let target = dir.join("orig.png");
        std::fs::write(&target, b"ORIGINAL").unwrap();
        flatten_save(target.to_string_lossy().into(), png_b64()).unwrap();
        let written = std::fs::read(&target).unwrap();
        assert_eq!(&written[..4], &[0x89, 0x50, 0x4E, 0x47]);
        // No stray temp file left behind.
        assert!(!dir.join("orig.png.tmp-wondershot").exists());
    }

    #[test]
    fn read_image_b64_round_trips() {
        let dir = std::env::temp_dir().join("ws-read-b64");
        std::fs::create_dir_all(&dir).unwrap();
        let target = dir.join("img.png");
        let body = png_b64();
        std::fs::write(
            &target,
            base64::engine::general_purpose::STANDARD.decode(&body).unwrap(),
        )
        .unwrap();
        assert_eq!(read_image_b64(target.to_string_lossy().into()).unwrap(), body);
    }
}
