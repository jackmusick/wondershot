use std::path::Path;
use wondershot_core::{capture, clipboard, library, paths, settings::Settings, sidecar};

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
