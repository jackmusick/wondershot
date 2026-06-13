use std::io::Write;
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use super::clock::{format_elapsed, KILL_MS};
use super::files::{salvage_decision, Salvage};

#[derive(Debug, Clone)]
pub enum RecEvent {
    Started,
    Stopping,
    Finished(PathBuf),
    Failed(String),
    Tick(String),
    PausedChanged(bool),
}

pub struct Recorder {
    child: Arc<Mutex<Child>>,
    tmp: PathBuf,
    out: PathBuf,
    on_event: Arc<dyn Fn(RecEvent) + Send + Sync + 'static>,
    stopping: Arc<AtomicBool>,
    finished: Arc<AtomicBool>,
    paused: Arc<AtomicBool>,
    pause_clock: Arc<Mutex<PauseClock>>,
    watchdog: Option<std::thread::JoinHandle<()>>,
}

#[derive(Debug, Default)]
struct PauseClock {
    total: Duration,
    started: Option<Instant>,
}

impl Recorder {
    pub fn launch(
        description: &str,
        tmp: PathBuf,
        out: PathBuf,
        on_event: impl Fn(RecEvent) + Send + Sync + 'static,
    ) -> Result<Self, String> {
        let ffmpeg = crate::ffmpeg::find_ffmpeg()?;
        if let Some(parent) = tmp.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        if let Some(parent) = out.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }

        let args: Vec<&str> = description.lines().filter(|s| !s.is_empty()).collect();
        let mut command = Command::new(ffmpeg);
        #[cfg(target_os = "windows")]
        command.creation_flags(0x08000000);
        let child = command
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("could not start ffmpeg: {e}"))?;

        let on_event: Arc<dyn Fn(RecEvent) + Send + Sync> = Arc::new(on_event);
        let child = Arc::new(Mutex::new(child));
        let stopping = Arc::new(AtomicBool::new(false));
        let finished = Arc::new(AtomicBool::new(false));
        let paused = Arc::new(AtomicBool::new(false));
        let pause_clock = Arc::new(Mutex::new(PauseClock::default()));
        let started_at = Instant::now();
        let watchdog = spawn_watchdog(
            child.clone(),
            tmp.clone(),
            out.clone(),
            on_event.clone(),
            stopping.clone(),
            finished.clone(),
            paused.clone(),
            pause_clock.clone(),
            started_at,
        );

        on_event(RecEvent::Started);
        Ok(Self {
            child,
            tmp,
            out,
            on_event,
            stopping,
            finished,
            paused,
            pause_clock,
            watchdog: Some(watchdog),
        })
    }

    pub fn pause(&self) {
        if !self.paused.swap(true, Ordering::SeqCst) {
            if write_child_stdin(&self.child, b"p").is_ok() {
                if let Ok(mut clock) = self.pause_clock.lock() {
                    clock.started = Some(Instant::now());
                }
                (self.on_event)(RecEvent::PausedChanged(true));
            } else {
                self.paused.store(false, Ordering::SeqCst);
            }
        }
    }

    pub fn resume(&self) {
        if self.paused.swap(false, Ordering::SeqCst) {
            if write_child_stdin(&self.child, b"p").is_ok() {
                if let Ok(mut clock) = self.pause_clock.lock() {
                    if let Some(started) = clock.started.take() {
                        clock.total = clock.total.saturating_add(started.elapsed());
                    }
                }
                (self.on_event)(RecEvent::PausedChanged(false));
            } else {
                self.paused.store(true, Ordering::SeqCst);
            }
        }
    }

    pub fn stop(mut self) {
        self.stopping.store(true, Ordering::SeqCst);
        (self.on_event)(RecEvent::Stopping);
        if self.paused.swap(false, Ordering::SeqCst) {
            let _ = write_child_stdin(&self.child, b"p");
            std::thread::sleep(Duration::from_millis(50));
        }
        let _ = write_child_stdin(&self.child, b"q\n");

        let start = Instant::now();
        loop {
            let done = self
                .child
                .lock()
                .ok()
                .and_then(|mut child| child.try_wait().ok().flatten())
                .is_some();
            if done || start.elapsed().as_millis() as u64 >= KILL_MS {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }

        if !self.finished.load(Ordering::SeqCst) {
            if let Ok(mut child) = self.child.lock() {
                let _ = child.kill();
                let _ = child.wait();
            }
            finalize(&self.tmp, &self.out, &self.on_event);
            self.finished.store(true, Ordering::SeqCst);
        }

        if let Some(h) = self.watchdog.take() {
            let _ = h.join();
        }
    }

    pub fn supports_pause() -> bool {
        true
    }
}

