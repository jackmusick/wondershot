//! macOS 14+ still-image capture using ScreenCaptureKit.
//!
//! The primary capture flow freezes each display and caches window geometry
//! before the shared selector starts. The committed window is captured once
//! with `SCScreenshotManager`; pointer movement performs no capture or content
//! enumeration. `capture_once` remains available for non-selector callers.

#![cfg(target_os = "macos")]

use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;

use image::{imageops, RgbaImage};
use screencapturekit::content_sharing_picker::{
    SCContentSharingPicker, SCContentSharingPickerConfiguration, SCContentSharingPickerMode,
    SCPickerOutcome,
};
use screencapturekit::prelude::*;
use screencapturekit::screenshot_manager::SCScreenshotManager;

use super::native::{MonitorRect, NativeCaptureCapabilities, WindowRect};
use super::{CaptureMode, FrozenDisplay, WindowTarget};

const SCREEN_CAPTURE_KIT: &str = "screen-capture-kit";
const REGION_SELECTOR: &str = "macos-region-selector";

pub const fn capabilities() -> NativeCaptureCapabilities {
    NativeCaptureCapabilities {
        fullscreen: true,
        frame: true,
        crop: true,
        region_selector: true,
        screen_selector: true,
        window_selector: true,
        monitors: true,
        windows: true,
    }
}

/// Compatibility frame used by recording and the legacy rectangle picker.
/// Screenshot capture itself uses the per-display freeze path below.
pub fn capture_fullscreen_rgba() -> Result<RgbaImage, String> {
    let scratch = std::env::temp_dir().join(format!(
        "wondershot-macos-frame-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_nanos()
    ));
    let displays = freeze_displays(&scratch, false);
    let result = displays.and_then(|displays| compose_displays(&displays));
    let _ = std::fs::remove_dir_all(&scratch);
    result
}

pub fn virtual_origin() -> (i32, i32) {
    let monitors = monitor_rects();
    (
        monitors.iter().map(|monitor| monitor.x).min().unwrap_or(0),
        monitors.iter().map(|monitor| monitor.y).min().unwrap_or(0),
    )
}

pub fn monitor_rects() -> Vec<MonitorRect> {
    let Ok(content) = SCShareableContent::get() else {
        return Vec::new();
    };
    content
        .displays()
        .into_iter()
        .filter_map(|display| {
            let frame = display.frame();
            if frame.size.width <= 0.0 || frame.size.height <= 0.0 {
                return None;
            }
            let scale_x = f64::from(display.width()) / frame.size.width;
            let scale_y = f64::from(display.height()) / frame.size.height;
            Some(MonitorRect {
                x: (frame.origin.x * scale_x).round() as i32,
                y: (frame.origin.y * scale_y).round() as i32,
                width: display.width(),
                height: display.height(),
            })
        })
        .collect()
}

pub fn window_rects() -> Vec<WindowRect> {
    let Ok(content) = SCShareableContent::get() else {
        return Vec::new();
    };
    let displays = content.displays();
    content
        .windows()
        .into_iter()
        .filter_map(|window| {
            if window.window_layer() != 0 || !window.is_on_screen() {
                return None;
            }
            let frame = window.frame();
            if frame.size.width < 2.0 || frame.size.height < 2.0 {
                return None;
            }
            let display = displays.iter().find(|display| {
                let display_frame = display.frame();
                rects_intersect(
                    display_frame.origin.x,
                    display_frame.origin.y,
                    display_frame.size.width,
                    display_frame.size.height,
                    frame.origin.x,
                    frame.origin.y,
                    frame.size.width,
                    frame.size.height,
                )
            })?;
            let display_frame = display.frame();
            let scale_x = f64::from(display.width()) / display_frame.size.width;
            let scale_y = f64::from(display.height()) / display_frame.size.height;
            Some(WindowRect {
                hwnd: window.window_id() as isize,
                title: window.title().unwrap_or_default(),
                x: (frame.origin.x * scale_x).round() as i32,
                y: (frame.origin.y * scale_y).round() as i32,
                width: (frame.size.width * scale_x).round().max(1.0) as u32,
                height: (frame.size.height * scale_y).round().max(1.0) as u32,
            })
        })
        .collect()
}

