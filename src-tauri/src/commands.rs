use crate::{graph, logging};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Instant;
use wondershot_core::record::{files, recorder};
#[cfg(target_os = "linux")]
use wondershot_core::record::{pipeline, portal};
use wondershot_core::{
    bgremove, capture, clipboard, library, paths, settings::Settings, sidecar, video,
};

static CAPTURE_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[tauri::command]
pub fn health() -> String {
    "ok".into()
}

#[tauri::command]
pub fn debug_log(message: String) {
    logging::log(format!("frontend: {message}"));
}

#[tauri::command]
pub fn log_path() -> String {
    logging::log_path().display().to_string()
}

#[tauri::command]
pub fn platform() -> &'static str {
    std::env::consts::OS
}

fn restore_main_window(app: &tauri::AppHandle) {
    use std::time::Duration;
    use tauri::{Manager, UserAttentionType};

    fn focus_main_window(w: &tauri::WebviewWindow, attempt: &str) {
        if let Err(e) = w.unminimize() {
            logging::log(format!(
                "restore main after capture ({attempt}): unminimize failed: {e}"
            ));
        }
        if let Err(e) = w.show() {
            logging::log(format!(
                "restore main after capture ({attempt}): show failed: {e}"
            ));
        }
        if let Err(e) = w.request_user_attention(Some(UserAttentionType::Informational)) {
            logging::log(format!(
                "restore main after capture ({attempt}): request attention failed: {e}"
            ));
        }
        if let Err(e) = w.set_focus() {
            logging::log(format!(
                "restore main after capture ({attempt}): focus failed: {e}"
            ));
        }
    }

    if let Some(w) = app.get_webview_window("main") {
        focus_main_window(&w, "initial");
        tauri::async_runtime::spawn(async move {
            for attempt in ["retry 1", "retry 2"] {
                tokio::time::sleep(Duration::from_millis(175)).await;
                focus_main_window(&w, attempt);
            }
        });
    } else {
        logging::log("restore main after capture: main window not found");
    }
}