fn write_child_stdin(child: &Arc<Mutex<Child>>, bytes: &[u8]) -> Result<(), ()> {
    let mut child = child.lock().map_err(|_| ())?;
    let stdin = child.stdin.as_mut().ok_or(())?;
    stdin.write_all(bytes).map_err(|_| ())?;
    stdin.flush().map_err(|_| ())
}

fn spawn_watchdog(
    child: Arc<Mutex<Child>>,
    tmp: PathBuf,
    out: PathBuf,
    on_event: Arc<dyn Fn(RecEvent) + Send + Sync + 'static>,
    stopping: Arc<AtomicBool>,
    finished: Arc<AtomicBool>,
    paused: Arc<AtomicBool>,
    pause_clock: Arc<Mutex<PauseClock>>,
    started_at: Instant,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(Duration::from_millis(1000));
            let exited = child
                .lock()
                .ok()
                .and_then(|mut child| child.try_wait().ok().flatten())
                .is_some();
            if exited {
                if !finished.swap(true, Ordering::SeqCst) {
                    finalize(&tmp, &out, &on_event);
                }
                break;
            }
            if stopping.load(Ordering::SeqCst) {
                continue;
            }
            if paused.load(Ordering::SeqCst) {
                continue;
            }
            let paused_total = pause_clock
                .lock()
                .map(|clock| clock.total)
                .unwrap_or_default();
            let elapsed = started_at.elapsed().saturating_sub(paused_total);
            on_event(RecEvent::Tick(format_elapsed(elapsed.as_secs_f64())));
        }
    })
}

fn finalize(
    tmp: &Path,
    out: &Path,
    on_event: &Arc<dyn Fn(RecEvent) + Send + Sync + 'static>,
) {
    let tmp_size = std::fs::metadata(tmp).map(|m| m.len()).unwrap_or(0);
    match salvage_decision(tmp.exists(), tmp_size) {
        Salvage::MoveToOut => {
            let moved = std::fs::rename(tmp, out)
                .or_else(|_| std::fs::copy(tmp, out).map(|_| ()).and_then(|_| std::fs::remove_file(tmp)));
            match moved {
                Ok(()) => on_event(RecEvent::Finished(out.to_path_buf())),
                Err(e) => on_event(RecEvent::Failed(format!("could not save recording: {e}"))),
            }
        }
        Salvage::Delete => {
            let _ = std::fs::remove_file(tmp);
            on_event(RecEvent::Failed("recording produced an empty file".into()));
        }
        Salvage::Nothing => on_event(RecEvent::Failed("recording produced no output file".into())),
    }
}

pub fn resolve_mic_source(description: &str) -> String {
    resolve_capture_device("audioinput", description).unwrap_or_default()
}

pub fn have_gst_element(_name: &str) -> bool {
    false
}

pub fn mic_probe(_source: &str) -> Result<f64, String> {
    Err("microphone probing is not available on Windows yet".into())
}

