use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const SIDECAR_DIRNAME: &str = ".wondershot";
pub const FORMAT_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarDoc {
    pub version: u32,
    pub bases: u32,
    #[serde(default)]
    pub items: Vec<serde_json::Value>,
    #[serde(default)]
    pub effects: serde_json::Value,
}

pub fn sidecar_dir(image_path: &Path) -> PathBuf {
    let parent = image_path.parent().unwrap_or_else(|| Path::new("."));
    parent.join(SIDECAR_DIRNAME)
}

pub fn sidecar_path(image_path: &Path) -> PathBuf {
    let name = image_path.file_name().unwrap_or_default().to_string_lossy();
    sidecar_dir(image_path).join(format!("{name}.json"))
}

pub fn base_path(image_path: &Path, n: u32) -> PathBuf {
    let name = image_path.file_name().unwrap_or_default().to_string_lossy();
    sidecar_dir(image_path).join(format!("{name}.base.{n}.png"))
}

pub fn load(image_path: &Path) -> Option<SidecarDoc> {
    let raw = std::fs::read_to_string(sidecar_path(image_path)).ok()?;
    let doc: SidecarDoc = serde_json::from_str(&raw).ok()?;
    if doc.version != FORMAT_VERSION {
        return None;
    }
    Some(doc)
}

pub fn save(image_path: &Path, doc: &SidecarDoc) -> bool {
    let dir = sidecar_dir(image_path);
    if std::fs::create_dir_all(&dir).is_err() {
        return false;
    }
    let target = sidecar_path(image_path);
    let tmp = target.with_extension("json.tmp");
    let Ok(json) = serde_json::to_string(doc) else { return false };
    if std::fs::write(&tmp, json).is_err() {
        return false;
    }
    std::fs::rename(&tmp, &target).is_ok()
}

pub fn related_files(image_path: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let sp = sidecar_path(image_path);
    if sp.exists() {
        out.push(sp);
    }
    let name = image_path.file_name().unwrap_or_default().to_string_lossy().to_string();
    let dir = sidecar_dir(image_path);
    if let Ok(entries) = std::fs::read_dir(&dir) {
        let mut bases: Vec<PathBuf> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| {
                p.file_name()
                    .map(|f| {
                        let f = f.to_string_lossy();
                        f.starts_with(&format!("{name}.base.")) && f.ends_with(".png")
                    })
                    .unwrap_or(false)
            })
            .collect();
        bases.sort();
        out.extend(bases);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn paths_include_extension_so_png_and_jpg_dont_collide() {
        let img = std::path::Path::new("/lib/shot.png");
        assert!(sidecar_path(img).ends_with(".wondershot/shot.png.json"));
        let jpg = std::path::Path::new("/lib/shot.jpg");
        assert!(sidecar_path(jpg).ends_with(".wondershot/shot.jpg.json"));
        assert!(base_path(img, 0).ends_with(".wondershot/shot.png.base.0.png"));
    }

    #[test]
    fn save_then_load_roundtrips_and_leaves_no_tmp() {
        let dir = tempfile::tempdir().unwrap();
        let img = dir.path().join("shot.png");
        let doc = SidecarDoc {
            version: 1,
            bases: 1,
            items: vec![serde_json::json!({"type": "rect"})],
            effects: serde_json::json!({"rounded": true}),
        };
        assert!(save(&img, &doc));
        let got = load(&img).unwrap();
        assert_eq!(got.version, 1);
        assert_eq!(got.bases, 1);
        assert_eq!(got.items[0]["type"], "rect");
        let scdir = sidecar_dir(&img);
        let leftover: Vec<_> = fs::read_dir(&scdir)
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().map_or(false, |x| x == "tmp"))
            .collect();
        assert!(leftover.is_empty());
    }

    #[test]
    fn load_returns_none_for_missing_corrupt_or_future_version() {
        let dir = tempfile::tempdir().unwrap();
        let img = dir.path().join("shot.png");
        assert!(load(&img).is_none());
        fs::create_dir_all(sidecar_dir(&img)).unwrap();
        fs::write(sidecar_path(&img), b"{ not json").unwrap();
        assert!(load(&img).is_none());
        fs::write(
            sidecar_path(&img),
            br#"{"version":2,"bases":0,"items":[],"effects":{}}"#,
        )
        .unwrap();
        assert!(load(&img).is_none());
    }

    #[test]
    fn related_files_lists_json_plus_sorted_bases() {
        let dir = tempfile::tempdir().unwrap();
        let img = dir.path().join("shot.png");
        let doc = SidecarDoc {
            version: 1,
            bases: 2,
            items: vec![],
            effects: serde_json::json!({}),
        };
        save(&img, &doc);
        fs::write(base_path(&img, 0), b"a").unwrap();
        fs::write(base_path(&img, 1), b"b").unwrap();
        let rel = related_files(&img);
        assert_eq!(rel.len(), 3);
        assert!(rel[0].ends_with("shot.png.json"));
        assert!(rel[1].to_string_lossy().contains("base.0"));
        assert!(rel[2].to_string_lossy().contains("base.1"));
    }
}
