use image::RgbaImage;
use std::ffi::{c_char, c_void};
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use super::native::{MonitorRect, NativeCaptureCapabilities, WindowRect};

type CFArrayRef = *const c_void;
type CFBooleanRef = *const c_void;
type CFDictionaryRef = *const c_void;
type CFIndex = isize;
type CFNumberRef = *const c_void;
type CFStringRef = *const c_void;

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
struct CGPoint {
    x: f64,
    y: f64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
struct CGSize {
    width: f64,
    height: f64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
struct CGRect {
    origin: CGPoint,
    size: CGSize,
}

#[link(name = "CoreGraphics", kind = "framework")]
unsafe extern "C" {
    fn CGPreflightScreenCaptureAccess() -> bool;
    fn CGRequestScreenCaptureAccess() -> bool;
    fn CGGetActiveDisplayList(
        max_displays: u32,
        active_displays: *mut u32,
        display_count: *mut u32,
    ) -> i32;
    fn CGDisplayBounds(display: u32) -> CGRect;
    fn CGWindowListCopyWindowInfo(option: u32, relative_to_window: u32) -> CFArrayRef;
    fn CGRectMakeWithDictionaryRepresentation(dict: CFDictionaryRef, rect: *mut CGRect) -> bool;

    static kCGWindowAlpha: CFStringRef;
    static kCGWindowBounds: CFStringRef;
    static kCGWindowIsOnscreen: CFStringRef;
    static kCGWindowLayer: CFStringRef;
    static kCGWindowName: CFStringRef;
    static kCGWindowNumber: CFStringRef;
    static kCGWindowOwnerName: CFStringRef;
}

#[link(name = "CoreFoundation", kind = "framework")]
unsafe extern "C" {
    fn CFArrayGetCount(array: CFArrayRef) -> CFIndex;
    fn CFArrayGetValueAtIndex(array: CFArrayRef, idx: CFIndex) -> *const c_void;
    fn CFBooleanGetValue(value: CFBooleanRef) -> bool;
    fn CFDictionaryGetValueIfPresent(
        dict: CFDictionaryRef,
        key: *const c_void,
        value: *mut *const c_void,
    ) -> bool;
    fn CFNumberGetValue(number: CFNumberRef, the_type: i32, value: *mut c_void) -> bool;
    fn CFRelease(value: *const c_void);
    fn CFStringGetCString(
        string: CFStringRef,
        buffer: *mut c_char,
        buffer_size: CFIndex,
        encoding: u32,
    ) -> bool;
    fn CFStringGetLength(string: CFStringRef) -> CFIndex;
    fn CFStringGetMaximumSizeForEncoding(length: CFIndex, encoding: u32) -> CFIndex;
}

pub fn capabilities() -> NativeCaptureCapabilities {
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

pub fn capture_fullscreen_rgba() -> Result<RgbaImage, String> {
    let path = temp_capture_path();
    let result = capture_fullscreen_to_temp(&path)
        .and_then(|_| {
            image::open(&path).map_err(|e| format!("could not read macOS screenshot: {e}"))
        })
        .map(|img| img.to_rgba8());
    let _ = std::fs::remove_file(&path);
    result
}

pub fn capture_window_to(path: &PathBuf, window_id: isize) -> Result<(), String> {
    if window_id <= 0 {
        return Err("invalid macOS window id".into());
    }
    let status = Command::new("/usr/sbin/screencapture")
        .arg("-x")
        .arg("-l")
        .arg(window_id.to_string())
        .arg(path)
        .status()
        .map_err(|e| format!("could not start macOS window capture: {e}"))?;
    if !status.success() {
        return Err(format!("macOS window capture failed with {status}"));
    }
    if !path.exists() {
        return Err("macOS window capture produced no output file".into());
    }
    Ok(())
}

pub fn monitor_rects() -> Vec<MonitorRect> {
    active_display_bounds()
        .into_iter()
        .map(|rect| MonitorRect {
            x: rect.origin.x.round() as i32,
            y: rect.origin.y.round() as i32,
            width: rect.size.width.max(0.0).round() as u32,
            height: rect.size.height.max(0.0).round() as u32,
        })
        .collect()
}

pub fn window_rects() -> Vec<WindowRect> {
    const KCG_WINDOW_LIST_OPTION_ON_SCREEN_ONLY: u32 = 1;
    const KCG_WINDOW_LIST_EXCLUDE_DESKTOP_ELEMENTS: u32 = 16;
    const KCG_NULL_WINDOW_ID: u32 = 0;

    unsafe {
        let info = CGWindowListCopyWindowInfo(
            KCG_WINDOW_LIST_OPTION_ON_SCREEN_ONLY | KCG_WINDOW_LIST_EXCLUDE_DESKTOP_ELEMENTS,
            KCG_NULL_WINDOW_ID,
        );
        if info.is_null() {
            return Vec::new();
        }

        let count = CFArrayGetCount(info);
        let mut windows = Vec::new();
        for i in 0..count {
            let dict = CFArrayGetValueAtIndex(info, i) as CFDictionaryRef;
            if dict.is_null() || !window_is_selectable(dict) {
                continue;
            }

            let Some(rect) = window_bounds(dict) else {
                continue;
            };
            let width = rect.size.width.max(0.0).round() as u32;
            let height = rect.size.height.max(0.0).round() as u32;
            if width < 16 || height < 16 {
                continue;
            }
            let Some(window_number) = cf_i32(dict, kCGWindowNumber) else {
                continue;
            };

            if is_own_window(dict) {
                continue;
            }

            let title = window_title(dict);
            if title.is_empty() {
                continue;
            }

            windows.push(WindowRect {
                hwnd: window_number as isize,
                title,
                x: rect.origin.x.round() as i32,
                y: rect.origin.y.round() as i32,
                width,
                height,
            });
        }
        CFRelease(info);
        windows
    }
}

pub fn virtual_origin() -> (i32, i32) {
    let (x, y, _, _) = virtual_bounds_from_displays();
    (x, y)
}

pub fn virtual_bounds() -> (i32, i32, u32, u32) {
    virtual_bounds_from_displays()
}

pub fn screen_capture_access_granted() -> bool {
    unsafe { CGPreflightScreenCaptureAccess() }
}

pub fn request_screen_capture_access() -> bool {
    unsafe { CGRequestScreenCaptureAccess() }
}

pub fn screen_capture_settings_url() -> &'static str {
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
}

pub fn open_screen_capture_settings() -> Result<(), String> {
    let status = Command::new("open")
        .arg(screen_capture_settings_url())
        .status()
        .map_err(|e| format!("could not open macOS Screen Recording settings: {e}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "open Screen Recording settings failed with {status}"
        ))
    }
}

fn temp_capture_path() -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    std::env::temp_dir().join(format!(
        "wondershot-capture-{}-{stamp}.png",
        std::process::id()
    ))
}

