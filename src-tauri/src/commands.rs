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
