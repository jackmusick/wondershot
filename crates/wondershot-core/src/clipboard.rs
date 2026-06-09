use std::io::Write;

pub fn should_use_wl_copy(wayland_display: Option<&str>, wl_copy_present: bool) -> bool {
    wayland_display.map_or(false, |d| !d.is_empty()) && wl_copy_present
}

pub fn wl_copy_args() -> [&'static str; 2] {
    ["--type", "image/png"]
}

fn wl_copy_on_path() -> bool {
    which("wl-copy")
}

fn which(bin: &str) -> bool {
    std::env::var_os("PATH").map_or(false, |paths| {
        std::env::split_paths(&paths).any(|p| p.join(bin).is_file())
    })
}

/// Put PNG bytes on the clipboard via wl-copy (Wayland, focus-independent).
/// Returns Ok(false) when not on Wayland (caller falls back to native clipboard);
/// Ok(true) when wl-copy accepted the bytes.
pub fn copy_png(png: &[u8]) -> std::io::Result<bool> {
    let wayland = std::env::var("WAYLAND_DISPLAY").ok();
    if !should_use_wl_copy(wayland.as_deref(), wl_copy_on_path()) {
        return Ok(false);
    }
    let mut child = std::process::Command::new("wl-copy")
        .args(wl_copy_args())
        .stdin(std::process::Stdio::piped())
        .spawn()?;
    let mut stdin = child.stdin.take().expect("piped stdin");
    stdin.write_all(png)?;
    drop(stdin); // close the pipe so wl-copy sees EOF and exits (else wait() deadlocks)
    let status = child.wait()?;
    Ok(status.success())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wayland_decision_needs_display_and_wl_copy() {
        assert!(should_use_wl_copy(Some("wayland-0"), true));
        assert!(!should_use_wl_copy(None, true));
        assert!(!should_use_wl_copy(Some("wayland-0"), false));
        assert!(!should_use_wl_copy(Some(""), true));
    }

    #[test]
    fn wl_copy_args_request_png_mime() {
        assert_eq!(wl_copy_args(), ["--type", "image/png"]);
    }
}