fn compose_displays(displays: &[FrozenDisplay]) -> Result<RgbaImage, String> {
    let min_x = displays.iter().map(|display| display.x).min().unwrap_or(0);
    let min_y = displays.iter().map(|display| display.y).min().unwrap_or(0);
    let max_x = displays
        .iter()
        .map(|display| i64::from(display.x) + i64::from(display.pixel_width))
        .max()
        .unwrap_or(0);
    let max_y = displays
        .iter()
        .map(|display| i64::from(display.y) + i64::from(display.pixel_height))
        .max()
        .unwrap_or(0);
    let width = u32::try_from(max_x - i64::from(min_x))
        .map_err(|_| "macOS virtual desktop width is invalid".to_string())?;
    let height = u32::try_from(max_y - i64::from(min_y))
        .map_err(|_| "macOS virtual desktop height is invalid".to_string())?;
    if width == 0 || height == 0 {
        return Err("macOS virtual desktop is empty".into());
    }
    let mut canvas = RgbaImage::new(width, height);
    for display in displays {
        let frame = image::open(&display.frame_path)
            .map_err(|e| format!("could not open frozen macOS display: {e}"))?
            .to_rgba8();
        imageops::overlay(
            &mut canvas,
            &frame,
            i64::from(display.x - min_x),
            i64::from(display.y - min_y),
        );
    }
    Ok(canvas)
}

/// Capture one still image with ScreenCaptureKit and write it directly as PNG.
pub fn capture_once(
    mode: CaptureMode,
    out: impl AsRef<Path>,
    cursor: bool,
) -> Result<&'static str, String> {
    match mode {
        CaptureMode::Region => {
            capture_picked_region(out.as_ref(), cursor)?;
            Ok(REGION_SELECTOR)
        }
        CaptureMode::Fullscreen => {
            capture_primary_display(out.as_ref(), cursor)?;
            Ok(SCREEN_CAPTURE_KIT)
        }
        CaptureMode::Window => {
            capture_picked_window(out.as_ref().to_path_buf(), cursor)?;
            Ok(SCREEN_CAPTURE_KIT)
        }
    }
}

fn capture_picked_region(out: &Path, cursor: bool) -> Result<(), String> {
    let mut command = std::process::Command::new("/usr/sbin/screencapture");
    command.args(["-i", "-s", "-x"]);
    if cursor {
        command.arg("-C");
    }
    let status = command
        .arg(out)
        .status()
        .map_err(|e| format!("could not start the macOS region selector: {e}"))?;
    if !status.success() || !out.is_file() {
        return Err("macOS region capture was cancelled or produced no image".into());
    }
    Ok(())
}

fn capture_primary_display(out: &Path, cursor: bool) -> Result<(), String> {
    let content = SCShareableContent::get()
        .map_err(|e| format!("Screen Recording permission or content enumeration failed: {e}"))?;
    let display = content
        .displays()
        .into_iter()
        .next()
        .ok_or_else(|| "ScreenCaptureKit reported no displays".to_string())?;
    let filter = SCContentFilter::create()
        .with_display(&display)
        .with_excluding_windows(&[])
        .build();
    save_filter(&filter, display.width(), display.height(), out, cursor)
}

