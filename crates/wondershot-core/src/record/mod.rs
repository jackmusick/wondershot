//! In-process screen-recorder support (pure helpers ported from `record.py`).

pub mod clock;
pub mod files;
pub mod pipeline;
#[cfg(target_os = "linux")]
pub mod portal;
#[cfg(target_os = "linux")]
pub mod recorder;
#[cfg(target_os = "windows")]
#[path = "recorder_win.rs"]
pub mod recorder;
#[cfg(target_os = "macos")]
#[path = "recorder_macos.rs"]
pub mod recorder;

#[cfg(not(target_os = "linux"))]
pub mod portal {
    pub type CastSession = ();

    pub async fn close_session(_session: &CastSession) {}

    pub async fn open_screencast() -> Result<((), u32, CastSession), String> {
        Err("screen recording is not available on this platform yet".into())
    }
}

#[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
pub mod recorder {
    use std::path::PathBuf;

    #[derive(Debug, Clone)]
    pub enum RecEvent {
        Started,
        Stopping,
        Finished(PathBuf),
        Failed(String),
        Tick(String),
        PausedChanged(bool),
    }

    pub struct Recorder;

    impl Recorder {
        pub fn launch(
            _description: &str,
            _tmp: PathBuf,
            _out: PathBuf,
            _on_event: impl Fn(RecEvent) + Send + Sync + 'static,
        ) -> Result<Self, String> {
            Err("screen recording is not available on this platform yet".into())
        }

        pub fn pause(&self) {}
        pub fn resume(&self) {}
        pub fn stop(self) {}
        pub fn supports_pause() -> bool { false }
    }

    pub fn resolve_mic_source(_description: &str) -> String {
        String::new()
    }

    pub fn have_gst_element(_name: &str) -> bool {
        false
    }

    pub fn mic_probe(_source: &str) -> Result<f64, String> {
        Err("microphone probing is not available on this platform yet".into())
    }

    pub fn list_capture_devices() -> Vec<(String, String)> {
        Vec::new()
    }
}
