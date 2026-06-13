use std::path::Path;

use image::RgbaImage;

use super::CaptureMode;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeCaptureCapabilities {
    pub fullscreen: bool,
    pub frame: bool,
    pub crop: bool,
    pub region_selector: bool,
    pub screen_selector: bool,
    pub window_selector: bool,
    pub monitors: bool,
    pub windows: bool,
}

impl NativeCaptureCapabilities {
    pub const fn unavailable() -> Self {
        Self {
            fullscreen: false,
            frame: false,
            crop: false,
            region_selector: false,
            screen_selector: false,
            window_selector: false,
            monitors: false,
            windows: false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MonitorRect {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowRect {
    pub hwnd: isize,
    pub title: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

pub fn capabilities() -> NativeCaptureCapabilities {
    #[cfg(target_os = "windows")]
    {
        return NativeCaptureCapabilities {
            fullscreen: true,
            frame: true,
            crop: true,
            region_selector: true,
            screen_selector: true,
            window_selector: true,
            monitors: true,
            windows: true,
        };
    }

    #[cfg(target_os = "macos")]
    {
        return super::macos::capabilities();
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        NativeCaptureCapabilities::unavailable()
    }
}

pub fn handles_capture() -> bool {
    capabilities().fullscreen
}

pub fn capture_to(path: &Path, mode: CaptureMode, capture_cursor: bool) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        return match mode {
            CaptureMode::Fullscreen => super::win::capture_fullscreen_to(path, capture_cursor),
            CaptureMode::Region | CaptureMode::Window => {
                Err("interactive native picker required for this capture mode".into())
            }
        };
    }

    #[cfg(target_os = "macos")]
    {
        let _ = (mode, capture_cursor);
        let img = super::macos::capture_fullscreen_rgba()?;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        return img.save(path).map_err(|e| e.to_string());
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = (path, mode, capture_cursor);
        Err("native capture is not available on this platform".into())
    }
}

pub fn capture_rgba() -> Result<RgbaImage, String> {
    #[cfg(target_os = "windows")]
    {
        return super::win::capture_fullscreen_rgba();
    }

    #[cfg(target_os = "macos")]
    {
        return super::macos::capture_fullscreen_rgba();
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        Err("native frame capture is not available on this platform".into())
    }
}

pub fn capture_rgba_with_cursor(capture_cursor: bool) -> Result<RgbaImage, String> {
    #[cfg(target_os = "windows")]
    {
        return super::win::capture_fullscreen_rgba_with_cursor(capture_cursor);
    }

    #[cfg(target_os = "macos")]
    {
        let _ = capture_cursor;
        return super::macos::capture_fullscreen_rgba();
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = capture_cursor;
        Err("native frame capture is not available on this platform".into())
    }
}

pub fn virtual_origin() -> (i32, i32) {
    #[cfg(target_os = "windows")]
    {
        return super::win::virtual_screen().map(|s| (s.x, s.y)).unwrap_or((0, 0));
    }

    #[cfg(target_os = "macos")]
    {
        return super::macos::virtual_origin();
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        (0, 0)
    }
}

pub fn virtual_bounds() -> (i32, i32, u32, u32) {
    #[cfg(target_os = "windows")]
    {
        return super::win::virtual_screen()
            .map(|s| (s.x, s.y, s.width, s.height))
            .unwrap_or((0, 0, 1920, 1080));
    }

    #[cfg(target_os = "macos")]
    {
        let (x, y) = super::macos::virtual_origin();
        let img = super::macos::capture_fullscreen_rgba();
        return img.map(|i| (x, y, i.width(), i.height())).unwrap_or((0, 0, 1920, 1080));
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        (0, 0, 1920, 1080)
    }
}

pub fn monitor_rects() -> Vec<MonitorRect> {
    #[cfg(target_os = "windows")]
    {
        return super::win::list_monitors()
            .into_iter()
            .map(|m| MonitorRect { x: m.x, y: m.y, width: m.width, height: m.height })
            .collect();
    }

    #[cfg(target_os = "macos")]
    {
        return super::macos::monitor_rects();
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        Vec::new()
    }
}

pub fn window_rects() -> Vec<WindowRect> {
    #[cfg(target_os = "windows")]
    {
        return super::win::list_windows()
            .into_iter()
            .map(|w| WindowRect {
                hwnd: w.hwnd,
                title: w.title,
                x: w.x,
                y: w.y,
                width: w.width,
                height: w.height,
            })
            .collect();
    }

    #[cfg(target_os = "macos")]
    {
        return super::macos::window_rects();
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        Vec::new()
    }
}