pub fn list_capture_devices() -> Vec<(String, String)> {
    let Ok(ffmpeg) = crate::ffmpeg::find_ffmpeg() else { return Vec::new() };
    let mut command = Command::new(ffmpeg);
    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000);
    let output = command
        .args(["-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
        .output();
    let Ok(output) = output else { return Vec::new() };
    let mut text = String::from_utf8_lossy(&output.stderr).to_string();
    text.push_str(&String::from_utf8_lossy(&output.stdout));
    parse_dshow_devices(&text)
}

pub fn resolve_capture_device(kind: &str, preferred: &str) -> Option<String> {
    let devices = list_capture_devices();
    let preferred = preferred.trim();
    if !preferred.is_empty()
        && devices.iter().any(|(device_kind, label)| device_kind == kind && label == preferred)
    {
        return Some(preferred.to_string());
    }
    devices
        .into_iter()
        .find_map(|(device_kind, label)| (device_kind == kind).then_some(label))
}

pub fn build_recording_args(
    tmp: &Path,
    rect: Option<(u32, u32, u32, u32)>,
    capture_cursor: bool,
    mic_enabled: bool,
    mic_device: &str,
) -> Vec<String> {
    let (origin_x, origin_y) = crate::capture::native::virtual_origin();
    let mut args = vec![
        "-y".into(),
        "-f".into(),
        "gdigrab".into(),
        "-framerate".into(),
        "30".into(),
        "-draw_mouse".into(),
        if capture_cursor { "1" } else { "0" }.into(),
    ];
    if let Some((x, y, w, h)) = rect {
        let screen_x = (x as i64 + origin_x as i64).clamp(i32::MIN as i64, i32::MAX as i64);
        let screen_y = (y as i64 + origin_y as i64).clamp(i32::MIN as i64, i32::MAX as i64);
        args.extend([
            "-offset_x".into(),
            screen_x.to_string(),
            "-offset_y".into(),
            screen_y.to_string(),
            "-video_size".into(),
            format!("{}x{}", w.max(2), h.max(2)),
        ]);
    }
    args.extend(["-i".into(), "desktop".into()]);

    let mic = resolve_mic_source(mic_device);
    let include_mic = mic_enabled && !mic.trim().is_empty();
    if include_mic {
        args.extend(["-f".into(), "dshow".into(), "-i".into(), format!("audio={mic}")]);
    }

    args.extend(["-map".into(), "0:v".into()]);
    if include_mic {
        args.extend(["-map".into(), "1:a".into()]);
    }
    args.extend([
        "-c:v".into(),
        "libx264".into(),
        "-preset".into(),
        "veryfast".into(),
        "-crf".into(),
        "23".into(),
        "-pix_fmt".into(),
        "yuv420p".into(),
        "-movflags".into(),
        "+faststart".into(),
        tmp.to_string_lossy().into_owned(),
    ]);
    args
}

fn parse_dshow_devices(text: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let mut section: Option<&str> = None;
    for line in text.lines() {
        if line.contains("DirectShow video devices") {
            section = Some("videoinput");
            continue;
        }
        if line.contains("DirectShow audio devices") {
            section = Some("audioinput");
            continue;
        }
        let Some(first) = line.find('"') else { continue };
        let Some(rel_last) = line[first + 1..].find('"') else { continue };
        let label = &line[first + 1..first + 1 + rel_last];
        let suffix = &line[first + 1 + rel_last + 1..];
        let kind = if suffix.contains("(video)") {
            "videoinput"
        } else if suffix.contains("(audio)") {
            "audioinput"
        } else {
            let Some(kind) = section else { continue };
            kind
        };
        if !label.starts_with('@') {
            out.push((kind.to_string(), label.to_string()));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_dshow_devices() {
        let text = r#"
[dshow @ 000001] DirectShow video devices (some may be both video and audio devices)
[dshow @ 000001]  "Integrated Camera"
[dshow @ 000001]     Alternative name "@device_pnp_..."
[dshow @ 000001] DirectShow audio devices
[dshow @ 000001]  "Microphone Array"
"#;
        assert_eq!(
            parse_dshow_devices(text),
            vec![
                ("videoinput".to_string(), "Integrated Camera".to_string()),
                ("audioinput".to_string(), "Microphone Array".to_string())
            ]
        );
    }

    #[test]
    fn parses_ffmpeg_8_dshow_devices() {
        let text = r#"
[in#0 @ 000001] "Integrated Camera" (video)
[in#0 @ 000001]   Alternative name "@device_pnp_..."
[in#0 @ 000001] "Microphone Array (Realtek(R) Audio)" (audio)
Error opening input file dummy.
"#;
        assert_eq!(
            parse_dshow_devices(text),
            vec![
                ("videoinput".to_string(), "Integrated Camera".to_string()),
                ("audioinput".to_string(), "Microphone Array (Realtek(R) Audio)".to_string())
            ]
        );
    }
}
