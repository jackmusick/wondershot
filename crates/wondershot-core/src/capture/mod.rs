pub mod spectacle;
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
#[cfg(target_os = "macos")]
pub mod macos;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureMode {
    Region,
    Fullscreen,
    Window,
}
