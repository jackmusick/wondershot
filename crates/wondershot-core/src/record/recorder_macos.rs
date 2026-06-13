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
        Err("native macOS screen recording is not implemented yet".into())
    }

    pub fn pause(&self) {}

    pub fn resume(&self) {}

    pub fn stop(self) {}

    pub fn supports_pause() -> bool {
        false
    }
}

pub fn resolve_mic_source(description: &str) -> String {
    description.to_string()
}

pub fn have_gst_element(_name: &str) -> bool {
    false
}

pub fn mic_probe(_source: &str) -> Result<f64, String> {
    Err("microphone probing is not available on macOS yet".into())
}

pub fn list_capture_devices() -> Vec<(String, String)> {
    Vec::new()
}
