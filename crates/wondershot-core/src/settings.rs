use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Settings {
    pub library_dir: String,
    pub backend: String,
    pub capture_cursor: bool,
    pub capture_delay: u32,
    pub extra_dirs: Vec<String>,
    pub mic_enabled: bool,
    pub mic_device: String,
    pub noise_suppression: bool,
    pub record_cursor_halo: bool,
    pub record_countdown: u32,
    pub camera_device: String,
}

impl Default for Settings {
    fn default() -> Self {
        let pictures = dirs::picture_dir()
            .unwrap_or_else(|| dirs::home_dir().unwrap_or_default().join("Pictures"));
        Settings {
            library_dir: pictures
                .join("Screenshots")
                .to_string_lossy()
                .to_string(),
            backend: "auto".into(),
            capture_cursor: false,
            capture_delay: 0,
            extra_dirs: Vec::new(),
            mic_enabled: true,
            mic_device: String::new(),
            noise_suppression: true,
            record_cursor_halo: false,
            record_countdown: 0,
            camera_device: String::new(),
        }
    }
}

impl Settings {
    pub fn conf_path() -> PathBuf {
        dirs::config_dir()
            .unwrap_or_default()
            .join("wondershot")
            .join("wondershot.conf")
    }

    pub fn load() -> Self {
        match std::fs::read_to_string(Self::conf_path()) {
            Ok(s) => Self::from_conf_str(&s),
            Err(_) => Self::default(),
        }
    }

    pub fn from_conf_str(conf: &str) -> Self {
        let mut s = Self::default();
        for line in conf.lines() {
            let line = line.trim();
            if line.starts_with('[') || !line.contains('=') {
                continue;
            }
            let (k, v) = line.split_once('=').unwrap();
            let (k, v) = (k.trim(), v.trim());
            match k {
                "library_dir" => s.library_dir = v.to_string(),
                "backend" => s.backend = v.to_string(),
                "capture_cursor" => s.capture_cursor = v == "true",
                "capture_delay" => s.capture_delay = v.parse().unwrap_or(0),
                "mic_enabled" => s.mic_enabled = v == "true",
                "mic_device" => s.mic_device = v.to_string(),
                "noise_suppression" => s.noise_suppression = v == "true",
                "record_cursor_halo" => s.record_cursor_halo = v == "true",
                "record_countdown" => s.record_countdown = v.parse().unwrap_or(0),
                "camera_device" => s.camera_device = v.to_string(),
                "extra_dirs" => {
                    s.extra_dirs = v
                        .split(';')
                        .filter(|x| !x.is_empty())
                        .map(String::from)
                        .collect()
                }
                _ => {}
            }
        }
        s
    }

    pub fn library_dirs(&self) -> Vec<PathBuf> {
        let mut v = vec![PathBuf::from(&self.library_dir)];
        v.extend(self.extra_dirs.iter().map(PathBuf::from));
        v
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_match_python() {
        let s = Settings::default();
        assert_eq!(s.backend, "auto");
        assert_eq!(s.capture_cursor, false);
        assert_eq!(s.capture_delay, 0);
        assert!(s.library_dir.ends_with("Screenshots"));
    }

    #[test]
    fn parse_conf_reads_known_keys() {
        let conf =
            "[General]\nlibrary_dir=/tmp/shots\nbackend=spectacle\ncapture_cursor=true\ncapture_delay=3\n";
        let s = Settings::from_conf_str(conf);
        assert_eq!(s.library_dir, "/tmp/shots");
        assert_eq!(s.backend, "spectacle");
        assert_eq!(s.capture_cursor, true);
        assert_eq!(s.capture_delay, 3);
    }

    #[test]
    fn extra_dirs_split_on_semicolon_ignoring_empties() {
        let s = Settings::from_conf_str("[General]\nextra_dirs=/a;/b;;/c\n");
        assert_eq!(s.extra_dirs, vec!["/a", "/b", "/c"]);
    }

    #[test]
    fn record_countdown_and_camera_device_parse_and_default() {
        let s = Settings::default();
        assert_eq!(s.record_countdown, 0);
        assert_eq!(s.camera_device, "");

        let conf = "[General]\nrecord_countdown=5\ncamera_device=/dev/video0\n";
        let s = Settings::from_conf_str(conf);
        assert_eq!(s.record_countdown, 5);
        assert_eq!(s.camera_device, "/dev/video0");
    }
}
