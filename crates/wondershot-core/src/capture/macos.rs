use image::RgbaImage;

use super::native::{MonitorRect, NativeCaptureCapabilities, WindowRect};

pub fn capabilities() -> NativeCaptureCapabilities {
    NativeCaptureCapabilities::unavailable()
}

pub fn capture_fullscreen_rgba() -> Result<RgbaImage, String> {
    Err("native macOS capture is not implemented yet".into())
}

pub fn monitor_rects() -> Vec<MonitorRect> {
    Vec::new()
}

pub fn window_rects() -> Vec<WindowRect> {
    Vec::new()
}

pub fn virtual_origin() -> (i32, i32) {
    (0, 0)
}
