use std::path::Path;
use std::sync::Mutex;
use wondershot_core::{capture, clipboard, library, paths, settings::Settings, sidecar};
use wondershot_core::record::{files, pipeline, portal, recorder};

#[tauri::command]
pub fn health() -> String {
    "ok".into()
}

#[tauri::command]
pub fn get_settings() -> serde_json::Value {
    let s = Settings::load();
    serde_json::json!({
        "library_dir": s.library_dir,
        "backend": s.backend,
        "capture_cursor": s.capture_cursor,
        "capture_delay": s.capture_delay,
        "extra_dirs": s.extra_dirs,
    })
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

fn spectacle_on_path() -> bool {
    std::env::var_os("PATH").map_or(false, |paths| {
        std::env::split_paths(&paths).any(|p| p.join("spectacle").is_file())
    })
}

async fn run_spectacle(mode: capture::CaptureMode, out: &str, cursor: bool, delay: u32) -> Result<(), String> {
    let args = capture::spectacle::spectacle_args(mode, out, cursor, delay);
    let status = tokio::process::Command::new("spectacle")
        .args(&args)
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

/// Pixelate the rect region of the base PNG; returns the patch as base64 PNG.
#[tauri::command]
pub fn pixelate_patch(path: String, rect: (u32, u32, u32, u32), block: u32) -> Result<String, String> {
    let img = image::open(&path).map_err(|e| e.to_string())?.to_rgba8();
    let patch = wondershot_core::imageops::pixelated_patch(&img, rect, block);
    encode_png_b64(&patch)
}

/// Gaussian-blur the rect region of the base PNG; returns the patch as base64 PNG.
#[tauri::command]
pub fn blur_patch(path: String, rect: (u32, u32, u32, u32), radius: u32) -> Result<String, String> {
    let img = image::open(&path).map_err(|e| e.to_string())?.to_rgba8();
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

// --- save / flatten / base persistence (T14) -------------------------------

/// Base64-decode `png_b64` and write the raw PNG bytes to the library image at
/// `path` (the flattened, annotations-baked result). Overwrites in place.
#[tauri::command]
pub fn flatten_save(path: String, png_b64: String) -> Result<(), String> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(png_b64.as_bytes())
        .map_err(|e| e.to_string())?;
    std::fs::write(&path, bytes).map_err(|e| e.to_string())
}

/// Base64-decode `png_b64` and write it as base `n` in the sidecar dir,
/// creating `.wondershot/` if needed. This is the editable base the editor
/// reopens (base + items), distinct from the flattened library image.
#[tauri::command]
pub fn write_base(path: String, n: u32, png_b64: String) -> Result<(), String> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(png_b64.as_bytes())
        .map_err(|e| e.to_string())?;
    let p = Path::new(&path);
    let base = sidecar::base_path(p, n);
    if let Some(parent) = base.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(&base, bytes).map_err(|e| e.to_string())
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
