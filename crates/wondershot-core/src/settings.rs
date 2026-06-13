use std::collections::BTreeMap;
use std::path::PathBuf;

fn default_hotkey_capture() -> String {
    #[cfg(target_os = "windows")]
    {
        "Ctrl+Shift+S".into()
    }
    #[cfg(not(target_os = "windows"))]
    {
        "Ctrl+Shift+Print".into()
    }
}

#[derive(Debug, Clone, PartialEq)]
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
    pub hotkey_capture: String,
    pub copy_after_capture: bool,
    pub show_gallery_after_capture: bool,
    pub pin_on_top: bool,
    pub quick_bar_enabled: bool,
    pub quick_bar_timeout: u32,
    pub stroke_width: u32,
    pub font_size: u32,
    pub tool_color: String,
    pub video_blur_strength: u32,
    pub gif_fps: u32,
    pub gif_max_width: u32,
    pub effect_rounded: bool,
    pub effect_corner_radius: u32,
    pub effect_fade: bool,
    pub effect_fade_height: u32,
    /// Conf keys the Rust app doesn't model (sharing creds, AI endpoint, …).
    /// Preserved verbatim across load→save so the shared wondershot.conf (also
    /// read by the Python app) is never clobbered. Quotes are re-added on write.
    pub extra: BTreeMap<String, String>,
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
            hotkey_capture: default_hotkey_capture(),
            copy_after_capture: true,
            show_gallery_after_capture: true,
            pin_on_top: false,
            quick_bar_enabled: true,
            quick_bar_timeout: 8,
            stroke_width: 10,
            font_size: 24,
            tool_color: "#e3242b".into(),
            video_blur_strength: 30,
            gif_fps: 12,
            gif_max_width: 720,
            effect_rounded: false,
            effect_corner_radius: 16,
            effect_fade: false,
            effect_fade_height: 96,
            extra: BTreeMap::new(),
        }
    }
}

