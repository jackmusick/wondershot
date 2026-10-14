//! Windows still-image capture backend.
//!
//! This module is intentionally side-effect free at crate load time. The Tauri
//! command layer can call [`capture_once`] from a blocking task and keep the app
//! process resident, avoiding the Python/Qt startup and BitBlt full-desktop copy
//! path that made Windows capture feel slow.
//!
//! Integration notes:
//! - Add `pub mod windows;` behind `#[cfg(target_os = "windows")]` in
//!   `capture/mod.rs`.
//! - Add a target-specific dependency:
//!   `windows-capture = "2.0.1"` under
//!   `[target.'cfg(target_os = "windows")'.dependencies]`.
//! - Region capture needs the selection overlay to pass a monitor-relative crop
//!   rectangle. Until that contract exists, this backend refuses region mode
//!   instead of returning a fullscreen screenshot with incorrect semantics.

#![cfg(target_os = "windows")]

use std::error::Error;
use std::path::{Path, PathBuf};

use windows_capture::capture::{Context, GraphicsCaptureApiHandler};
use windows_capture::encoder::ImageFormat;
use windows_capture::frame::Frame;
use windows_capture::graphics_capture_api::InternalCaptureControl;
use windows_capture::graphics_capture_picker::GraphicsCapturePicker;
use windows_capture::monitor::Monitor;
use windows_capture::settings::{
    ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings,
    MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings,
};

use super::CaptureMode;
use super::{FrozenDisplay, WindowTarget};
use windows::Win32::Foundation::RECT;
use windows::Win32::Graphics::Gdi::{GetMonitorInfoW, HMONITOR, MONITORINFO};
use windows_capture::window::Window;

const BACKEND_LABEL: &str = "windows-graphics-capture";
const REGION_UNSUPPORTED: &str =
    "Windows region capture needs an overlay-provided crop rectangle; refusing fullscreen fallback";

type CaptureError = Box<dyn Error + Send + Sync>;

struct OneShotCapture {
    out: PathBuf,
}

impl GraphicsCaptureApiHandler for OneShotCapture {
    type Flags = PathBuf;
    type Error = CaptureError;

    fn new(ctx: Context<Self::Flags>) -> Result<Self, Self::Error> {
        Ok(Self { out: ctx.flags })
    }

    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame,
        capture_control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        let result = frame.save_as_image(&self.out, ImageFormat::Png);
        capture_control.stop();
        result.map_err(|err| Box::new(err) as Self::Error)
    }
}

/// Capture one still image on Windows and write it to `out`.
///
/// `Window` mode delegates target selection to `GraphicsCapturePicker`, which is
/// the native Windows UX for smooth window/monitor highlighting. `Fullscreen`
/// captures the primary monitor directly. `Region` is deliberately unsupported
/// until the caller can provide a real crop rectangle from a selection overlay.
pub fn capture_once(
    mode: CaptureMode,
    out: impl AsRef<Path>,
    cursor: bool,
) -> Result<&'static str, String> {
    let out = out.as_ref().to_path_buf();
    match mode {
        CaptureMode::Region => Err(REGION_UNSUPPORTED.to_string()),
        CaptureMode::Fullscreen => {
            let monitor =
                Monitor::primary().map_err(|err| format!("primary monitor unavailable: {err}"))?;
            let settings = settings(monitor, out, cursor);
            OneShotCapture::start(settings)
                .map_err(|err| format!("Windows fullscreen capture failed: {err}"))?;
            Ok(BACKEND_LABEL)
        }
        CaptureMode::Window => {
            let item = GraphicsCapturePicker::pick_item()
                .map_err(|err| format!("Windows capture picker failed: {err}"))?
                .ok_or_else(|| "Windows capture picker returned no item".to_string())?;
            let settings = settings(item, out, cursor);
            OneShotCapture::start(settings)
                .map_err(|err| format!("Windows window capture failed: {err}"))?;
            Ok(BACKEND_LABEL)
        }
    }
}

