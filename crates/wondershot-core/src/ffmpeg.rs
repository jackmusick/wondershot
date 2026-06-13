use std::path::{Path, PathBuf};

pub fn find_ffmpeg() -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("WONDERSHOT_FFMPEG").map(PathBuf::from) {
        if path.is_file() {
            return Ok(path);
        }
    }

    #[cfg(target_os = "windows")]
    {
        let mut candidates = Vec::new();
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                candidates.extend([
                    dir.join("ffmpeg.exe"),
                    dir.join("ffmpeg-x86_64-pc-windows-gnu.exe"),
                    dir.join("ffmpeg-x86_64-pc-windows-msvc.exe"),
                ]);
                if let Some(parent) = dir.parent() {
                    candidates.extend([
                        parent.join("resources").join("ffmpeg.exe"),
                        parent.join("resources").join("ffmpeg-x86_64-pc-windows-gnu.exe"),
                        parent.join("resources").join("ffmpeg-x86_64-pc-windows-msvc.exe"),
                    ]);
                }
            }
        }
        if let Some(found) = candidates.into_iter().find(|p| p.is_file()) {
            return Ok(found);
        }
    }

    #[cfg(target_os = "macos")]
    {
        let mut candidates = Vec::new();
        if let Ok(exe) = std::env::current_exe() {
            if let Some(contents_macos) = exe.parent() {
                if let Some(contents) = contents_macos.parent() {
                    candidates.extend([
                        contents.join("Resources").join("ffmpeg"),
                        contents.join("MacOS").join("ffmpeg"),
                    ]);
                }
            }
        }
        if let Some(found) = candidates.into_iter().find(|p| p.is_file()) {
            return Ok(found);
        }
    }

    let names: &[&str] = if cfg!(target_os = "windows") {
        &["ffmpeg.exe", "ffmpeg"]
    } else {
        &["ffmpeg"]
    };
    std::env::var_os("PATH")
        .and_then(|paths| {
            std::env::split_paths(&paths)
                .find_map(|p| names.iter().map(|name| p.join(name)).find(|p| p.is_file()))
        })
        .or_else(|| {
            ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/app/bin/ffmpeg"]
                .into_iter()
                .map(Path::new)
                .find(|p| p.is_file())
                .map(Path::to_path_buf)
        })
        .ok_or_else(|| "ffmpeg not found on PATH".to_string())
}
