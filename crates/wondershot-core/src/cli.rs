//! Pure parser for Wondershot's tiny CLI surface (parity with `wondershot/cli.py`).
//! Used both for the launch process args and for the single-instance *forwarded*
//! args of a second invocation. `argv` here EXCLUDES argv0.

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CliAction {
    Launch,
    Capture,
    Fullscreen,
    Edit(String),
    Import(Vec<String>),
    Quit,
    InstallDesktop,
    Version,
    SelfCheck,
    MediaCheck,
    OpenUrl(String),
}

/// Parse already-argv0-stripped args. First recognized intent wins; unknown
/// flags fall back to `Launch` (lenient, matching the desktop-launch case).
pub fn parse_args<I: IntoIterator<Item = String>>(args: I) -> CliAction {
    let args: Vec<String> = args.into_iter().collect();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "-c" | "--capture" => return CliAction::Capture,
            "-f" | "--fullscreen" => return CliAction::Fullscreen,
            "--quit" => return CliAction::Quit,
            "--install-desktop" => return CliAction::InstallDesktop,
            "--version" => return CliAction::Version,
            "--self-check" => return CliAction::SelfCheck,
            "--media-check" => return CliAction::MediaCheck,
            "-e" | "--edit" => {
                return match args.get(i + 1) {
                    Some(p) => CliAction::Edit(p.clone()),
                    None => CliAction::Launch,
                };
            }
            "-i" | "--import" => {
                let rest: Vec<String> = args[i + 1..].to_vec();
                return if rest.is_empty() {
                    CliAction::Launch
                } else {
                    CliAction::Import(rest)
                };
            }
            s if s.starts_with("wondershot://") => return CliAction::OpenUrl(s.to_string()),
            _ => {}
        }
        i += 1;
    }
    CliAction::Launch
}

#[cfg(test)]
mod tests {
    use super::*;
    fn p(args: &[&str]) -> CliAction {
        parse_args(args.iter().map(|s| s.to_string()))
    }
    #[test]
    fn no_args_launches() {
        assert_eq!(p(&[]), CliAction::Launch);
    }
    #[test]
    fn capture_flag() {
        assert_eq!(p(&["--capture"]), CliAction::Capture);
    }
    #[test]
    fn capture_short() {
        assert_eq!(p(&["-c"]), CliAction::Capture);
    }
    #[test]
    fn fullscreen() {
        assert_eq!(p(&["-f"]), CliAction::Fullscreen);
    }
    #[test]
    fn edit_takes_path() {
        assert_eq!(p(&["--edit", "/a/b.png"]), CliAction::Edit("/a/b.png".into()));
    }
    #[test]
    fn import_takes_many() {
        assert_eq!(
            p(&["-i", "/a.png", "/b.png"]),
            CliAction::Import(vec!["/a.png".into(), "/b.png".into()])
        );
    }
    #[test]
    fn quit_flag() {
        assert_eq!(p(&["--quit"]), CliAction::Quit);
    }
    #[test]
    fn install_desktop() {
        assert_eq!(p(&["--install-desktop"]), CliAction::InstallDesktop);
    }
    #[test]
    fn version_flag() {
        assert_eq!(p(&["--version"]), CliAction::Version);
    }
    #[test]
    fn self_check_flag() {
        assert_eq!(p(&["--self-check"]), CliAction::SelfCheck);
    }
    #[test]
    fn url_positional() {
        assert_eq!(
            p(&["wondershot://open?x=1"]),
            CliAction::OpenUrl("wondershot://open?x=1".into())
        );
    }
    #[test]
    fn unknown_flag_launches() {
        assert_eq!(p(&["--unknown"]), CliAction::Launch);
    }
}
