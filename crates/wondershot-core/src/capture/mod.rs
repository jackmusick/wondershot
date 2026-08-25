#[cfg(target_os = "linux")]
pub mod kwin;
pub mod native;
#[cfg(target_os = "linux")]
pub mod portal;
#[cfg(not(target_os = "linux"))]
pub mod portal {
    use std::path::PathBuf;

    pub async fn screenshot(_interactive: bool) -> Option<PathBuf> {
        None
    }
}
#[cfg(target_os = "windows")]
pub mod win;
#[cfg(target_os = "windows")]
pub mod windows;
#[cfg(target_os = "macos")]
pub mod macos;
pub mod spectacle;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureMode {
    Region,
    Fullscreen,
    Window,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq, Eq)]
pub struct WindowTarget {
    pub id: String,
    pub title: String,
    pub application: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub z_order: u32,
    pub capturable: bool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq, Eq)]
pub struct FrozenDisplay {
    pub id: String,
    pub frame_path: std::path::PathBuf,
    pub x: i32,
    pub y: i32,
    pub pixel_width: u32,
    pub pixel_height: u32,
    pub windows: Vec<WindowTarget>,
}
