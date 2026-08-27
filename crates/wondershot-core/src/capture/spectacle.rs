use super::CaptureMode;

/// Build the Spectacle CLI args. `-i` keeps the capture in this process instead
/// of forwarding it to an existing DBus instance and returning before the
/// selected image has been written.
pub fn spectacle_args(mode: CaptureMode, out: &str, cursor: bool, delay_secs: u32) -> Vec<String> {
    let flag = match mode {
        CaptureMode::Region => "-r",
        CaptureMode::Fullscreen => "-f",
        CaptureMode::Window => "-a",
    };
    let mut args: Vec<String> = vec![
        "-i".into(),
        "-b".into(),
        "-n".into(),
        flag.into(),
        "-o".into(),
        out.into(),
    ];
    if cursor {
        args.insert(3, "-p".into());
    }
    if delay_secs > 0 {
        args.push("-d".into());
        args.push((delay_secs * 1000).to_string());
    }
    args
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::capture::CaptureMode;

    #[test]
    fn region_args_background_no_notify() {
        let a = spectacle_args(CaptureMode::Region, "/out.png", false, 0);
        assert_eq!(a, vec!["-i", "-b", "-n", "-r", "-o", "/out.png"]);
    }
    #[test]
    fn cursor_flag_is_forwarded() {
        let a = spectacle_args(CaptureMode::Fullscreen, "/o.png", true, 0);
        assert_eq!(a, vec!["-i", "-b", "-n", "-p", "-f", "-o", "/o.png"]);
    }
    #[test]
    fn delay_seconds_become_milliseconds_appended() {
        let a = spectacle_args(CaptureMode::Window, "/o.png", false, 2);
        assert_eq!(a, vec!["-i", "-b", "-n", "-a", "-o", "/o.png", "-d", "2000"]);
    }
}
