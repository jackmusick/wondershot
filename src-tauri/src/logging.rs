use std::io::Write;
use std::path::PathBuf;
use std::sync::Once;
use std::time::{SystemTime, UNIX_EPOCH};

use wondershot_core::settings::Settings;

static INIT: Once = Once::new();

pub fn init() {
    INIT.call_once(|| {
        std::panic::set_hook(Box::new(|info| {
            log(format!("panic: {info}"));
        }));
        log("logging initialized");
    });
}

pub fn log_path() -> PathBuf {
    Settings::conf_path()
        .parent()
        .map(|p| p.join("wondershot.log"))
        .unwrap_or_else(|| PathBuf::from("wondershot.log"))
}

pub fn log(message: impl AsRef<str>) {
    let path = log_path();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or_default();
    let thread = std::thread::current()
        .name()
        .map(str::to_string)
        .unwrap_or_else(|| format!("{:?}", std::thread::current().id()));
    let line = format!(
        "{now} pid={} thread={} {}\n",
        std::process::id(),
        thread,
        message.as_ref()
    );

    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = file.write_all(line.as_bytes());
    }
}