fn capture_fullscreen_to_temp(path: &PathBuf) -> Result<(), String> {
    capture_rect_to(path, virtual_bounds(), false)
}

pub fn capture_region_to(path: &PathBuf, rect: (u32, u32, u32, u32), cursor: bool) -> Result<(), String> {
    let (origin_x, origin_y) = virtual_origin();
    capture_rect_to(path, (origin_x + rect.0 as i32, origin_y + rect.1 as i32, rect.2, rect.3), cursor)
}

fn capture_rect_to(path: &PathBuf, rect: (i32, i32, u32, u32), cursor: bool) -> Result<(), String> {
    let (x, y, w, h) = rect;
    if w == 0 || h == 0 { return Err("capture region is empty".into()); }
    let mut command = Command::new("/usr/sbin/screencapture");
    command.arg("-x").arg(format!("-R{x},{y},{w},{h}"));
    if cursor { command.arg("-C"); }
    let mut child = command
        .arg(path)
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("could not start macOS screencapture: {e}"))?;

    let started = std::time::Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                if !status.success() {
                    let stderr = child_stderr(&mut child);
                    let detail = if stderr.is_empty() {
                        status.to_string()
                    } else {
                        format!("{status}: {stderr}")
                    };
                    return Err(format!(
                        "macOS screencapture failed with {detail}. Check System Settings > Privacy & Security > Screen Recording."
                    ));
                }
                if !path.exists() {
                    return Err("macOS screencapture produced no output file".into());
                }
                return Ok(());
            }
            Ok(None) => {
                if started.elapsed() > Duration::from_secs(15) {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(
                        "macOS screencapture timed out. Check Screen Recording permission for this app."
                            .into(),
                    );
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("could not wait for macOS screencapture: {e}"));
            }
        }
    }
}

fn active_display_bounds() -> Vec<CGRect> {
    const MAX_DISPLAYS: usize = 32;
    let mut displays = [0u32; MAX_DISPLAYS];
    let mut count = 0u32;
    unsafe {
        if CGGetActiveDisplayList(MAX_DISPLAYS as u32, displays.as_mut_ptr(), &mut count) != 0 {
            return Vec::new();
        }
        displays
            .iter()
            .take(count as usize)
            .map(|display| CGDisplayBounds(*display))
            .collect()
    }
}

