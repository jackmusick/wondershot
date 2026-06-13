#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OpenPlatform {
    Windows,
    Macos,
    Linux,
    Other,
}

impl OpenPlatform {
    pub fn current() -> Self {
        if cfg!(target_os = "windows") {
            Self::Windows
        } else if cfg!(target_os = "macos") {
            Self::Macos
        } else if cfg!(target_os = "linux") {
            Self::Linux
        } else {
            Self::Other
        }
    }
}

pub fn open_command(
    platform: OpenPlatform,
    in_flatpak: bool,
    target: &str,
) -> Result<(&'static str, Vec<String>), String> {
    match platform {
        OpenPlatform::Windows => {
            Ok(("rundll32.exe", vec!["url.dll,FileProtocolHandler".into(), target.into()]))
        }
        OpenPlatform::Macos => Ok(("open", vec![target.into()])),
        OpenPlatform::Linux if in_flatpak => {
            Ok(("flatpak-spawn", vec!["--host".into(), "xdg-open".into(), target.into()]))
        }
        OpenPlatform::Linux => Ok(("xdg-open", vec![target.into()])),
        OpenPlatform::Other => Err("open is not available on this platform".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_uses_shell_file_protocol_handler() {
        let (program, args) = open_command(OpenPlatform::Windows, false, "https://example.test").unwrap();
        assert_eq!(program, "rundll32.exe");
        assert_eq!(args, vec!["url.dll,FileProtocolHandler", "https://example.test"]);
    }

    #[test]
    fn macos_uses_open() {
        let (program, args) = open_command(OpenPlatform::Macos, false, "/tmp/file.png").unwrap();
        assert_eq!(program, "open");
        assert_eq!(args, vec!["/tmp/file.png"]);
    }

    #[test]
    fn linux_uses_host_xdg_open_inside_flatpak() {
        let (program, args) = open_command(OpenPlatform::Linux, true, "/tmp/file.png").unwrap();
        assert_eq!(program, "flatpak-spawn");
        assert_eq!(args, vec!["--host", "xdg-open", "/tmp/file.png"]);
    }

    #[test]
    fn linux_uses_xdg_open_outside_flatpak() {
        let (program, args) = open_command(OpenPlatform::Linux, false, "/tmp/file.png").unwrap();
        assert_eq!(program, "xdg-open");
        assert_eq!(args, vec!["/tmp/file.png"]);
    }
}
