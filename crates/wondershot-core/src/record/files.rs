//! PURE filename / salvage / sweep decision helpers ported from `record.py`.

use std::path::{Path, PathBuf};

/// Timestamped output name `Recording_YYYYMMDD_HHMMSS.mp4`.
/// (record.py:528 — timestamp_name("Recording") with .mp4 extension)
pub fn recording_name() -> String {
    format!("Recording_{}.mp4", chrono::Local::now().format("%Y%m%d_%H%M%S"))
}

/// The `.rendering` tmp dir under the library. (record.py:529)
pub fn rendering_dir(library_dir: &Path) -> PathBuf {
    library_dir.join(".rendering")
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Salvage {
    MoveToOut,
    Delete,
    Nothing,
}

/// Decide what to do with a tmp recording on finalize. (record.py:_salvage_partial)
pub fn salvage_decision(tmp_exists: bool, tmp_size: u64) -> Salvage {
    if !tmp_exists {
        return Salvage::Nothing;
    }
    if tmp_size > 0 {
        Salvage::MoveToOut
    } else {
        Salvage::Delete
    }
}

/// A tmp file older than `max_age_s` is a dead orphan. (record.py:sweep_stale_tmp)
pub fn is_stale(mtime_age_s: f64, max_age_s: u64) -> bool {
    mtime_age_s > max_age_s as f64
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn recording_name_pattern() {
        let n = recording_name();
        assert!(n.starts_with("Recording_"));
        assert!(n.ends_with(".mp4"));
        let stamp = &n["Recording_".len()..n.len()-4];
        let (d,t) = stamp.split_once('_').unwrap();
        assert_eq!(d.len(), 8); assert_eq!(t.len(), 6);
    }
    #[test] fn rendering_dir_is_dot_rendering() {
        let d = rendering_dir(std::path::Path::new("/lib"));
        assert!(d.ends_with(".rendering"));
    }
    #[test] fn salvage_keeps_nonzero_deletes_zero() {
        assert_eq!(salvage_decision(true, 1024), Salvage::MoveToOut);
        assert_eq!(salvage_decision(true, 0), Salvage::Delete);
        assert_eq!(salvage_decision(false, 0), Salvage::Nothing);
    }
    #[test] fn is_stale_past_threshold() {
        assert!(is_stale(3601.0, 3600));
        assert!(!is_stale(10.0, 3600));
    }
}