/// Freeze every attached monitor and snapshot the capturable window catalog.
/// Monitor capture finishes before the selector process starts, so Wondershot's
/// overlay can never appear in its own frames.
pub fn freeze_displays(
    out_dir: impl AsRef<Path>,
    cursor: bool,
) -> Result<Vec<FrozenDisplay>, String> {
    std::fs::create_dir_all(out_dir.as_ref()).map_err(|e| e.to_string())?;
    let windows = enumerate_windows();
    let monitors = Monitor::enumerate().map_err(|e| format!("monitor enumeration failed: {e}"))?;
    let mut displays = Vec::with_capacity(monitors.len());
    for (index, monitor) in monitors.into_iter().enumerate() {
        let id = format!("monitor-{index}");
        let out = out_dir.as_ref().join(format!("{id}.png"));
        let rect = monitor_rect(&monitor)?;
        let settings = settings(monitor, out.clone(), cursor);
        OneShotCapture::start(settings)
            .map_err(|e| format!("Windows display freeze failed: {e}"))?;
        let width = (rect.right - rect.left).max(0) as u32;
        let height = (rect.bottom - rect.top).max(0) as u32;
        displays.push(FrozenDisplay {
            id,
            frame_path: out,
            x: rect.left,
            y: rect.top,
            pixel_width: width,
            pixel_height: height,
            windows: windows
                .iter()
                .filter(|window| intersects(window, rect))
                .cloned()
                .collect(),
        });
    }
    if displays.is_empty() {
        return Err("Windows reported no displays".into());
    }
    Ok(displays)
}

pub fn capture_window_by_id(id: &str, out: impl AsRef<Path>, cursor: bool) -> Result<(), String> {
    let raw = usize::from_str_radix(id.trim_start_matches("0x"), 16)
        .map_err(|_| "invalid Windows window identifier".to_string())?;
    let window = Window::from_raw_hwnd(raw as *mut std::ffi::c_void);
    let settings = settings(window, out.as_ref().to_path_buf(), cursor);
    OneShotCapture::start(settings).map_err(|e| format!("Windows window capture failed: {e}"))
}

fn enumerate_windows() -> Vec<WindowTarget> {
    Window::enumerate()
        .unwrap_or_default()
        .into_iter()
        .enumerate()
        .filter_map(|(z_order, window)| {
            if window.process_id().ok() == Some(std::process::id()) {
                return None;
            }
            let rect = window.rect().ok()?;
            let width = (rect.right - rect.left).max(0) as u32;
            let height = (rect.bottom - rect.top).max(0) as u32;
            if width < 2 || height < 2 {
                return None;
            }
            Some(WindowTarget {
                id: format!("0x{:x}", window.as_raw_hwnd() as usize),
                title: window.title().unwrap_or_default(),
                application: window.process_name().unwrap_or_default(),
                x: rect.left,
                y: rect.top,
                width,
                height,
                z_order: z_order as u32,
                capturable: true,
            })
        })
        .collect()
}

fn monitor_rect(monitor: &Monitor) -> Result<RECT, String> {
    let mut info = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    let ok =
        unsafe { GetMonitorInfoW(HMONITOR(monitor.as_raw_hmonitor()), (&raw mut info).cast()) };
    if !ok.as_bool() {
        return Err("GetMonitorInfoW failed".into());
    }
    Ok(info.rcMonitor)
}

fn intersects(window: &WindowTarget, display: RECT) -> bool {
    window.x < display.right
        && window.x.saturating_add_unsigned(window.width) > display.left
        && window.y < display.bottom
        && window.y.saturating_add_unsigned(window.height) > display.top
}

fn settings<T>(item: T, out: PathBuf, cursor: bool) -> Settings<PathBuf, T>
where
    T: TryInto<windows_capture::settings::GraphicsCaptureItemType>,
{
    Settings::new(
        item,
        cursor_setting(cursor),
        DrawBorderSettings::WithoutBorder,
        SecondaryWindowSettings::Include,
        MinimumUpdateIntervalSettings::Default,
        DirtyRegionSettings::Default,
        ColorFormat::Rgba8,
        out,
    )
}

const fn cursor_setting(cursor: bool) -> CursorCaptureSettings {
    if cursor {
        CursorCaptureSettings::WithCursor
    } else {
        CursorCaptureSettings::WithoutCursor
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cursor_true_requests_cursor() {
        assert_eq!(cursor_setting(true), CursorCaptureSettings::WithCursor);
    }

    #[test]
    fn cursor_false_suppresses_cursor() {
        assert_eq!(cursor_setting(false), CursorCaptureSettings::WithoutCursor);
    }

    #[test]
    fn region_error_is_explicit_about_missing_crop_contract() {
        let err = capture_once(CaptureMode::Region, "ignored.png", false).unwrap_err();
        assert!(err.contains("overlay-provided crop rectangle"));
    }
}