/// Capture immutable frames for every display and take one shareable-window
/// snapshot for hit testing. Window bounds are converted from CoreGraphics
/// points into each display's frozen-frame pixel space, including mixed-DPI
/// arrangements.
pub fn freeze_displays(
    out_dir: impl AsRef<Path>,
    cursor: bool,
) -> Result<Vec<FrozenDisplay>, String> {
    std::fs::create_dir_all(out_dir.as_ref()).map_err(|e| e.to_string())?;
    let content = SCShareableContent::get()
        .map_err(|e| format!("Screen Recording permission or content enumeration failed: {e}"))?;
    let windows = content.windows();
    let mut displays = Vec::new();

    for display in content.displays() {
        let frame = display.frame();
        if frame.size.width <= 0.0 || frame.size.height <= 0.0 {
            continue;
        }
        let width = display.width();
        let height = display.height();
        let scale_x = f64::from(width) / frame.size.width;
        let scale_y = f64::from(height) / frame.size.height;
        let display_x = (frame.origin.x * scale_x).round() as i32;
        let display_y = (frame.origin.y * scale_y).round() as i32;
        let id = display.display_id().to_string();
        let out = out_dir.as_ref().join(format!("display-{id}.png"));
        let filter = SCContentFilter::create()
            .with_display(&display)
            .with_excluding_windows(&[])
            .build();
        save_filter(&filter, width, height, &out, cursor)?;

        let targets = windows
            .iter()
            .enumerate()
            .filter_map(|(z_order, window)| {
                if window.window_layer() != 0 || !window.is_on_screen() {
                    return None;
                }
                if window
                    .owning_application()
                    .is_some_and(|app| app.process_id() == std::process::id() as i32)
                {
                    return None;
                }
                let window_frame = window.frame();
                if !rects_intersect(
                    frame.origin.x,
                    frame.origin.y,
                    frame.size.width,
                    frame.size.height,
                    window_frame.origin.x,
                    window_frame.origin.y,
                    window_frame.size.width,
                    window_frame.size.height,
                ) {
                    return None;
                }
                let pixel_width = (window_frame.size.width * scale_x).round().max(0.0) as u32;
                let pixel_height = (window_frame.size.height * scale_y).round().max(0.0) as u32;
                if pixel_width < 2 || pixel_height < 2 {
                    return None;
                }
                Some(WindowTarget {
                    id: window.window_id().to_string(),
                    title: window.title().unwrap_or_default(),
                    application: window
                        .owning_application()
                        .map(|app| app.application_name())
                        .unwrap_or_default(),
                    x: display_x
                        + ((window_frame.origin.x - frame.origin.x) * scale_x).round() as i32,
                    y: display_y
                        + ((window_frame.origin.y - frame.origin.y) * scale_y).round() as i32,
                    width: pixel_width,
                    height: pixel_height,
                    z_order: z_order as u32,
                    capturable: true,
                })
            })
            .collect();
        displays.push(FrozenDisplay {
            id,
            frame_path: out,
            x: display_x,
            y: display_y,
            pixel_width: width,
            pixel_height: height,
            windows: targets,
        });
    }

    if displays.is_empty() {
        return Err("ScreenCaptureKit reported no displays".into());
    }
    Ok(displays)
}

pub fn capture_window_by_id(id: &str, out: impl AsRef<Path>, cursor: bool) -> Result<(), String> {
    let id = id
        .parse::<u32>()
        .map_err(|_| "invalid macOS window identifier".to_string())?;
    let content = SCShareableContent::get()
        .map_err(|e| format!("Screen Recording permission or content enumeration failed: {e}"))?;
    let window = content
        .windows()
        .into_iter()
        .find(|window| window.window_id() == id)
        .ok_or_else(|| "selected macOS window is no longer available".to_string())?;
    let frame = window.frame();
    let filter = SCContentFilter::create().with_window(&window).build();
    let scale = f64::from(filter.point_pixel_scale());
    let width = (frame.size.width * scale).round().max(1.0) as u32;
    let height = (frame.size.height * scale).round().max(1.0) as u32;
    save_filter(&filter, width, height, out.as_ref(), cursor)
}

#[allow(clippy::too_many_arguments)]
fn rects_intersect(ax: f64, ay: f64, aw: f64, ah: f64, bx: f64, by: f64, bw: f64, bh: f64) -> bool {
    ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by
}

fn capture_picked_window(out: PathBuf, cursor: bool) -> Result<(), String> {
    let (tx, rx) = mpsc::sync_channel(1);
    let mut config = SCContentSharingPickerConfiguration::default_from_system();
    config.set_allowed_picker_modes(&[SCContentSharingPickerMode::SingleWindow]);
    SCContentSharingPicker::show(&config, move |outcome| {
        let result = match outcome {
            SCPickerOutcome::Picked(picked) => {
                let (width, height) = picked.pixel_size();
                save_filter(&picked.filter(), width, height, &out, cursor)
            }
            SCPickerOutcome::Cancelled => Err("macOS capture picker cancelled".into()),
            SCPickerOutcome::Error(e) => Err(format!("macOS capture picker failed: {e}")),
        };
        let _ = tx.send(result);
    });
    rx.recv_timeout(Duration::from_secs(300))
        .map_err(|_| "macOS capture picker timed out".to_string())?
}

fn save_filter(
    filter: &SCContentFilter,
    width: u32,
    height: u32,
    out: &Path,
    cursor: bool,
) -> Result<(), String> {
    let config = SCStreamConfiguration::new()
        .with_width(width)
        .with_height(height)
        .with_shows_cursor(cursor);
    let image = SCScreenshotManager::capture_image(filter, &config)
        .map_err(|e| format!("ScreenCaptureKit screenshot failed: {e}"))?;
    let path = out
        .to_str()
        .ok_or_else(|| "capture output path is not valid UTF-8".to_string())?;
    image
        .save_png(path)
        .map_err(|e| format!("could not save ScreenCaptureKit PNG: {e}"))
}
