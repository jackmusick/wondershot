//! Live library folder watching — Python-app parity (QFileSystemWatcher).
//!
//! The Qt app's carousel updates the moment a file lands in a watched folder
//! (a Spectacle hotkey capture, a file dropped in by another program). The
//! frontend only re-scans on its own actions (capture/import/trash), so
//! without this, externally created files never appear until a restart.
//!
//! A `notify` watcher over `Settings::library_dirs()` feeds a debounce thread
//! that emits `library://changed`; `+page.svelte` listens and re-runs
//! `loadLibrary()`. `rewatch()` is called at startup and after every
//! `set_settings` so folder changes take effect immediately.

use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::path::PathBuf;
use std::sync::mpsc;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use tauri::Emitter;
use wondershot_core::library::{is_image_ext, is_video_ext};
use wondershot_core::settings::Settings;

/// Managed state holding the live watcher so a settings change can replace it.
pub struct LibWatch {
    watcher: Mutex<Option<RecommendedWatcher>>,
    acknowledged: Arc<Mutex<HashMap<PathBuf, std::time::Instant>>>,
}

impl Default for LibWatch {
    fn default() -> Self {
        Self {
            watcher: Mutex::new(None),
            acknowledged: Arc::new(Mutex::new(HashMap::new())),
        }
    }
}

/// Mark an app-created file so the debounced filesystem event does not trigger
/// a redundant full library scan after the frontend has inserted it directly.
pub fn acknowledge(state: &LibWatch, path: &Path) {
    state
        .acknowledged
        .lock()
        .unwrap()
        .insert(path.to_path_buf(), std::time::Instant::now());
}

fn retain_external(
    paths: HashSet<PathBuf>,
    acknowledged: &Mutex<HashMap<PathBuf, std::time::Instant>>,
) -> bool {
    let now = std::time::Instant::now();
    let mut own = acknowledged.lock().unwrap();
    own.retain(|_, at| now.duration_since(*at) < Duration::from_secs(2));
    paths.iter().any(|path| !own.contains_key(path))
}

/// Only library-relevant changes should wake the frontend: media files, not
/// sidecar writes (`.wondershot/`), temp files, or our own atomic-save churn.
fn is_relevant(path: &Path) -> bool {
    let Some(name) = path.file_name().map(|n| n.to_string_lossy().to_string()) else {
        return false;
    };
    if name.starts_with('.') || name.contains(".tmp") || name.ends_with(".part") {
        return false;
    }
    // Anything inside a dot-directory (.wondershot sidecars) is internal.
    if path
        .components()
        .any(|c| c.as_os_str().to_string_lossy().starts_with('.'))
    {
        return false;
    }
    match path.extension().map(|e| e.to_string_lossy().to_string()) {
        Some(ext) => is_image_ext(&ext) || is_video_ext(&ext),
        None => false,
    }
}

/// (Re)build the watcher over the current settings' library dirs. Replaces any
/// previous watcher (dropping it stops its threads). Missing dirs are skipped —
/// the library dir is created lazily on first capture.
pub fn rewatch(app: &tauri::AppHandle, state: &LibWatch) {
    let dirs = Settings::load().library_dirs();

    let (tx, rx) = mpsc::channel::<Vec<PathBuf>>();
    let mut watcher =
        match notify::recommended_watcher(move |res: notify::Result<notify::Event>| {
            if let Ok(event) = res {
                use notify::EventKind;
                let relevant_kind = matches!(
                    event.kind,
                    EventKind::Create(_) | EventKind::Modify(_) | EventKind::Remove(_)
                );
                if relevant_kind {
                    let paths: Vec<PathBuf> =
                        event.paths.into_iter().filter(|p| is_relevant(p)).collect();
                    if !paths.is_empty() {
                        let _ = tx.send(paths);
                    }
                }
            }
        }) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("library watcher unavailable: {e}");
                return;
            }
        };

    let mut watching = 0usize;
    for dir in &dirs {
        let p = Path::new(dir);
        if !p.is_dir() {
            continue;
        }
        match watcher.watch(p, RecursiveMode::NonRecursive) {
            Ok(()) => watching += 1,
            Err(e) => eprintln!("cannot watch {}: {e}", dir.display()),
        }
    }
    if watching == 0 {
        return; // nothing watchable; keep any previous watcher dropped
    }

    // Debounce: a capture write or a bulk copy lands as a burst of events;
    // coalesce 500ms of quiet before telling the frontend to re-scan.
    let handle = app.clone();
    let acknowledged = state.acknowledged.clone();
    std::thread::spawn(move || {
        while let Ok(first) = rx.recv() {
            let mut changed: HashSet<PathBuf> = first.into_iter().collect();
            while let Ok(paths) = rx.recv_timeout(Duration::from_millis(500)) {
                changed.extend(paths);
            }
            if retain_external(changed, &acknowledged) {
                let _ = handle.emit("library://changed", ());
            }
        }
        // Channel closed → the watcher was replaced/dropped; thread ends.
    });

    *state.watcher.lock().unwrap() = Some(watcher);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn acknowledged_capture_does_not_request_a_rescan() {
        let own = Mutex::new(HashMap::from([(
            PathBuf::from("/shots/one.png"),
            std::time::Instant::now(),
        )]));
        assert!(!retain_external(
            HashSet::from([PathBuf::from("/shots/one.png")]),
            &own,
        ));
        assert!(retain_external(
            HashSet::from([PathBuf::from("/shots/external.png")]),
            &own,
        ));
    }
}
