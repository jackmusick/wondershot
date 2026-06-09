use std::path::PathBuf;

/// Take a screenshot via xdg-desktop-portal; returns the file path it wrote.
/// interactive=false only for fullscreen (matches capture.py:_portal).
pub async fn screenshot(interactive: bool) -> Option<PathBuf> {
    use ashpd::desktop::screenshot::Screenshot;
    let resp = Screenshot::request()
        .interactive(interactive)
        .send()
        .await
        .ok()?
        .response()
        .ok()?;
    resp.uri().to_file_path().ok()
}
