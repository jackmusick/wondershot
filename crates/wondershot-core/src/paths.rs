use std::path::{Path, PathBuf};

/// `<prefix>_%Y%m%d_%H%M%S.png` in local time (matches Python strftime).
pub fn timestamp_name(prefix: &str) -> String {
    let now = chrono::Local::now();
    format!("{}_{}.png", prefix, now.format("%Y%m%d_%H%M%S"))
}

/// First non-colliding path: `name`, then `name-1.ext`, `name-2.ext`, …
pub fn unique_path(dir: &Path, name: &str) -> PathBuf {
    let mut candidate = dir.join(name);
    if !candidate.exists() {
        return candidate;
    }
    let (stem, ext) = match name.rsplit_once('.') {
        Some((s, e)) => (s.to_string(), format!(".{e}")),
        None => (name.to_string(), String::new()),
    };
    let mut n = 1;
    loop {
        candidate = dir.join(format!("{stem}-{n}{ext}"));
        if !candidate.exists() {
            return candidate;
        }
        n += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn timestamp_name_matches_python_format() {
        let name = timestamp_name("Screenshot");
        assert!(name.starts_with("Screenshot_"));
        assert!(name.ends_with(".png"));
        let stamp = &name["Screenshot_".len()..name.len() - 4];
        let (d, t) = stamp.split_once('_').unwrap();
        assert_eq!(d.len(), 8);
        assert_eq!(t.len(), 6);
        assert!(d.chars().chain(t.chars()).all(|c| c.is_ascii_digit()));
    }

    #[test]
    fn unique_path_appends_dash_n_on_collision() {
        let dir = tempfile::tempdir().unwrap();
        let p0 = unique_path(dir.path(), "Shot_20260608_000000.png");
        assert_eq!(p0.file_name().unwrap(), "Shot_20260608_000000.png");
        fs::write(&p0, b"x").unwrap();
        let p1 = unique_path(dir.path(), "Shot_20260608_000000.png");
        assert_eq!(p1.file_name().unwrap(), "Shot_20260608_000000-1.png");
        fs::write(&p1, b"x").unwrap();
        let p2 = unique_path(dir.path(), "Shot_20260608_000000.png");
        assert_eq!(p2.file_name().unwrap(), "Shot_20260608_000000-2.png");
    }
}
