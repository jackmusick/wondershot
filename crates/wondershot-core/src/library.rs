use serde::Serialize;
use std::path::{Path, PathBuf};

const IMAGE_EXTS: [&str; 6] = ["png", "jpg", "jpeg", "webp", "bmp", "gif"];
const VIDEO_EXTS: [&str; 6] = ["mp4", "mkv", "webm", "mov", "avi", "m4v"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CaptureKind {
    Image,
    Video,
}

#[derive(Debug, Clone, Serialize)]
pub struct Capture {
    pub id: String,
    pub path: PathBuf,
    pub kind: CaptureKind,
    #[serde(rename = "createdAt")]
    pub created_at: u64,
    pub title: String,
}

/// Build library metadata for one completed media file without rescanning every
/// configured directory. Capture completion uses this on the latency-critical
/// path; `scan` remains the reconciliation path for external filesystem edits.
pub fn from_path(path: &Path) -> Option<Capture> {
    if !path.is_file() {
        return None;
    }
    let ext = path.extension()?.to_string_lossy();
    let kind = if is_image_ext(&ext) {
        CaptureKind::Image
    } else if is_video_ext(&ext) {
        CaptureKind::Video
    } else {
        return None;
    };
    Some(Capture {
        id: path.to_string_lossy().to_string(),
        path: path.to_path_buf(),
        kind,
        created_at: mtime_ms(path),
        title: path.file_stem()?.to_string_lossy().to_string(),
    })
}

pub fn is_image_ext(ext: &str) -> bool {
    IMAGE_EXTS.contains(&ext.to_ascii_lowercase().as_str())
}

pub fn is_video_ext(ext: &str) -> bool {
    VIDEO_EXTS.contains(&ext.to_ascii_lowercase().as_str())
}

fn mtime_ms(p: &Path) -> u64 {
    std::fs::metadata(p)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

pub fn scan(dirs: &[PathBuf]) -> Vec<Capture> {
    let mut caps = Vec::new();
    for dir in dirs {
        let Ok(entries) = std::fs::read_dir(dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }
            if let Some(capture) = from_path(&path) {
                caps.push(capture);
            }
        }
    }
    caps.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    caps
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn scan_lists_media_newest_first_and_skips_sidecar_dir() {
        let dir = tempfile::tempdir().unwrap();
        let a = dir.path().join("a.png");
        let b = dir.path().join("b.mp4");
        fs::write(&a, b"x").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(20));
        fs::write(&b, b"x").unwrap();
        fs::write(dir.path().join("notes.txt"), b"x").unwrap();
        fs::create_dir_all(dir.path().join(".wondershot")).unwrap();
        fs::write(dir.path().join(".wondershot/a.png.json"), b"{}").unwrap();
        let caps = scan(&[dir.path().to_path_buf()]);
        assert_eq!(caps.len(), 2);
        assert_eq!(caps[0].path, b);
        assert_eq!(caps[1].path, a);
        assert_eq!(caps[0].kind, CaptureKind::Video);
        assert_eq!(caps[1].kind, CaptureKind::Image);
    }

    #[test]
    fn is_image_and_video_ext_match_python_sets() {
        for e in ["png", "jpg", "jpeg", "webp", "bmp", "gif"] {
            assert!(is_image_ext(e));
        }
        for e in ["mp4", "mkv", "webm", "mov", "avi", "m4v"] {
            assert!(is_video_ext(e));
        }
        assert!(!is_image_ext("txt"));
        assert!(is_image_ext("PNG"));
    }

    #[test]
    fn from_path_builds_one_capture_without_a_directory_scan() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("one.png");
        fs::write(&path, b"png").unwrap();
        let capture = from_path(&path).unwrap();
        assert_eq!(capture.path, path);
        assert_eq!(capture.title, "one");
        assert_eq!(capture.kind, CaptureKind::Image);
        assert!(from_path(&dir.path().join("missing.png")).is_none());
    }
}