fn virtual_bounds_from_displays() -> (i32, i32, u32, u32) {
    let displays = active_display_bounds();
    if displays.is_empty() {
        return (0, 0, 1920, 1080);
    }

    let min_x = displays
        .iter()
        .map(|r| r.origin.x)
        .fold(f64::INFINITY, f64::min);
    let min_y = displays
        .iter()
        .map(|r| r.origin.y)
        .fold(f64::INFINITY, f64::min);
    let max_x = displays
        .iter()
        .map(|r| r.origin.x + r.size.width)
        .fold(f64::NEG_INFINITY, f64::max);
    let max_y = displays
        .iter()
        .map(|r| r.origin.y + r.size.height)
        .fold(f64::NEG_INFINITY, f64::max);

    (
        min_x.round() as i32,
        min_y.round() as i32,
        (max_x - min_x).max(0.0).round() as u32,
        (max_y - min_y).max(0.0).round() as u32,
    )
}

unsafe fn window_is_selectable(dict: CFDictionaryRef) -> bool {
    let layer = cf_i32(dict, kCGWindowLayer).unwrap_or(0);
    if layer != 0 {
        return false;
    }

    let alpha = cf_f64(dict, kCGWindowAlpha).unwrap_or(1.0);
    if alpha <= 0.01 {
        return false;
    }

    cf_bool(dict, kCGWindowIsOnscreen).unwrap_or(true)
}

unsafe fn window_bounds(dict: CFDictionaryRef) -> Option<CGRect> {
    let value = cf_value(dict, kCGWindowBounds)?;
    let mut rect = CGRect::default();
    if CGRectMakeWithDictionaryRepresentation(value as CFDictionaryRef, &mut rect) {
        Some(rect)
    } else {
        None
    }
}

unsafe fn window_title(dict: CFDictionaryRef) -> String {
    let name = cf_string(dict, kCGWindowName).unwrap_or_default();
    if !name.trim().is_empty() {
        return name;
    }
    cf_string(dict, kCGWindowOwnerName).unwrap_or_default()
}

unsafe fn is_own_window(dict: CFDictionaryRef) -> bool {
    let owner = cf_string(dict, kCGWindowOwnerName)
        .unwrap_or_default()
        .to_lowercase();
    owner.contains("wondershot")
}

unsafe fn cf_value(dict: CFDictionaryRef, key: CFStringRef) -> Option<*const c_void> {
    let mut value = std::ptr::null();
    if CFDictionaryGetValueIfPresent(dict, key, &mut value) && !value.is_null() {
        Some(value)
    } else {
        None
    }
}

unsafe fn cf_i32(dict: CFDictionaryRef, key: CFStringRef) -> Option<i32> {
    let value = cf_value(dict, key)? as CFNumberRef;
    let mut out = 0i32;
    if CFNumberGetValue(value, 3, &mut out as *mut i32 as *mut c_void) {
        Some(out)
    } else {
        None
    }
}

unsafe fn cf_f64(dict: CFDictionaryRef, key: CFStringRef) -> Option<f64> {
    let value = cf_value(dict, key)? as CFNumberRef;
    let mut out = 0.0f64;
    if CFNumberGetValue(value, 13, &mut out as *mut f64 as *mut c_void) {
        Some(out)
    } else {
        None
    }
}

unsafe fn cf_bool(dict: CFDictionaryRef, key: CFStringRef) -> Option<bool> {
    Some(CFBooleanGetValue(cf_value(dict, key)? as CFBooleanRef))
}

unsafe fn cf_string(dict: CFDictionaryRef, key: CFStringRef) -> Option<String> {
    const K_CF_STRING_ENCODING_UTF8: u32 = 0x0800_0100;
    let value = cf_value(dict, key)? as CFStringRef;
    let len = CFStringGetLength(value);
    let max_len = CFStringGetMaximumSizeForEncoding(len, K_CF_STRING_ENCODING_UTF8) + 1;
    if max_len <= 1 {
        return Some(String::new());
    }
    let mut buffer = vec![0u8; max_len as usize];
    if !CFStringGetCString(
        value,
        buffer.as_mut_ptr() as *mut c_char,
        max_len,
        K_CF_STRING_ENCODING_UTF8,
    ) {
        return None;
    }
    let nul = buffer.iter().position(|b| *b == 0).unwrap_or(buffer.len());
    Some(String::from_utf8_lossy(&buffer[..nul]).trim().to_string())
}

fn child_stderr(child: &mut std::process::Child) -> String {
    let mut text = String::new();
    if let Some(mut stderr) = child.stderr.take() {
        let _ = stderr.read_to_string(&mut text);
    }
    text.trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capabilities_enable_shared_region_picker_only_for_supported_mvp() {
        let caps = capabilities();

        assert!(caps.fullscreen);
        assert!(caps.frame);
        assert!(caps.crop);
        assert!(caps.region_selector);
        assert!(caps.screen_selector);
        assert!(caps.window_selector);
        assert!(caps.monitors);
        assert!(caps.windows);
    }

    #[test]
    fn settings_url_targets_screen_recording_privacy_pane() {
        assert_eq!(
            screen_capture_settings_url(),
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
        );
    }
}