impl Settings {
    pub fn conf_path() -> PathBuf {
        // In a Flatpak, XDG_CONFIG_HOME is sandboxed to ~/.var/app/<id>/config,
        // which hides the user's real ~/.config/wondershot/wondershot.conf shared
        // with the non-Flatpak (pip/AppImage) install. With the manifest's
        // --filesystem=xdg-config/wondershot grant, read the host config directly
        // so settings (library dir, backend, camera/mic, …) carry over on cutover.
        if std::env::var_os("FLATPAK_ID").is_some() {
            if let Some(home) = dirs::home_dir() {
                return home
                    .join(".config")
                    .join("wondershot")
                    .join("wondershot.conf");
            }
        }
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
            // QSettings INI quotes values containing ; or special chars
            // (e.g. extra_dirs="a;b", azure_key="…=="). Strip one matched pair.
            let k = k.trim();
            let v = v.trim();
            let v = if v.len() >= 2 && v.starts_with('"') && v.ends_with('"') {
                &v[1..v.len() - 1]
            } else {
                v
            };
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
                "hotkey_capture" => s.hotkey_capture = v.to_string(),
                "copy_after_capture" => s.copy_after_capture = v == "true",
                "show_gallery_after_capture" => s.show_gallery_after_capture = v == "true",
                "pin_on_top" => s.pin_on_top = v == "true",
                "quick_bar_enabled" => s.quick_bar_enabled = v == "true",
                "quick_bar_timeout" => s.quick_bar_timeout = v.parse().unwrap_or(8),
                "stroke_width" => s.stroke_width = v.parse().unwrap_or(10),
                "font_size" => s.font_size = v.parse().unwrap_or(24),
                "tool_color" => s.tool_color = v.to_string(),
                "video_blur_strength" => s.video_blur_strength = v.parse().unwrap_or(30),
                "gif_fps" => s.gif_fps = v.parse().unwrap_or(12),
                "gif_max_width" => s.gif_max_width = v.parse().unwrap_or(720),
                "effect_rounded" => s.effect_rounded = v == "true",
                "effect_corner_radius" => s.effect_corner_radius = v.parse().unwrap_or(16),
                "effect_fade" => s.effect_fade = v == "true",
                "effect_fade_height" => s.effect_fade_height = v.parse().unwrap_or(96),
                "extra_dirs" => {
                    s.extra_dirs = v
                        .split(';')
                        .filter(|x| !x.is_empty())
                        .map(String::from)
                        .collect()
                }
                // Preserve everything else (sharing creds, AI endpoint, …) so a
                // save round-trips them back into the shared conf.
                _ => {
                    s.extra.insert(k.to_string(), v.to_string());
                }
            }
        }
        #[cfg(target_os = "windows")]
        if s.hotkey_capture == "Ctrl+Shift+Print" {
            // Windows 11 commonly reserves Print Screen for Snipping Tool,
            // which makes RegisterHotKey fail. Migrate the old cross-platform
            // default to a Windows-friendly native shortcut.
            s.hotkey_capture = default_hotkey_capture();
        }
        s
    }

    /// Serialize all keys back to the QSettings INI format (`[General]` header
    /// then `key=value` lines). Round-trips with `from_conf_str`.
    pub fn to_conf_str(&self) -> String {
        let b = |x: bool| if x { "true" } else { "false" };
        // QSettings INI quotes values containing ; or special chars; mirror that
        // so the Python app (sharing the file) reads them back correctly.
        let q = |v: &str| -> String {
            if v.contains(';') || v.contains(',') || v.starts_with(' ') || v.ends_with(' ') {
                format!("\"{}\"", v.replace('"', "\\\""))
            } else {
                v.to_string()
            }
        };
        let mut out = String::from("[General]\n");
        out.push_str(&format!("library_dir={}\n", self.library_dir));
        out.push_str(&format!("backend={}\n", self.backend));
        out.push_str(&format!("capture_cursor={}\n", b(self.capture_cursor)));
        out.push_str(&format!("capture_delay={}\n", self.capture_delay));
        out.push_str(&format!("extra_dirs={}\n", q(&self.extra_dirs.join(";"))));
        out.push_str(&format!("mic_enabled={}\n", b(self.mic_enabled)));
        out.push_str(&format!("mic_device={}\n", self.mic_device));
        out.push_str(&format!("noise_suppression={}\n", b(self.noise_suppression)));
        out.push_str(&format!("record_cursor_halo={}\n", b(self.record_cursor_halo)));
        out.push_str(&format!("record_countdown={}\n", self.record_countdown));
        out.push_str(&format!("camera_device={}\n", self.camera_device));
        out.push_str(&format!("hotkey_capture={}\n", self.hotkey_capture));
        out.push_str(&format!("copy_after_capture={}\n", b(self.copy_after_capture)));
        out.push_str(&format!(
            "show_gallery_after_capture={}\n",
            b(self.show_gallery_after_capture)
        ));
        out.push_str(&format!("pin_on_top={}\n", b(self.pin_on_top)));
        out.push_str(&format!("quick_bar_enabled={}\n", b(self.quick_bar_enabled)));
        out.push_str(&format!("quick_bar_timeout={}\n", self.quick_bar_timeout));
        out.push_str(&format!("stroke_width={}\n", self.stroke_width));
        out.push_str(&format!("font_size={}\n", self.font_size));
        out.push_str(&format!("tool_color={}\n", self.tool_color));
        out.push_str(&format!("video_blur_strength={}\n", self.video_blur_strength));
        out.push_str(&format!("gif_fps={}\n", self.gif_fps));
        out.push_str(&format!("gif_max_width={}\n", self.gif_max_width));
        out.push_str(&format!("effect_rounded={}\n", b(self.effect_rounded)));
        out.push_str(&format!("effect_corner_radius={}\n", self.effect_corner_radius));
        out.push_str(&format!("effect_fade={}\n", b(self.effect_fade)));
        out.push_str(&format!("effect_fade_height={}\n", self.effect_fade_height));
        // Preserved unmodeled keys (sharing creds, AI endpoint, …), sorted.
        for (k, v) in &self.extra {
            out.push_str(&format!("{}={}\n", k, q(v)));
        }
        out
    }

    /// Create the conf dir and write `to_conf_str()` to `conf_path()`.
    pub fn save(&self) -> std::io::Result<()> {
        let path = Self::conf_path();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&path, self.to_conf_str())
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
    fn preserves_unmodeled_keys_and_quotes() {
        // The shared conf has sharing/AI keys the Rust app doesn't model + a
        // quoted extra_dirs. A load→save round-trip must keep them all.
        let conf = "[General]\nlibrary_dir=/home/jack/Sync/Screenshots\n\
            extra_dirs=\"/home/jack/Videos;/home/jack/Videos/Screencasts\"\n\
            ai_endpoint=https://openrouter.ai/api\nshare_provider=onedrive\n\
            azure_key=\"abc+def==\"\n";
        let s = Settings::from_conf_str(conf);
        assert_eq!(s.library_dir, "/home/jack/Sync/Screenshots");
        assert_eq!(s.extra_dirs, vec!["/home/jack/Videos", "/home/jack/Videos/Screencasts"]);
        assert_eq!(s.extra.get("ai_endpoint").unwrap(), "https://openrouter.ai/api");
        assert_eq!(s.extra.get("azure_key").unwrap(), "abc+def==");
        let out = s.to_conf_str();
        assert!(out.contains("ai_endpoint=https://openrouter.ai/api"));
        assert!(out.contains("share_provider=onedrive"));
        assert!(out.contains("azure_key=abc+def==")); // no ; so unquoted is fine
        assert!(out.contains("extra_dirs=\"/home/jack/Videos;/home/jack/Videos/Screencasts\""));
        // Idempotent: re-parsing the output yields the same settings.
        assert_eq!(Settings::from_conf_str(&out), s);
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

    #[test]
    fn new_keys_parse_and_default() {
        let s = Settings::default();
        #[cfg(target_os = "windows")]
        assert_eq!(s.hotkey_capture, "Ctrl+Shift+S");
        #[cfg(not(target_os = "windows"))]
        assert_eq!(s.hotkey_capture, "Ctrl+Shift+Print");
        assert_eq!(s.copy_after_capture, true);
        assert_eq!(s.show_gallery_after_capture, true);
        assert_eq!(s.pin_on_top, false);
        assert_eq!(s.quick_bar_enabled, true);
        assert_eq!(s.quick_bar_timeout, 8);
        assert_eq!(s.stroke_width, 10);
        assert_eq!(s.font_size, 24);
        assert_eq!(s.tool_color, "#e3242b");
        assert_eq!(s.video_blur_strength, 30);
        assert_eq!(s.gif_fps, 12);
        assert_eq!(s.gif_max_width, 720);
        assert_eq!(s.effect_corner_radius, 16);
        assert_eq!(s.effect_fade_height, 96);
    }

    #[test]
    fn to_conf_str_from_conf_str_round_trip() {
        let s = Settings {
            library_dir: "/tmp/shots".into(),
            backend: "spectacle".into(),
            capture_cursor: true,
            capture_delay: 3,
            extra_dirs: vec!["/a".into(), "/b".into()],
            mic_enabled: false,
            mic_device: "mic-x".into(),
            noise_suppression: false,
            record_cursor_halo: true,
            record_countdown: 5,
            camera_device: "/dev/video0".into(),
            hotkey_capture: "Ctrl+Alt+P".into(),
            copy_after_capture: false,
            show_gallery_after_capture: false,
            pin_on_top: true,
            quick_bar_enabled: false,
            quick_bar_timeout: 30,
            stroke_width: 5,
            font_size: 40,
            tool_color: "#00ff00".into(),
            video_blur_strength: 22,
            gif_fps: 24,
            gif_max_width: 1080,
            effect_rounded: true,
            effect_corner_radius: 32,
            effect_fade: true,
            effect_fade_height: 200,
            extra: BTreeMap::new(),
        };
        let round = Settings::from_conf_str(&s.to_conf_str());
        assert_eq!(s, round);
    }

    #[test]
    fn save_writes_a_file() {
        let dir = std::env::temp_dir().join(format!("wondershot-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("wondershot.conf");
        let s = Settings::default();
        std::fs::write(&path, s.to_conf_str()).unwrap();
        let read = std::fs::read_to_string(&path).unwrap();
        assert_eq!(Settings::from_conf_str(&read), s);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