fn restore_main_after_capture(app: &tauri::AppHandle, settings: &Settings) {
    if settings.show_gallery_after_capture {
        restore_main_window(app);
    }
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
    let before = s.clone();
    let old_dirs = s.library_dirs();
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
            "library_dir" => {
                if let Some(x) = get_str(v) {
                    s.library_dir = x
                }
            }
            "backend" => {
                if let Some(x) = get_str(v) {
                    s.backend = x
                }
            }
            "capture_cursor" => {
                if let Some(x) = get_bool(v) {
                    s.capture_cursor = x
                }
            }
            "capture_delay" => {
                if let Some(x) = get_u32(v) {
                    s.capture_delay = x
                }
            }
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
            "mic_enabled" => {
                if let Some(x) = get_bool(v) {
                    s.mic_enabled = x
                }
            }
            "mic_device" => {
                if let Some(x) = get_str(v) {
                    s.mic_device = x
                }
            }
            "noise_suppression" => {
                if let Some(x) = get_bool(v) {
                    s.noise_suppression = x
                }
            }
            "record_cursor_halo" => {
                if let Some(x) = get_bool(v) {
                    s.record_cursor_halo = x
                }
            }
            "record_countdown" => {
                if let Some(x) = get_u32(v) {
                    s.record_countdown = x
                }
            }
            "camera_device" => {
                if let Some(x) = get_str(v) {
                    s.camera_device = x
                }
            }
            "hotkey_capture" => {
                if let Some(x) = get_str(v) {
                    s.hotkey_capture = x
                }
            }
            "copy_after_capture" => {
                if let Some(x) = get_bool(v) {
                    s.copy_after_capture = x
                }
            }
            "show_gallery_after_capture" => {
                if let Some(x) = get_bool(v) {
                    s.show_gallery_after_capture = x
                }
            }
            "pin_on_top" => {
                if let Some(x) = get_bool(v) {
                    s.pin_on_top = x
                }
            }
            "quick_bar_enabled" => {
                if let Some(x) = get_bool(v) {
                    s.quick_bar_enabled = x
                }
            }
            "quick_bar_timeout" => {
                if let Some(x) = get_u32(v) {
                    s.quick_bar_timeout = x
                }
            }
            "stroke_width" => {
                if let Some(x) = get_u32(v) {
                    s.stroke_width = x
                }
            }
            "font_size" => {
                if let Some(x) = get_u32(v) {
                    s.font_size = x
                }
            }
            "tool_color" => {
                if let Some(x) = get_str(v) {
                    s.tool_color = x
                }
            }
            "video_blur_strength" => {
                if let Some(x) = get_u32(v) {
                    s.video_blur_strength = x
                }
            }
            "gif_fps" => {
                if let Some(x) = get_u32(v) {
                    s.gif_fps = x
                }
            }
            "gif_max_width" => {
                if let Some(x) = get_u32(v) {
                    s.gif_max_width = x
                }
            }
            "effect_rounded" => {
                if let Some(x) = get_bool(v) {
                    s.effect_rounded = x
                }
            }
            "effect_corner_radius" => {
                if let Some(x) = get_u32(v) {
                    s.effect_corner_radius = x
                }
            }
            "effect_fade" => {
                if let Some(x) = get_bool(v) {
                    s.effect_fade = x
                }
            }
            "effect_fade_height" => {
                if let Some(x) = get_u32(v) {
                    s.effect_fade_height = x
                }
            }
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
    if s == before {
        return Ok(());
    }
    let dirs_changed = s.library_dirs() != old_dirs;
    s.save().map_err(|e| e.to_string())?;
    crate::hotkeys::update_from_settings(&app);
    if dirs_changed {
        crate::watcher::rewatch(&app, watch.inner());
    }
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

pub(crate) fn in_flatpak() -> bool {
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

async fn run_spectacle(
    mode: capture::CaptureMode,
    out: &str,
    cursor: bool,
    delay: u32,
) -> Result<(), String> {
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

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CaptureOutcome {
    capture: library::Capture,
    operation_id: String,
    backend: &'static str,
    capture_elapsed_ms: u64,
    copy_after_capture: bool,
    show_preview: bool,
}

async fn do_capture(
    mode: capture::CaptureMode,
    app: &tauri::AppHandle,
    watch: &crate::watcher::LibWatch,
) -> Result<CaptureOutcome, String> {
    use tauri::Manager;

    let started = Instant::now();
    let s = Settings::load();
    let main_was_visible = app
        .get_webview_window("main")
        .and_then(|window| window.is_visible().ok().map(|visible| (window, visible)));
    if let Some((window, true)) = &main_was_visible {
        window.hide().map_err(|e| format!("could not hide Wondershot before capture: {e}"))?;
        tokio::task::yield_now().await;
    }
    let _ = std::fs::create_dir_all(&s.library_dir);
    let out = paths::unique_path(
        Path::new(&s.library_dir),
        &paths::timestamp_name("Screenshot"),
    );
    let out_str = out.to_string_lossy().to_string();
    let operation_id = format!(
        "capture-{}-{}",
        std::process::id(),
        CAPTURE_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    );

    let (result, backend) = platform_capture(
        mode,
        app,
        &out,
        &out_str,
        s.capture_cursor,
        s.capture_delay,
        &s.backend,
        &s.library_dir,
        &operation_id,
    )
    .await;
    let path = match result {
        Ok(path) => path,
        Err(error) => {
            if main_was_visible.as_ref().is_some_and(|(_, visible)| *visible) {
                restore_main_window(app);
            }
            return Err(error);
        }
    };
    let capture = library::from_path(Path::new(&path))
        .ok_or_else(|| "capture completed but output metadata could not be read".to_string())?;
    crate::watcher::acknowledge(watch, Path::new(&path));
    let outcome = CaptureOutcome {
        capture,
        operation_id,
        backend,
        capture_elapsed_ms: started.elapsed().as_millis() as u64,
        copy_after_capture: s.copy_after_capture,
        show_preview: s.show_gallery_after_capture,
    };
    restore_main_after_capture(app, &s);
    Ok(outcome)
}

fn selection_dir(library_dir: &str, operation_id: &str) -> PathBuf {
    Path::new(library_dir)
        .join(".wondershot")
        .join("selection")
        .join(operation_id)
}

fn selector_session(
    operation_id: &str,
    mode: capture::CaptureMode,
    displays: &[capture::FrozenDisplay],
) -> wondershot_selector::SelectionSession {
    let mode = match mode {
        capture::CaptureMode::Region => wondershot_selector::SelectionMode::Region,
        capture::CaptureMode::Window => wondershot_selector::SelectionMode::Window,
        capture::CaptureMode::Fullscreen => unreachable!("fullscreen does not use the selector"),
    };
    wondershot_selector::SelectionSession {
        operation_id: operation_id.to_string(),
        mode,
        displays: displays
            .iter()
            .map(|display| wondershot_selector::FrozenDisplay {
                id: display.id.clone(),
                frame_path: display.frame_path.to_string_lossy().into_owned(),
                x: display.x,
                y: display.y,
                pixel_width: display.pixel_width,
                pixel_height: display.pixel_height,
                windows: display
                    .windows
                    .iter()
                    .map(|window| wondershot_selector::WindowTarget {
                        id: window.id.clone(),
                        title: window.title.clone(),
                        application: window.application.clone(),
                        x: window.x,
                        y: window.y,
                        width: window.width,
                        height: window.height,
                        z_order: window.z_order,
                        capturable: window.capturable,
                    })
                    .collect(),
            })
            .collect(),
    }
}

async fn run_selector(
    session_dir: &Path,
    session: &wondershot_selector::SelectionSession,
) -> Result<wondershot_selector::SelectionResult, String> {
    std::fs::create_dir_all(session_dir).map_err(|e| e.to_string())?;
    let session_path = session_dir.join("session.json");
    let bytes = serde_json::to_vec(session).map_err(|e| e.to_string())?;
    std::fs::write(&session_path, bytes).map_err(|e| e.to_string())?;
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let output = tokio::process::Command::new(executable)
        .arg("--selector-session")
        .arg(&session_path)
        .output()
        .await
        .map_err(|e| format!("could not start Wondershot selector: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "Wondershot selector failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let stdout = String::from_utf8(output.stdout)
        .map_err(|_| "Wondershot selector returned invalid UTF-8".to_string())?;
    serde_json::from_str(stdout.trim())
        .map_err(|e| format!("Wondershot selector returned invalid output: {e}"))
}

fn crop_frozen_region(
    displays: &[capture::FrozenDisplay],
    display_id: &str,
    rect: (u32, u32, u32, u32),
    out: &Path,
) -> Result<(), String> {
    let display = displays
        .iter()
        .find(|display| display.id == display_id)
        .ok_or_else(|| "selected display is no longer available".to_string())?;
    let image = image::open(&display.frame_path).map_err(|e| e.to_string())?;
    let (x, y, width, height) = rect;
    if width < 2
        || height < 2
        || x.checked_add(width)
            .is_none_or(|right| right > image.width())
        || y.checked_add(height)
            .is_none_or(|bottom| bottom > image.height())
    {
        return Err("selected region falls outside its frozen display".into());
    }
    image
        .crop_imm(x, y, width, height)
        .save(out)
        .map_err(|e| e.to_string())
}

#[cfg(target_os = "linux")]
fn freeze_portal_displays(
    app: &tauri::AppHandle,
    portal_frame: &Path,
    session_dir: &Path,
) -> Result<Vec<capture::FrozenDisplay>, String> {
    let image = image::open(portal_frame).map_err(|e| e.to_string())?;
    let monitors = app.available_monitors().map_err(|e| e.to_string())?;
    if monitors.is_empty() {
        return Err("the compositor reported no displays".into());
    }
    let min_x = monitors
        .iter()
        .map(|monitor| monitor.position().x)
        .min()
        .unwrap_or(0);
    let min_y = monitors
        .iter()
        .map(|monitor| monitor.position().y)
        .min()
        .unwrap_or(0);
    let max_x = monitors
        .iter()
        .map(|monitor| monitor.position().x as i64 + monitor.size().width as i64)
        .max()
        .unwrap_or(i64::from(image.width()));
    let max_y = monitors
        .iter()
        .map(|monitor| monitor.position().y as i64 + monitor.size().height as i64)
        .max()
        .unwrap_or(i64::from(image.height()));
    let desktop_width = (max_x - i64::from(min_x)).max(1) as f64;
    let desktop_height = (max_y - i64::from(min_y)).max(1) as f64;
    let scale_x = f64::from(image.width()) / desktop_width;
    let scale_y = f64::from(image.height()) / desktop_height;

    monitors
        .iter()
        .enumerate()
        .map(|(index, monitor)| {
            let x = (f64::from(monitor.position().x - min_x) * scale_x).round() as u32;
            let y = (f64::from(monitor.position().y - min_y) * scale_y).round() as u32;
            let width = (f64::from(monitor.size().width) * scale_x).round() as u32;
            let height = (f64::from(monitor.size().height) * scale_y).round() as u32;
            let width = width.min(image.width().saturating_sub(x));
            let height = height.min(image.height().saturating_sub(y));
            if width == 0 || height == 0 {
                return Err("portal screenshot does not match compositor display geometry".into());
            }
            let frame_path = session_dir.join(format!("portal-display-{index}.png"));
            image
                .crop_imm(x, y, width, height)
                .save(&frame_path)
                .map_err(|e| e.to_string())?;
            Ok(capture::FrozenDisplay {
                id: format!("portal-display-{index}"),
                frame_path,
                x: monitor.position().x,
                y: monitor.position().y,
                pixel_width: width,
                pixel_height: height,
                windows: Vec::new(),
            })
        })
        .collect()
}

#[cfg(target_os = "windows")]
async fn platform_capture(
    mode: capture::CaptureMode,
    _app: &tauri::AppHandle,
    out: &Path,
    _out_str: &str,
    cursor: bool,
    delay: u32,
    _backend: &str,
    library_dir: &str,
    operation_id: &str,
) -> (Result<String, String>, &'static str) {
    if delay > 0 {
        tokio::time::sleep(std::time::Duration::from_secs(delay as u64)).await;
    }
    let out = out.to_path_buf();
    let result = if mode == capture::CaptureMode::Fullscreen {
        let capture_out = out.clone();
        tokio::task::spawn_blocking(move || {
            capture::windows::capture_once(mode, &capture_out, cursor)
                .map(|_| capture_out.to_string_lossy().into_owned())
        })
        .await
        .map_err(|err| format!("Windows capture task failed: {err}"))
        .and_then(|result| result)
    } else {
        let session_dir = selection_dir(library_dir, operation_id);
        let freeze_dir = session_dir.clone();
        let frozen = tokio::task::spawn_blocking(move || {
            capture::windows::freeze_displays(&freeze_dir, false)
        })
        .await
        .map_err(|err| format!("Windows freeze task failed: {err}"))
        .and_then(|result| result);
        let selected = match frozen {
            Ok(displays) => {
                let session = selector_session(operation_id, mode, &displays);
                match run_selector(&session_dir, &session).await {
                    Ok(wondershot_selector::SelectionResult::Region {
                        display_id,
                        x,
                        y,
                        width,
                        height,
                    }) => crop_frozen_region(&displays, &display_id, (x, y, width, height), &out)
                        .map(|_| out.to_string_lossy().into_owned()),
                    Ok(wondershot_selector::SelectionResult::Window { window_id }) => {
                        let capture_out = out.clone();
                        tokio::task::spawn_blocking(move || {
                            capture::windows::capture_window_by_id(&window_id, &capture_out, cursor)
                                .map(|_| capture_out.to_string_lossy().into_owned())
                        })
                        .await
                        .map_err(|err| format!("Windows window capture task failed: {err}"))
                        .and_then(|result| result)
                    }
                    Ok(wondershot_selector::SelectionResult::Cancelled) => {
                        Err("capture cancelled".into())
                    }
                    Err(error) => Err(error),
                }
            }
            Err(error) => Err(error),
        };
        let _ = std::fs::remove_dir_all(&session_dir);
        selected
    };
    (result, "windows-graphics-capture")
}

#[cfg(target_os = "macos")]
async fn platform_capture(
    mode: capture::CaptureMode,
    _app: &tauri::AppHandle,
    out: &Path,
    _out_str: &str,
    cursor: bool,
    delay: u32,
    _backend: &str,
    library_dir: &str,
    operation_id: &str,
) -> (Result<String, String>, &'static str) {
    if delay > 0 {
        tokio::time::sleep(std::time::Duration::from_secs(delay as u64)).await;
    }
    let out = out.to_path_buf();
    if mode == capture::CaptureMode::Fullscreen {
        let result = tokio::task::spawn_blocking(move || {
            capture::macos::capture_once(mode, &out, cursor)
                .map(|backend| (out.to_string_lossy().into_owned(), backend))
        })
        .await
        .map_err(|err| format!("macOS capture task failed: {err}"))
        .and_then(|result| result);
        return match result {
            Ok((path, backend)) => (Ok(path), backend),
            Err(error) => (Err(error), "macos-native-capture"),
        };
    }

    let session_dir = selection_dir(library_dir, operation_id);
    let freeze_dir = session_dir.clone();
    let frozen =
        tokio::task::spawn_blocking(move || capture::macos::freeze_displays(&freeze_dir, false))
            .await
            .map_err(|err| format!("macOS freeze task failed: {err}"))
            .and_then(|result| result);
    let result = match frozen {
        Ok(displays) => {
            let session = selector_session(operation_id, mode, &displays);
            match run_selector(&session_dir, &session).await {
                Ok(wondershot_selector::SelectionResult::Region {
                    display_id,
                    x,
                    y,
                    width,
                    height,
                }) => crop_frozen_region(&displays, &display_id, (x, y, width, height), &out)
                    .map(|_| out.to_string_lossy().into_owned()),
                Ok(wondershot_selector::SelectionResult::Window { window_id }) => {
                    let capture_out = out.clone();
                    tokio::task::spawn_blocking(move || {
                        capture::macos::capture_window_by_id(&window_id, &capture_out, cursor)
                            .map(|_| capture_out.to_string_lossy().into_owned())
                    })
                    .await
                    .map_err(|err| format!("macOS window capture task failed: {err}"))
                    .and_then(|result| result)
                }
                Ok(wondershot_selector::SelectionResult::Cancelled) => {
                    Err("capture cancelled".into())
                }
                Err(error) => Err(error),
            }
        }
        Err(error) => Err(error),
    };
    let _ = std::fs::remove_dir_all(&session_dir);
    (result, "screen-capture-kit")
}

#[cfg(target_os = "linux")]
async fn platform_capture(
    mode: capture::CaptureMode,
    app: &tauri::AppHandle,
    out: &Path,
    out_str: &str,
    cursor: bool,
    delay: u32,
    backend: &str,
    library_dir: &str,
    operation_id: &str,
) -> (Result<String, String>, &'static str) {
    // The compositor portal is the low-latency default on Linux. Spectacle is
    // used only when explicitly selected, avoiding a process/path probe on
    // every capture and keeping the fast portal behavior deterministic.
    if backend == "spectacle" && spectacle_on_path() {
        let result = match run_spectacle(mode, out_str, cursor, delay).await {
            Ok(()) => Ok(out_str.to_string()),
            Err(e) => Err(e),
        };
        return (result, "spectacle");
    }

    // The portal remains the compositor-owned source of pixels. For region
    // mode it captures once, then Wondershot selects and crops that frozen
    // frame locally. Wayland window discovery remains compositor-private, so
    // window mode uses the portal's native picker.
    let interactive = mode == capture::CaptureMode::Window;
    let result = match capture::portal::screenshot(interactive).await {
        Some(p) => {
            if mode == capture::CaptureMode::Region {
                let session_dir = selection_dir(library_dir, operation_id);
                let frozen = std::fs::create_dir_all(&session_dir)
                    .map_err(|e| e.to_string())
                    .and_then(|_| freeze_portal_displays(app, &p, &session_dir));
                let _ = std::fs::remove_file(&p);
                let selected = match frozen {
                    Ok(displays) => {
                        let session = selector_session(operation_id, mode, &displays);
                        match run_selector(&session_dir, &session).await {
                            Ok(wondershot_selector::SelectionResult::Region {
                                display_id,
                                x,
                                y,
                                width,
                                height,
                            }) => crop_frozen_region(
                                &displays,
                                &display_id,
                                (x, y, width, height),
                                out,
                            )
                            .map(|_| out_str.to_string()),
                            Ok(wondershot_selector::SelectionResult::Cancelled) => {
                                Err("capture cancelled".into())
                            }
                            Ok(wondershot_selector::SelectionResult::Window { .. }) => {
                                Err("portal region selector returned a window".into())
                            }
                            Err(error) => Err(error),
                        }
                    }
                    Err(error) => Err(error),
                };
                let _ = std::fs::remove_dir_all(&session_dir);
                selected
            } else if p.parent() == Some(Path::new(library_dir)) {
                Ok(p.to_string_lossy().to_string())
            } else {
                match std::fs::rename(&p, out).or_else(|_| std::fs::copy(&p, out).map(|_| ())) {
                    Ok(()) => Ok(out_str.to_string()),
                    Err(e) => Err(format!("could not move screenshot: {e}")),
                }
            }
        }
        None => Err("portal screenshot cancelled or failed".into()),
    };
    (result, "portal")
}

#[tauri::command]
pub async fn capture_region(
    app: tauri::AppHandle,
    watch: tauri::State<'_, crate::watcher::LibWatch>,
) -> Result<CaptureOutcome, String> {
    do_capture(capture::CaptureMode::Region, &app, watch.inner()).await
}

#[tauri::command]
pub async fn capture_fullscreen(
    app: tauri::AppHandle,
    watch: tauri::State<'_, crate::watcher::LibWatch>,
) -> Result<CaptureOutcome, String> {
    do_capture(capture::CaptureMode::Fullscreen, &app, watch.inner()).await
}

#[tauri::command]
pub async fn capture_window(
    app: tauri::AppHandle,
    watch: tauri::State<'_, crate::watcher::LibWatch>,
) -> Result<CaptureOutcome, String> {
    do_capture(capture::CaptureMode::Window, &app, watch.inner()).await
}

#[tauri::command]
pub fn native_capture_frame_b64() -> Result<serde_json::Value, String> {
    use base64::Engine;
    use std::io::Cursor;

    let img = capture::native::capture_rgba()?;
    let (width, height) = img.dimensions();
    let (origin_x, origin_y) = capture::native::virtual_origin();
    let monitors: Vec<serde_json::Value> = capture::native::monitor_rects()
        .into_iter()
        .enumerate()
        .map(|(i, monitor)| {
            serde_json::json!({
                "id": i,
                "x": monitor.x - origin_x,
                "y": monitor.y - origin_y,
                "screenX": monitor.x,
                "screenY": monitor.y,
                "width": monitor.width,
                "height": monitor.height,
            })
        })
        .collect();
    let windows: Vec<serde_json::Value> = capture::native::window_rects()
        .into_iter()
        .enumerate()
        .map(|(i, window)| {
            serde_json::json!({
                "id": i,
                "title": window.title,
                "x": window.x - origin_x,
                "y": window.y - origin_y,
                "screenX": window.x,
                "screenY": window.y,
                "width": window.width,
                "height": window.height,
            })
        })
        .collect();
    let mut bytes = Vec::new();
    img.write_to(&mut Cursor::new(&mut bytes), image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(serde_json::json!({
        "width": width,
        "height": height,
        "originX": origin_x,
        "originY": origin_y,
        "monitors": monitors,
        "windows": windows,
        "pngB64": base64::engine::general_purpose::STANDARD.encode(bytes),
    }))
}

#[tauri::command]
pub fn native_capture_capabilities() -> serde_json::Value {
    let caps = capture::native::capabilities();
    serde_json::json!({
        "fullscreen": caps.fullscreen,
        "frame": caps.frame,
        "crop": caps.crop,
        "regionSelector": caps.region_selector,
        "screenSelector": caps.screen_selector,
        "windowSelector": caps.window_selector,
        "monitors": caps.monitors,
        "windows": caps.windows,
    })
}

#[tauri::command]
pub fn save_native_capture_crop(
    app: tauri::AppHandle,
    rect: (u32, u32, u32, u32),
) -> Result<String, String> {
    use tauri::Emitter;

    let s = Settings::load();
    std::fs::create_dir_all(&s.library_dir).map_err(|e| e.to_string())?;
    let img = capture::native::capture_rgba_with_cursor(s.capture_cursor)?;
    let (img_w, img_h) = img.dimensions();
    let (x, y, w, h) = rect;
    if w < 2 || h < 2 || x >= img_w || y >= img_h {
        return Err("empty capture region".into());
    }
    let w = w.min(img_w.saturating_sub(x));
    let h = h.min(img_h.saturating_sub(y));
    let out_img = image::imageops::crop_imm(&img, x, y, w, h).to_image();
    let out = paths::unique_path(Path::new(&s.library_dir), &paths::timestamp_name("Screenshot"));
    out_img.save(&out).map_err(|e| e.to_string())?;
    let path = out.to_string_lossy().to_string();
    restore_main_after_capture(&app, &s);
    let _ = app.emit("capture://done", path.clone());
    Ok(path)
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
    let src = if base0.exists() {
        base0
    } else {
        p.to_path_buf()
    };
    Ok(image::open(&src).map_err(|e| e.to_string())?.to_rgba8())
}

/// Pixelate the rect region of the base PNG; returns the patch as base64 PNG.
#[tauri::command]
pub fn pixelate_patch(
    path: String,
    rect: (u32, u32, u32, u32),
    block: u32,
) -> Result<String, String> {
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
    // The EDITABLE base (base.0 when present), like the pixelate/blur patches —
    // the flattened library file would bake existing annotations into the new base.
    let img = open_patch_source(&path)?;
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

/// Seed an editable base from the original capture without transferring or
/// re-encoding the image. Existing bases are immutable and left untouched.
#[tauri::command]
pub fn ensure_base(path: String, n: u32) -> Result<(), String> {
    let source = Path::new(&path);
    let base = sidecar::base_path(source, n);
    if base.exists() {
        return Ok(());
    }
    if let Some(parent) = base.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let bytes = std::fs::read(source).map_err(|e| e.to_string())?;
    write_atomic(&base, &bytes)
}

/// Save a browser-recorded video blob into the library and emit the same
/// recording completion events as the native Linux recorder.
#[tauri::command]
pub fn save_recording_b64(app: tauri::AppHandle, data_b64: String, ext: Option<String>) -> Result<String, String> {
    use base64::Engine;
    use tauri::Emitter;

    let s = Settings::load();
    let library_dir = Path::new(&s.library_dir);
    std::fs::create_dir_all(library_dir).map_err(|e| e.to_string())?;

    let ext = ext
        .as_deref()
        .map(str::trim)
        .filter(|x| !x.is_empty())
        .unwrap_or("webm")
        .trim_start_matches('.')
        .to_ascii_lowercase();
    let name = paths::timestamp_name("Recording").replace(".png", &format!(".{ext}"));
    let out = paths::unique_path(library_dir, &name);
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(data_b64.as_bytes())
        .map_err(|e| e.to_string())?;
    if bytes.is_empty() {
        return Err("recording produced no data".into());
    }
    std::fs::write(&out, bytes).map_err(|e| e.to_string())?;
    let path = out.to_string_lossy().to_string();
    let _ = app.emit("recording://done", path.clone());
    let _ = app.emit(
        "recording://state",
        serde_json::json!({ "status": "idle", "paused": false }),
    );
    Ok(path)
}

/// Return the path of editable base `n` when it exists. The webview streams it
/// from the allow-listed loopback image server instead of copying it through
/// IPC as base64.
#[tauri::command]
pub fn read_base_path(path: String, n: u32) -> Option<String> {
    let base = sidecar::base_path(Path::new(&path), n);
    if !base.exists() {
        return None;
    }
    Some(base.to_string_lossy().into_owned())
}

// --- screen recording (M4 T6) ----------------------------------------------

/// Managed Tauri state holding the live recorder. `Recorder` is not `Clone`
/// and `stop(self)` consumes it, so we store an `Option` and `.take()` on stop.
pub struct RecState {
    pub recorder: Mutex<Option<recorder::Recorder>>,
    /// The live portal session — closed when the recording ends (any way it
    /// ends), or the compositor keeps showing its "screen is being shared"
    /// indicator and every new recording stacks another one.
    #[cfg(target_os = "linux")]
    pub session: Mutex<Option<portal::CastSession>>,
}

impl Default for RecState {
    fn default() -> Self {
        RecState {
            recorder: Mutex::new(None),
            #[cfg(target_os = "linux")]
            session: Mutex::new(None),
        }
    }
}

/// Close (best-effort) the stored portal session, asynchronously.
#[cfg(target_os = "linux")]
fn close_cast_session(app: &tauri::AppHandle) {
    use tauri::Manager;
    let taken = app
        .state::<RecState>()
        .session
        .lock()
        .ok()
        .and_then(|mut s| s.take());
    if let Some(session) = taken {
        tauri::async_runtime::spawn(async move {
            portal::close_session(&session).await;
        });
    }
}

/// Map a `RecEvent` to a `recording://` webview event.
///
/// Payloads:
///   - `recording://state`  { status: "recording"|"stopping"|"idle", paused: bool }
///   - `recording://tick`   "M:SS" elapsed string
///   - `recording://done`   the finished file path
///   - `recording://failed` the error message
#[cfg(target_os = "linux")]
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
            close_cast_session(app);
            // External terminations finalize via the watchdog without a
            // stop_recording call — drop the recorder handle too so the next
            // start doesn't think one is live.
            drop_recorder_handle(app);
            let _ = app.emit("recording://done", path.to_string_lossy().to_string());
            let _ = app.emit(
                "recording://state",
                serde_json::json!({ "status": "idle", "paused": false }),
            );
        }
        RecEvent::Failed(msg) => {
            close_cast_session(app);
            drop_recorder_handle(app);
            let _ = app.emit("recording://failed", msg);
            let _ = app.emit(
                "recording://state",
                serde_json::json!({ "status": "idle", "paused": false }),
            );
        }
    }
}

/// Clear the stored Recorder without running stop() — used when the watchdog
/// already finalized (external termination). Dropping the handle is safe: the
/// pipeline was already set to NULL by the salvage path and the watchdog
/// thread exits after emitting the terminal event.
#[cfg(target_os = "linux")]
fn drop_recorder_handle(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Ok(mut r) = app.state::<RecState>().recorder.lock() {
        let _ = r.take();
    }
}

/// Remove `.rendering` tmp files older than 1h (orphaned by a crash).
/// Ports the effect of record.py's `sweep_stale_tmp`.
#[cfg(target_os = "linux")]
fn sweep_stale_tmp(rendering: &Path) {
    let _ = std::fs::create_dir_all(rendering);
    let Ok(entries) = std::fs::read_dir(rendering) else {
        return;
    };
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
    rect: Option<(u32, u32, u32, u32)>,
) -> Result<(), String> {
    #[cfg(not(any(target_os = "linux", target_os = "windows")))]
    {
        let _ = (app, state, rect);
        return Err("screen recording is not available on this platform yet".into());
    }

    #[cfg(target_os = "windows")]
    {
        let s = Settings::load();
        let library_dir = Path::new(&s.library_dir);
        std::fs::create_dir_all(library_dir).map_err(|e| e.to_string())?;
        let rendering = files::rendering_dir(library_dir);
        std::fs::create_dir_all(&rendering).map_err(|e| e.to_string())?;

        let name = files::recording_name();
        let tmp = rendering.join(&name);
        let out = paths::unique_path(library_dir, &name);
        let desc = recorder::build_recording_args(
            &tmp,
            rect,
            s.capture_cursor,
            s.mic_enabled,
            &s.mic_device,
        )
        .join("\n");
        let app_for_cb = app.clone();
        let rec = recorder::Recorder::launch(&desc, tmp, out, move |ev| {
            emit_rec_event(&app_for_cb, ev)
        })?;
        *state.recorder.lock().map_err(|e| e.to_string())? = Some(rec);
        Ok(())
    }

    #[cfg(target_os = "linux")]
    {
    let _ = rect;
    use std::os::fd::AsRawFd;

    let s = Settings::load();
    let library_dir = Path::new(&s.library_dir);

    // Sweep stale tmp renders (>1h old) before starting a fresh one.
    let rendering = files::rendering_dir(library_dir);
    sweep_stale_tmp(&rendering);

    // Portal: pick a screen/window and obtain the PipeWire fd + node id. KEEP
    // `fd` (OwnedFd) alive across launch — pipewiresrc dups it during launch.
    let (fd, node, session) = portal::open_screencast().await?;

    // Same base name for tmp and out; the out path is uniquified.
    let name = files::recording_name();
    let tmp = rendering.join(&name);
    let out = paths::unique_path(library_dir, &name);

    // mic_device in settings is a human-readable description (shared with the
    // Python app's conf); resolve it to the pulse source name here. webrtcdsp
    // is probed for real (record.py parity) — the GNOME runtime ships it, and
    // without it the noise_suppression setting silently did nothing.
    let opts = pipeline::PipelineOpts {
        mic_enabled: s.mic_enabled,
        mic_device: recorder::resolve_mic_source(&s.mic_device),
        noise_suppression: s.noise_suppression,
        have_webrtcdsp: recorder::have_gst_element("webrtcdsp"),
        crop: None,
        halo: s.record_cursor_halo,
    };

    let tmp_str = tmp
        .to_str()
        .ok_or("tmp path is not valid UTF-8")?
        .to_string();
    let desc = pipeline::build_pipeline_description(fd.as_raw_fd(), node, &tmp_str, &opts);

    let app_for_cb = app.clone();
    let rec =
        recorder::Recorder::launch(&desc, tmp, out, move |ev| emit_rec_event(&app_for_cb, ev))?;

    // `fd` (OwnedFd) was kept alive through launch; pipewiresrc has dup'd it,
    // so it may drop now.
    drop(fd);

    *state.recorder.lock().map_err(|e| e.to_string())? = Some(rec);
    *state.session.lock().map_err(|e| e.to_string())? = Some(session);
    Ok(())
    }
}

#[cfg(not(target_os = "linux"))]
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

/// Stop the active recording. `stop()` consumes the recorder and emits
/// `Finished`/`Failed` through the event callback (which also closes the
/// portal session). Async + off-thread: a wedged pipeline's EOS escalation
/// can take up to KILL_MS, and that wait must never block the main thread —
/// that was the "stop freezes the whole app" bug.
#[tauri::command]
pub async fn stop_recording(state: tauri::State<'_, RecState>) -> Result<(), String> {
    let rec = state.recorder.lock().map_err(|e| e.to_string())?.take();
    if let Some(rec) = rec {
        tauri::async_runtime::spawn_blocking(move || rec.stop())
            .await
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Pause the active recording (drops frames until resumed).
#[tauri::command]
pub fn pause_recording(state: tauri::State<'_, RecState>) -> Result<(), String> {
    if let Some(rec) = state.recorder.lock().map_err(|e| e.to_string())?.as_ref() {
        rec.pause();
    }
    Ok(())
}

/// Resume a paused recording.
#[tauri::command]
pub fn resume_recording(state: tauri::State<'_, RecState>) -> Result<(), String> {
    if let Some(rec) = state.recorder.lock().map_err(|e| e.to_string())?.as_ref() {
        rec.resume();
    }
    Ok(())
}

// --- video: ffmpeg-driven operations (M5 T2) -------------------------------

/// Locate the ffmpeg binary. M2/M4 have no bundled-ffmpeg helper, so resolve
/// it on PATH (the flatpak ships ffmpeg in the runtime; dev hosts have it too).
fn find_ffmpeg() -> Result<String, String> {
    wondershot_core::ffmpeg::find_ffmpeg().map(|p| p.to_string_lossy().into_owned())
}

fn ffmpeg_command(ffmpeg: &str) -> tokio::process::Command {
    #[allow(unused_mut)]
    let mut command = tokio::process::Command::new(ffmpeg);
    #[cfg(target_os = "windows")]
    {
        command.creation_flags(0x08000000);
    }
    command
}

/// The library dir and the `.rendering` tmp dir (created), as paths.
fn library_and_rendering() -> (std::path::PathBuf, std::path::PathBuf) {
    let s = Settings::load();
    let library_dir = std::path::PathBuf::from(&s.library_dir);
    let _ = std::fs::create_dir_all(&library_dir);
    let rendering = library_dir.join(".rendering");
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
    let output = ffmpeg_command(&ffmpeg)
        .args(args)
        .output()
        .await
        .map_err(|e| format!("could not start ffmpeg: {e}"))?;
    if !output.status.success() {
        let _ = std::fs::remove_file(tmp);
        let stderr = String::from_utf8_lossy(&output.stderr);
        let tail: String = stderr
            .lines()
            .rev()
            .take(4)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect::<Vec<_>>()
            .join("\n");
        return Err(format!("ffmpeg failed: {tail}"));
    }
    if !tmp.exists() {
        return Err("ffmpeg produced no output file".into());
    }
    let out = paths::unique_path(library_dir, out_name);
    std::fs::rename(tmp, &out)
        .or_else(|_| {
            std::fs::copy(tmp, &out)
                .map(|_| ())
                .and_then(|_| std::fs::remove_file(tmp))
        })
        .map_err(|e| format!("could not move render into library: {e}"))?;
    Ok(out.to_string_lossy().into_owned())
}

/// Poster frame for a video's filmstrip card, returned as a base64 PNG body
/// (Qt parity: video thumbnails show a real frame, not a generic icon).
/// Extracted with ffmpeg at t=0, scaled to thumbnail width, and cached in
/// `~/.cache/wondershot/thumbs/` keyed on path+mtime so each video pays the
/// ffmpeg cost once.
#[tauri::command]
pub async fn video_thumb(path: String) -> Result<String, String> {
    use base64::Engine;
    use std::hash::{Hash, Hasher};
    let mtime = std::fs::metadata(&path)
        .and_then(|m| m.modified())
        .map_err(|e| e.to_string())?;
    let mut h = std::collections::hash_map::DefaultHasher::new();
    path.hash(&mut h);
    mtime.hash(&mut h);
    let cache_dir = dirs::cache_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("wondershot")
        .join("thumbs");
    std::fs::create_dir_all(&cache_dir).map_err(|e| e.to_string())?;
    let thumb = cache_dir.join(format!("{:016x}.png", h.finish()));
    if !thumb.exists() {
        let ffmpeg = find_ffmpeg()?;
        let args: Vec<String> = vec![
            "-y".into(),
            "-ss".into(),
            "0".into(),
            "-i".into(),
            path.clone(),
            "-frames:v".into(),
            "1".into(),
            "-vf".into(),
            "scale=480:-2".into(),
            thumb.to_string_lossy().into_owned(),
        ];
        let out = ffmpeg_command(&ffmpeg)
            .args(&args)
            .output()
            .await
            .map_err(|e| format!("could not start ffmpeg: {e}"))?;
        if !out.status.success() || !thumb.exists() {
            return Err("ffmpeg could not extract a poster frame".into());
        }
    }
    let bytes = std::fs::read(&thumb).map_err(|e| e.to_string())?;
    Ok(base64::engine::general_purpose::STANDARD.encode(bytes))
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
         Categories=Utility;Graphics;\nStartupNotify=true\n\
         MimeType=x-scheme-handler/wondershot;\n",
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
    let visible = app
        .get_webview_window("bubble")
        .and_then(|w| w.is_visible().ok())
        .unwrap_or(false);
    set_camera_bubble(app, !visible)?;
    Ok(!visible)
}

/// Show/hide the camera bubble — the ONLY correct way to do it: visibility
/// and the camera stream lifecycle must move together (the bubble page
/// starts/stops its MJPEG stream on these events). Direct window.show()
/// produced a bubble with no feed.
#[tauri::command]
pub fn set_camera_bubble(app: tauri::AppHandle, visible: bool) -> Result<(), String> {
    use tauri::{Emitter, Manager};
    let Some(w) = app.get_webview_window("bubble") else {
        return Err("camera bubble window not found".into());
    };
    if visible {
        w.show().map_err(|e| e.to_string())?;
        let _ = w.set_focus();
        let _ = app.emit("bubble://shown", ());
    } else {
        w.hide().map_err(|e| e.to_string())?;
        // Release the webcam while hidden. The bubble://hidden event asks the
        // webview to drop its <img> (closes the socket), but WebKitGTK often
        // keeps a multipart/x-mixed-replace connection alive — leaving the gst
        // pipeline PLAYING and the PipeWire camera node "in use", which keeps
        // the machine awake. Tear the stream down from the backend too so the
        // release is deterministic regardless of what the webview does.
        let _ = app.emit("bubble://hidden", ());
        crate::media_server::stop_camera();
    }
    Ok(())
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
    let candidates: [(&str, &[&str]); 2] = [
        ("systemsettings", &["kcm_keys"]),
        ("kcmshell6", &["kcm_keys"]),
    ];
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

/// Open a path/URL with the platform's native launcher. Linux routes through
/// the host opener when sandboxed.
fn open_target(target: &str) -> Result<(), String> {
    let (program, args) = wondershot_core::opener::open_command(
        wondershot_core::opener::OpenPlatform::current(),
        in_flatpak(),
        target,
    )?;
    std::process::Command::new(program)
        .args(args)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

// --- OneDrive / SharePoint (Microsoft Graph) --------------------------------

/// Fans `wondershot://auth` callback URLs out to whichever interactive login
/// is currently awaiting one (wonderblob's DeepLinkRouter pattern). The OS
/// protocol handler relaunches wondershot with the URL; single-instance
/// forwards it to dispatch_cli, which delivers here.
pub struct AuthRouter(tokio::sync::broadcast::Sender<String>);

impl Default for AuthRouter {
    fn default() -> Self {
        let (tx, _rx) = tokio::sync::broadcast::channel(16);
        AuthRouter(tx)
    }
}

impl AuthRouter {
    pub fn deliver(&self, url: String) {
        let _ = self.0.send(url);
    }
}

/// Interactive OneDrive sign-in: PKCE + system browser + custom-scheme
/// redirect. Returns the connected account label. The device-code flow stays
/// available as the fallback (e.g. when `wondershot://auth` isn't registered
/// for a custom client id, or no browser can reach back to this instance).
#[tauri::command]
pub async fn graph_connect_interactive(
    router: tauri::State<'_, AuthRouter>,
    client_id: String,
) -> Result<String, String> {
    let cid = if client_id.trim().is_empty() {
        graph::DEFAULT_CLIENT_ID.to_string()
    } else {
        client_id.trim().to_string()
    };
    let (verifier, challenge) = graph::pkce();
    let state = uuid_state();
    let url = graph::authorize_url(&cid, &challenge, &state);

    // Subscribe BEFORE opening the browser so a fast redirect can't be missed.
    let mut rx = router.0.subscribe();
    open_target(&url)?;

    // Await OUR callback (matching state), bounded so an abandoned browser
    // sign-in can't hang the command forever.
    let callback = tokio::time::timeout(std::time::Duration::from_secs(10 * 60), async {
        loop {
            let cb = rx
                .recv()
                .await
                .map_err(|_| "sign-in channel closed".to_string())?;
            match graph::parse_callback(&cb) {
                Ok((code, got)) if got == state => return Ok(code),
                Ok(_) => continue, // stale callback from an older attempt
                Err(e) if cb.contains("error=") => return Err(e),
                Err(_) => continue,
            }
        }
    })
    .await
    .map_err(|_| "sign-in timed out waiting for the browser redirect".to_string())??;

    let cid2 = cid.clone();
    let tokens = tauri::async_runtime::spawn_blocking(move || {
        graph::exchange_code(&cid2, &callback, &verifier)
    })
    .await
    .map_err(|e| e.to_string())??;
    let token = tokens
        .get("access_token")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let account = tauri::async_runtime::spawn_blocking(move || graph::whoami(&token))
        .await
        .map_err(|e| e.to_string())?
        .unwrap_or_else(|_| "connected".into());
    graph::save_tokens(&tokens, &cid, &account)?;
    Ok(account)
}

/// CSRF state — random urlsafe via the PKCE helper's RNG path.
fn uuid_state() -> String {
    graph::pkce().0.chars().take(32).collect()
}

// --- (device-code OAuth, kept as the fallback path) --------------------------

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
pub fn graph_connect_poll(
    client_id: String,
    device_code: String,
) -> Result<serde_json::Value, String> {
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
pub fn test_ai_endpoint(
    endpoint: String,
    model: String,
    api_key: String,
) -> Result<String, String> {
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
            let suffix = if m.is_empty() {
                String::new()
            } else {
                format!(" · model “{m}” will be used")
            };
            Ok(format!("Connected (HTTP {}){suffix}", resp.status()))
        }
        Err(ureq::Error::Status(code, _)) => Err(format!(
            "Endpoint reachable but returned HTTP {code} (check API key/model)"
        )),
        Err(e) => Err(format!("Could not reach endpoint: {e}")),
    }
}

/// Start the interactive capture picker used by the header and global hotkey.
/// Windows keeps its hybrid region/window hover picker and post-selection
/// Capture/Record action bar; explicit panel modes continue through the shared
/// freeze-first selector in `do_capture`.
#[tauri::command]
pub async fn show_capture_window(
    app: tauri::AppHandle,
    _watch: tauri::State<'_, crate::watcher::LibWatch>,
) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        use tauri::Emitter;

        logging::log("show_capture_window: spawning Windows picker thread");
        let app_for_thread = app.clone();
        std::thread::Builder::new()
            .name("wondershot-capture-picker".into())
            .spawn(move || {
                logging::log("Windows picker thread started");
                if let Err(error) = run_windows_capture_picker(app_for_thread.clone()) {
                    logging::log(format!("Windows picker failed: {error}"));
                    let _ = app_for_thread.emit("capture://failed", error);
                }
                logging::log("Windows picker thread finished");
            })
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    #[cfg(not(target_os = "windows"))]
    {
        use tauri::Emitter;

        let outcome = do_capture(capture::CaptureMode::Region, &app, _watch.inner()).await?;
        app.emit("capture://done", outcome.capture.path.clone())
            .map_err(|error| error.to_string())
    }
}

#[tauri::command]
pub fn copy_files(paths: Vec<String>) -> Result<bool, String> {
    if paths.is_empty() {
        return Ok(false);
    }
    for path in &paths {
        if !Path::new(path).is_file() {
            return Err(format!("Capture does not exist: {path}"));
        }
    }

    #[cfg(target_os = "windows")]
    {
        use clipboard_win::{formats::FileList, Clipboard, Setter};
        let _clipboard = Clipboard::new_attempts(10).map_err(|e| e.to_string())?;
        FileList.write_clipboard(&paths).map_err(|e| e.to_string())?;
        return Ok(true);
    }

    #[cfg(not(target_os = "windows"))]
    {
        // File-list clipboard formats differ by desktop. Preserve a useful
        // fallback without pretending repeated bitmap copies are cumulative.
        let mut cb = arboard::Clipboard::new().map_err(|e| e.to_string())?;
        cb.set_text(paths.join("\n")).map_err(|e| e.to_string())?;
        Ok(true)
    }
}

#[cfg(target_os = "windows")]
fn run_windows_capture_picker(app: tauri::AppHandle) -> Result<(), String> {
    use tauri::Emitter;

    let app_for_bar = app.clone();
    let listener_ids = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let listener_ids_for_bar = listener_ids.clone();
    logging::log("Windows picker: entering native picker");
    let choice = capture::win::pick_action_with_toolbar(move |toolbar, signal| {
        logging::log(format!(
            "Windows picker: request actionbar rect={:?} toolbar={:?}",
            toolbar.rect, toolbar.toolbar
        ));
        show_capture_action_bar(
            app_for_bar.clone(),
            toolbar,
            signal,
            listener_ids_for_bar.clone(),
        );
    })?;
    cleanup_capture_action_bar(&app, listener_ids);

    let Some(choice) = choice else {
        logging::log("Windows picker: cancelled");
        return Ok(());
    };
    logging::log(format!(
        "Windows picker: selected action={:?} rect={:?} hwnd={:?}",
        choice.action, choice.rect, choice.hwnd
    ));

    if choice.action == capture::win::PickerAction::Record {
        logging::log("Windows picker: emitting region://record-rect");
        let _ = app.emit("region://record-rect", choice.rect);
        return Ok(());
    }

    let settings = Settings::load();
    std::fs::create_dir_all(&settings.library_dir).map_err(|error| error.to_string())?;
    let out = paths::unique_path(
        Path::new(&settings.library_dir),
        &paths::timestamp_name("Screenshot"),
    );

    if let Some(hwnd) = choice.hwnd {
        let window_id = format!("0x{:x}", hwnd as usize);
        if let Err(error) =
            capture::windows::capture_window_by_id(&window_id, &out, settings.capture_cursor)
        {
            logging::log(format!(
                "Windows Graphics Capture failed, falling back to legacy window capture: {error}"
            ));
            let image = capture::win::capture_window_rgba(hwnd).or_else(|window_error| {
                logging::log(format!(
                    "Windows window capture failed, falling back to desktop crop: {window_error}"
                ));
                let desktop =
                    capture::native::capture_rgba_with_cursor(settings.capture_cursor)?;
                crop_capture_image(desktop, choice.rect)
            })?;
            image.save(&out).map_err(|error| error.to_string())?;
        }
    } else {
        let desktop = capture::native::capture_rgba_with_cursor(settings.capture_cursor)?;
        crop_capture_image(desktop, choice.rect)?
            .save(&out)
            .map_err(|error| error.to_string())?;
    }

    let path = out.to_string_lossy().to_string();
    logging::log(format!("Windows picker: saved capture {path}"));
    restore_main_after_capture(&app, &settings);
    let _ = app.emit("capture://done", path);
    Ok(())
}

#[cfg(target_os = "windows")]
fn crop_capture_image(
    image: image::RgbaImage,
    rect: (u32, u32, u32, u32),
) -> Result<image::RgbaImage, String> {
    let (image_width, image_height) = image.dimensions();
    let (x, y, width, height) = rect;
    if width < 2 || height < 2 || x >= image_width || y >= image_height {
        return Err("empty capture region".into());
    }
    let width = width.min(image_width.saturating_sub(x));
    let height = height.min(image_height.saturating_sub(y));
    Ok(image::imageops::crop_imm(&image, x, y, width, height).to_image())
}

#[cfg(target_os = "windows")]
fn show_capture_action_bar(
    app: tauri::AppHandle,
    toolbar: capture::win::PickerToolbar,
    signal: std::sync::Arc<std::sync::Mutex<Option<capture::win::PickerToolbarResult>>>,
    listener_ids: std::sync::Arc<std::sync::Mutex<Vec<tauri::EventId>>>,
) {
    use tauri::{Listener, Manager};

    const LABEL: &str = "capture-actionbar";

    let signal_for_event = signal.clone();
    let listener = app.once("capture-actionbar://action", move |event| {
        let value = serde_json::from_str::<String>(event.payload())
            .unwrap_or_else(|_| event.payload().trim_matches('"').to_string());
        logging::log(format!("actionbar: event action={value}"));
        let mapped = match value.as_str() {
            "capture" => capture::win::PickerToolbarResult::Capture,
            "record" => capture::win::PickerToolbarResult::Record,
            _ => capture::win::PickerToolbarResult::Cancel,
        };
        set_toolbar_signal(signal_for_event.clone(), mapped);
    });
    if let Ok(mut ids) = listener_ids.lock() {
        ids.push(listener);
    }

    let url = format!(
        "/capture-actionbar?w={}&h={}",
        toolbar.rect.2, toolbar.rect.3
    );
    let (built_tx, built_rx) = std::sync::mpsc::channel();
    let app_for_ui = app.clone();
    logging::log(format!("actionbar: scheduling build url={url}"));
    if let Err(error) = app.run_on_main_thread(move || {
        if let Some(window) = app_for_ui.get_webview_window(LABEL) {
            let _ = window.close();
        }
        let result = tauri::WebviewWindowBuilder::new(
            &app_for_ui,
            LABEL,
            tauri::WebviewUrl::App(url.into()),
        )
        .background_color(tauri::utils::config::Color(20, 20, 23, 255))
        .title("")
        .position(toolbar.toolbar.0 as f64, toolbar.toolbar.1 as f64)
        .inner_size(toolbar.toolbar.2 as f64, toolbar.toolbar.3 as f64)
        .resizable(false)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(true)
        .build()
        .map(|_| ())
        .map_err(|error| error.to_string());
        let _ = built_tx.send(result);
    }) {
        logging::log(format!("actionbar: could not schedule build: {error}"));
        set_toolbar_signal(signal, capture::win::PickerToolbarResult::Cancel);
        return;
    }

    match built_rx.recv_timeout(std::time::Duration::from_secs(3)) {
        Ok(Ok(())) => logging::log("actionbar: built"),
        Ok(Err(error)) => {
            logging::log(format!("actionbar: build failed: {error}"));
            set_toolbar_signal(signal, capture::win::PickerToolbarResult::Cancel);
        }
        Err(error) => {
            logging::log(format!("actionbar: build timed out: {error}"));
            set_toolbar_signal(signal, capture::win::PickerToolbarResult::Cancel);
        }
    }
}

#[cfg(target_os = "windows")]
fn set_toolbar_signal(
    signal: std::sync::Arc<std::sync::Mutex<Option<capture::win::PickerToolbarResult>>>,
    value: capture::win::PickerToolbarResult,
) {
    if let Ok(mut slot) = signal.lock() {
        *slot = Some(value);
    }
}

#[cfg(target_os = "windows")]
fn cleanup_capture_action_bar(
    app: &tauri::AppHandle,
    listener_ids: std::sync::Arc<std::sync::Mutex<Vec<tauri::EventId>>>,
) {
    use tauri::{Listener, Manager};

    logging::log("actionbar: cleanup requested");
    let app_for_ui = app.clone();
    if let Err(error) = app.run_on_main_thread(move || {
        if let Some(window) = app_for_ui.get_webview_window("capture-actionbar") {
            let _ = window.hide();
            let _ = window.close();
        }
    }) {
        logging::log(format!("actionbar: cleanup schedule failed: {error}"));
    }
    if let Ok(mut ids) = listener_ids.lock() {
        for id in ids.drain(..) {
            app.unlisten(id);
        }
    }
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

/// Share the capture at `path` via the configured default provider: upload,
/// copy the time-limited link to the clipboard, return {url, provider}.
/// Errors with guidance when no provider is configured/connected.
#[tauri::command]
pub async fn share_capture(path: String) -> Result<serde_json::Value, String> {
    let s = Settings::load();
    let provider = crate::share::default_provider(&s);
    if provider.is_empty() {
        return Err(
            "No share provider configured — set up S3, Azure, or connect OneDrive in Settings → Sharing"
                .into(),
        );
    }
    let prov = provider.clone();
    let url =
        tauri::async_runtime::spawn_blocking(move || crate::share::share_file(&s, &path, &prov))
            .await
            .map_err(|e| e.to_string())??;
    // Best-effort clipboard copy (wl-clipboard path first, arboard fallback).
    let copied = clipboard::copy_text(&url).unwrap_or(false)
        || arboard::Clipboard::new()
            .and_then(|mut cb| cb.set_text(url.clone()))
            .is_ok();
    Ok(serde_json::json!({ "url": url, "provider": provider, "copied": copied }))
}

// --- u2net model download (first Remove BG) ---------------------------------

/// Where the model comes from + what it must hash to (same source the
/// Flatpak used to bundle; rembg's canonical release asset).
const U2NET_URL: &str = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx";
const U2NET_SHA256: &str = "8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491";

/// Download u2net (~168 MB) to `~/.cache/wondershot/u2net.onnx`, emitting
/// `bg-model://progress` (0–100) along the way. sha256-verified, atomic
/// rename — a torn download can never be mistaken for the model. No-op if
/// the model already resolves.
#[tauri::command]
pub async fn bg_model_download(app: tauri::AppHandle) -> Result<(), String> {
    if bgremove::model_available() {
        return Ok(());
    }
    tauri::async_runtime::spawn_blocking(move || {
        use sha2::Digest;
        use std::io::{Read, Write};
        use tauri::Emitter;

        let dest = bgremove::model_path();
        if let Some(parent) = dest.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let tmp = dest.with_extension("onnx.part");

        let resp = ureq::get(U2NET_URL)
            .timeout(std::time::Duration::from_secs(1800))
            .call()
            .map_err(|e| format!("model download failed: {e}"))?;
        let total: u64 = resp
            .header("Content-Length")
            .and_then(|h| h.parse().ok())
            .unwrap_or(0);

        let mut reader = resp.into_reader();
        let mut out = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
        let mut hasher = sha2::Sha256::new();
        let mut buf = [0u8; 64 * 1024];
        let mut done: u64 = 0;
        let mut last_pct: u64 = 0;
        loop {
            let n = reader
                .read(&mut buf)
                .map_err(|e| format!("model download failed: {e}"))?;
            if n == 0 {
                break;
            }
            out.write_all(&buf[..n]).map_err(|e| e.to_string())?;
            hasher.update(&buf[..n]);
            done += n as u64;
            if total > 0 {
                let pct = done * 100 / total;
                if pct != last_pct {
                    last_pct = pct;
                    let _ = app.emit("bg-model://progress", pct);
                }
            }
        }
        drop(out);

        let got = format!("{:x}", hasher.finalize());
        if got != U2NET_SHA256 {
            let _ = std::fs::remove_file(&tmp);
            return Err("model download corrupted (checksum mismatch) — try again".into());
        }
        std::fs::rename(&tmp, &dest).map_err(|e| e.to_string())?;
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
}

/// The exact command a desktop shortcut should run to trigger a capture in
/// the running app (Settings → Global capture hotkey). The bare name
/// `wondershot` isn't on PATH for a Flatpak install, and even host installs
/// want the full path (the Qt dialog showed one).
#[tauri::command]
pub fn capture_command() -> String {
    if in_flatpak() {
        "flatpak run io.github.jackmusick.wondershot --capture".into()
    } else {
        std::env::current_exe()
            .map(|p| format!("{} --capture", p.display()))
            .unwrap_or_else(|_| "wondershot --capture".into())
    }
}

/// Capture devices for the Settings dropdowns ({kind, label}), enumerated in
/// the backend (gst DeviceMonitor) so no webview media permission is needed
/// and labels match what `resolve_mic_source` resolves at record time.
#[tauri::command]
pub fn list_media_devices() -> Vec<serde_json::Value> {
    #[cfg(target_os = "linux")]
    {
        recorder::list_capture_devices()
            .into_iter()
            .map(|(kind, label)| serde_json::json!({ "kind": kind, "label": label }))
            .collect()
    }
    #[cfg(not(target_os = "linux"))]
    {
        Vec::new()
    }
}

#[tauri::command]
pub fn recorder_capabilities() -> serde_json::Value {
    serde_json::json!({
        "pause": recorder::Recorder::supports_pause(),
    })
}

// --- AI Redact / Simplify (crate::ai) ----------------------------------------

/// Endpoint/model/key from the shared conf's AI keys. The key is optional
/// (local servers); endpoint+model are required.
fn ai_config() -> Result<(String, String, String), String> {
    let s = Settings::load();
    let g = |k: &str| {
        s.extra
            .get(k)
            .map(|v| v.trim().to_string())
            .unwrap_or_default()
    };
    let (endpoint, model, key) = (g("ai_endpoint"), g("ai_model"), g("ai_api_key"));
    if endpoint.is_empty() || model.is_empty() {
        return Err("Configure an AI endpoint and model in Settings → AI first".into());
    }
    Ok((endpoint, model, key))
}

/// Decoded image + PNG bytes the AI should see: the EDITABLE base (same source
/// as the pixelate/blur patches), so already-applied redactions don't skew it.
fn ai_source(path: &str) -> Result<(image::RgbaImage, Vec<u8>), String> {
    let img = open_patch_source(path)?;
    let mut png: Vec<u8> = Vec::new();
    img.write_to(&mut std::io::Cursor::new(&mut png), image::ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok((img, png))
}

/// Find sensitive text on the capture; returns pixel rects for the editor to
/// cover with pixelate items. Blocking pipeline (OCR + LLM) runs off-thread.
#[tauri::command]
pub async fn ai_redact(path: String) -> Result<Vec<crate::ai::RectPx>, String> {
    let (endpoint, model, key) = ai_config()?;
    tauri::async_runtime::spawn_blocking(move || {
        let (img, png) = ai_source(&path)?;
        let (w, h) = (img.width() as i32, img.height() as i32);
        crate::ai::redact_regions(&png, w, h, &endpoint, &key, &model)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Label the capture's major UI regions; returns rect+kind+fill/stroke colors
/// for the editor to replace with clean editable rects.
#[tauri::command]
pub async fn ai_simplify(path: String) -> Result<Vec<crate::ai::SimplifyRegion>, String> {
    let (endpoint, model, key) = ai_config()?;
    tauri::async_runtime::spawn_blocking(move || {
        let (img, png) = ai_source(&path)?;
        crate::ai::simplify_regions(&img, &png, &endpoint, &key, &model)
    })
    .await
    .map_err(|e| e.to_string())?
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
    fn selector_session_preserves_physical_window_geometry() {
        let displays = vec![capture::FrozenDisplay {
            id: "left".into(),
            frame_path: PathBuf::from("left.png"),
            x: -1920,
            y: 0,
            pixel_width: 1920,
            pixel_height: 1080,
            windows: vec![capture::WindowTarget {
                id: "window-1".into(),
                title: "Editor".into(),
                application: "Example".into(),
                x: -1200,
                y: 80,
                width: 900,
                height: 700,
                z_order: 2,
                capturable: true,
            }],
        }];
        let session = selector_session("capture-1", capture::CaptureMode::Window, &displays);
        assert_eq!(session.mode, wondershot_selector::SelectionMode::Window);
        assert_eq!(session.displays[0].x, -1920);
        assert_eq!(session.displays[0].windows[0].x, -1200);
        assert_eq!(session.displays[0].windows[0].z_order, 2);
    }

    #[test]
    fn frozen_region_crop_uses_the_selected_display_pixels() {
        let dir = std::env::temp_dir().join(format!(
            "ws-frozen-crop-{}-{}",
            std::process::id(),
            CAPTURE_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let frame = dir.join("display.png");
        image::RgbaImage::from_fn(8, 6, |x, y| image::Rgba([x as u8, y as u8, 0, 255]))
            .save(&frame)
            .unwrap();
        let displays = vec![capture::FrozenDisplay {
            id: "display".into(),
            frame_path: frame,
            x: 0,
            y: 0,
            pixel_width: 8,
            pixel_height: 6,
            windows: Vec::new(),
        }];
        let out = dir.join("crop.png");
        crop_frozen_region(&displays, "display", (2, 1, 4, 3), &out).unwrap();
        let crop = image::open(out).unwrap().to_rgba8();
        assert_eq!(crop.dimensions(), (4, 3));
        assert_eq!(crop.get_pixel(0, 0).0, [2, 1, 0, 255]);
        assert_eq!(crop.get_pixel(3, 2).0, [5, 3, 0, 255]);
        std::fs::remove_dir_all(dir).unwrap();
    }

}
