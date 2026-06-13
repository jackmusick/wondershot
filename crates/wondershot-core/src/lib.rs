pub mod paths;
pub mod settings;
pub mod sidecar;
pub mod library;
pub mod clipboard;
pub mod capture;
pub mod editor;
pub mod imageops;
pub mod bgremove;
pub mod record;
pub mod ffmpeg;
pub mod opener;
#[cfg(target_os = "linux")]
pub mod camera;
#[cfg(target_os = "windows")]
#[path = "camera_win.rs"]
pub mod camera;
#[cfg(target_os = "macos")]
#[path = "camera_macos.rs"]
pub mod camera;
#[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
pub mod camera {
    pub struct CameraStream;

    pub fn open(_label: &str) -> Result<CameraStream, String> {
        Err("camera bubble is not available on this platform yet".into())
    }

    pub fn open_with_retry(_label: &str, _attempts: u32, _delay_ms: u64) -> Result<CameraStream, String> {
        Err("camera bubble is not available on this platform yet".into())
    }

    impl CameraStream {
        pub fn next_jpeg(&self) -> Option<Vec<u8>> { None }
        pub fn next_jpeg_timeout(&self, _timeout_ms: u64) -> Option<Vec<u8>> { None }
    }
}
pub mod video;
pub mod cli;
