use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use super::clock::{format_elapsed, KILL_MS};
use super::files::{salvage_decision, Salvage};

#[derive(Debug, Clone)]
pub enum RecEvent {
    Started, Stopping, Finished(PathBuf), Failed(String), Tick(String), PausedChanged(bool),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CaptureDevice {
    pub kind: String,
    pub index: u32,
    pub label: String,
}

// AVFoundation has no pause command. Close the current MP4 on pause and start
// a fresh segment on resume, so no screen or microphone content is captured
// during the pause. Concatenation preserves only the active recording time.
struct Session {
    child: Option<Child>,
    ffmpeg: PathBuf,
    args: Vec<String>,
    tmp: PathBuf,
    segments: Vec<PathBuf>,
    pause_started: Option<Instant>,
    paused_total: Duration,
    started_at: Instant,
    stderr_tail: Arc<Mutex<String>>,
    segment_started_at: Instant,
}

impl Session {
    fn start_segment(&mut self) -> Result<(), String> {
        let path = self.tmp.with_file_name(format!("{}.segment-{}.mp4",
            self.tmp.file_stem().unwrap_or_default().to_string_lossy(), self.segments.len()));
        let mut args = self.args.clone();
        *args.last_mut().ok_or("recording command has no output path")? = path.to_string_lossy().into_owned();
        let mut child = Command::new(&self.ffmpeg).args(args)
            .stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::piped())
            .spawn().map_err(|e| format!("could not start ffmpeg: {e}"))?;
        spawn_stderr_reader(child.stderr.take(), self.stderr_tail.clone());
        self.child = Some(child);
        self.segments.push(path);
        self.segment_started_at = Instant::now();
        Ok(())
    }

    fn close_segment(&mut self) -> Result<(), String> {
        let Some(mut child) = self.child.take() else { return Ok(()) };
        if let Some(stdin) = child.stdin.as_mut() {
            let _ = stdin.write_all(b"q\n");
            let _ = stdin.flush();
        }
        let deadline = Instant::now() + Duration::from_millis(KILL_MS);
        loop {
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                return if status.success() { Ok(()) } else { Err(format!("ffmpeg exited with {status}")) };
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                return Err("ffmpeg did not finalize its recording before the timeout".into());
            }
            std::thread::sleep(Duration::from_millis(25));
        }
    }
}

pub struct Recorder {
    session: Arc<Mutex<Session>>,
    out: PathBuf,
    on_event: Arc<dyn Fn(RecEvent) + Send + Sync + 'static>,
    stopping: Arc<AtomicBool>,
    failed: Arc<AtomicBool>,
    watchdog: Option<std::thread::JoinHandle<()>>,
}

impl Recorder {
    pub fn launch(description: &str, tmp: PathBuf, out: PathBuf,
        on_event: impl Fn(RecEvent) + Send + Sync + 'static) -> Result<Self, String> {
        if let Some(parent) = tmp.parent() { std::fs::create_dir_all(parent).map_err(|e| e.to_string())?; }
        if let Some(parent) = out.parent() { std::fs::create_dir_all(parent).map_err(|e| e.to_string())?; }
        let mut session = Session {
            child: None, ffmpeg: crate::ffmpeg::find_ffmpeg()?,
            args: description.lines().filter(|s| !s.is_empty()).map(String::from).collect(),
            tmp, segments: vec![], pause_started: None, paused_total: Duration::ZERO,
            started_at: Instant::now(), stderr_tail: Arc::new(Mutex::new(String::new())),
            segment_started_at: Instant::now(),
        };
        session.start_segment()?;
        let session = Arc::new(Mutex::new(session));
        let on_event: Arc<dyn Fn(RecEvent) + Send + Sync> = Arc::new(on_event);
        let stopping = Arc::new(AtomicBool::new(false));
        let failed = Arc::new(AtomicBool::new(false));
        let watchdog = {
            let session = session.clone(); let on_event = on_event.clone();
            let stopping = stopping.clone(); let failed = failed.clone();
            std::thread::spawn(move || {
                let mut last_tick = String::new();
                while !stopping.load(Ordering::SeqCst) {
                    std::thread::sleep(Duration::from_millis(100));
                    let event = {
                        let Ok(mut s) = session.lock() else { break };
                        if let Some(status) = s.child.as_mut().and_then(|c| c.try_wait().ok().flatten()) {
                            s.child = None;
                            failed.store(true, Ordering::SeqCst);
                            Some(RecEvent::Failed(recording_failure(format!("ffmpeg stopped unexpectedly ({status})"), &s.stderr_tail)))
                        } else if s.child.is_some() && s.segment_started_at.elapsed() > Duration::from_secs(15)
                            && !s.segments.last().is_some_and(|p| p.exists()) {
                            if let Some(mut child) = s.child.take() { let _ = child.kill(); let _ = child.wait(); }
                            failed.store(true, Ordering::SeqCst);
                            Some(RecEvent::Failed(recording_failure("no frames received; check the selected display and microphone permissions", &s.stderr_tail)))
                        } else if s.pause_started.is_none() {
                            let tick = format_elapsed(s.started_at.elapsed().saturating_sub(s.paused_total).as_secs_f64());
                            if tick != last_tick { last_tick = tick.clone(); Some(RecEvent::Tick(tick)) } else { None }
                        } else { None }
                    };
                    if let Some(event) = event { on_event(event); }
                    if failed.load(Ordering::SeqCst) { break; }
                }
            })
        };
        on_event(RecEvent::Started);
        Ok(Self { session, out, on_event, stopping, failed, watchdog: Some(watchdog) })
    }

    pub fn pause(&self) {
        let result = {
            let Ok(mut s) = self.session.lock() else { return };
            if s.pause_started.is_some() || self.failed.load(Ordering::SeqCst) { return; }
            s.pause_started = Some(Instant::now());
            s.close_segment().map_err(|e| recording_failure(e, &s.stderr_tail))
        };
        match result {
            Ok(()) => (self.on_event)(RecEvent::PausedChanged(true)),
            Err(e) => { self.failed.store(true, Ordering::SeqCst); (self.on_event)(RecEvent::Failed(e)); }
        }
    }

    pub fn resume(&self) {
        let result = {
            let Ok(mut s) = self.session.lock() else { return };
            if s.pause_started.is_none() || self.failed.load(Ordering::SeqCst) { return; }
            s.start_segment().map(|_| {
                if let Some(started) = s.pause_started.take() { s.paused_total += started.elapsed(); }
            }).map_err(|e| recording_failure(e, &s.stderr_tail))
        };
        match result {
            Ok(()) => (self.on_event)(RecEvent::PausedChanged(false)),
            Err(e) => { self.failed.store(true, Ordering::SeqCst); (self.on_event)(RecEvent::Failed(e)); }
        }
    }

    pub fn stop(mut self) {
        self.stopping.store(true, Ordering::SeqCst);
        (self.on_event)(RecEvent::Stopping);
        let result = self.session.lock().map_err(|e| e.to_string()).and_then(|mut s| {
            s.close_segment()?;
            if self.failed.load(Ordering::SeqCst) { return Err("recording already failed; segments retained for recovery".into()); }
            merge_segments(&s.ffmpeg, &s.segments, &s.tmp)?;
            finalize(&s.tmp, &self.out, &self.on_event, &s.stderr_tail);
            for segment in &s.segments { let _ = std::fs::remove_file(segment); }
            Ok(())
        });
        if let Err(e) = result { (self.on_event)(RecEvent::Failed(e)); }
        if let Some(h) = self.watchdog.take() { let _ = h.join(); }
    }

    pub fn supports_pause() -> bool { true }
}

impl Drop for Recorder {
    fn drop(&mut self) {
        self.stopping.store(true, Ordering::SeqCst);
        if let Ok(mut s) = self.session.lock() {
            if let Some(mut child) = s.child.take() { let _ = child.kill(); let _ = child.wait(); }
        }
        if let Some(h) = self.watchdog.take() { let _ = h.join(); }
    }
}

fn merge_segments(ffmpeg: &Path, segments: &[PathBuf], tmp: &Path) -> Result<(), String> {
    if segments.is_empty() { return Err("recording has no segments".into()); }
    if segments.len() == 1 {
        std::fs::copy(&segments[0], tmp).map_err(|e| e.to_string())?;
        return Ok(());
    }
    let list = tmp.with_extension("concat.txt");
    let contents = segments.iter().map(|path| {
        let path = std::fs::canonicalize(path).map_err(|e| e.to_string())?;
        Ok(format!("file '{}'\n", path.to_string_lossy().replace('\\', "\\\\").replace('\'', "'\\''")))
    }).collect::<Result<Vec<_>, String>>()?.concat();
    std::fs::write(&list, contents).map_err(|e| e.to_string())?;
    let output = Command::new(ffmpeg).args(["-y", "-f", "concat", "-safe", "0", "-i"])
        .arg(&list).args(["-c", "copy", "-movflags", "+faststart"]).arg(tmp)
        .output().map_err(|e| e.to_string());
    let _ = std::fs::remove_file(list);
    let output = output?;
    if !output.status.success() { return Err(format!("could not combine recording segments: {}", String::from_utf8_lossy(&output.stderr))); }
    Ok(())
}

fn spawn_stderr_reader(stderr: Option<std::process::ChildStderr>, tail: Arc<Mutex<String>>) {
    let Some(stderr) = stderr else { return };
    std::thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            if let Ok(mut tail) = tail.lock() {
                tail.push_str(&line); tail.push('\n');
                if tail.len() > 16384 {
                    let mut boundary = tail.len() - 8192;
                    while !tail.is_char_boundary(boundary) { boundary += 1; }
                    tail.drain(..boundary);
                }
            }
        }
    });
}

fn recording_failure(message: impl AsRef<str>, stderr_tail: &Arc<Mutex<String>>) -> String {
    let tail = stderr_tail
        .lock()
        .map(|tail| tail.trim().to_string())
        .unwrap_or_default();
    if tail.is_empty() {
        format!("recording failed: {}", message.as_ref())
    } else {
        format!("recording failed: {}: {tail}", message.as_ref())
    }
}

fn finalize(
    tmp: &Path,
    out: &Path,
    on_event: &Arc<dyn Fn(RecEvent) + Send + Sync + 'static>,
    stderr_tail: &Arc<Mutex<String>>,
) {
    let tmp_size = std::fs::metadata(tmp).map(|m| m.len()).unwrap_or(0);
    match salvage_decision(tmp.exists(), tmp_size) {
        Salvage::MoveToOut => {
            let moved = std::fs::rename(tmp, out).or_else(|_| {
                std::fs::copy(tmp, out)
                    .map(|_| ())
                    .and_then(|_| std::fs::remove_file(tmp))
            });
            match moved {
                Ok(()) => on_event(RecEvent::Finished(out.to_path_buf())),
                Err(e) => on_event(RecEvent::Failed(recording_failure(
                    format!("could not save recording: {e}"),
                    stderr_tail,
                ))),
            }
        }
        Salvage::Delete => {
            let _ = std::fs::remove_file(tmp);
            on_event(RecEvent::Failed(recording_failure(
                "recording produced an empty file",
                stderr_tail,
            )));
        }
        Salvage::Nothing => on_event(RecEvent::Failed(recording_failure(
            "recording produced no output file",
            stderr_tail,
        ))),
    }
}

pub fn resolve_mic_source(description: &str) -> String {
    resolve_capture_device_index("audioinput", description)
        .map(|index| index.to_string())
        .unwrap_or_default()
}

pub fn have_gst_element(_name: &str) -> bool {
    false
}

pub fn mic_probe(_source: &str) -> Result<f64, String> {
    Err("microphone probing is not available on macOS yet".into())
}

pub fn list_capture_devices() -> Vec<(String, String)> {
    avfoundation_devices()
        .into_iter()
        .filter(|device| device.kind == "videoinput" || device.kind == "audioinput")
        .map(|device| (device.kind, device.label))
        .collect()
}

pub fn resolve_capture_device(kind: &str, preferred: &str) -> Option<String> {
    resolve_capture_device_index(kind, preferred).map(|index| index.to_string())
}

pub fn build_recording_args(
    tmp: &Path,
    rect: Option<(u32, u32, u32, u32)>,
    capture_cursor: bool,
    mic_enabled: bool,
    mic_device: &str,
) -> Result<Vec<String>, String> {
    let mut devices = avfoundation_devices();
    let monitors = crate::capture::macos::monitor_rects();
    let (origin_x, origin_y) = crate::capture::macos::virtual_origin();
    let (display, crop, width, height) = recording_target(rect, &monitors, (origin_x, origin_y))?;
    let label = format!("Capture screen {display}");
    let screen = devices.iter().find(|d| d.kind == "screen" && d.label == label)
        .cloned().ok_or_else(|| format!("FFmpeg did not report {label}"))?;
    devices.retain(|d| d.kind != "screen");
    devices.insert(0, screen);
    let mut args = build_recording_args_with_devices(tmp, crop, capture_cursor, mic_enabled, mic_device, &devices);
    // AVFoundation can produce backing pixels on Retina displays. Normalize to
    // display points before applying the picker rectangle, independent of scale.
    if let Some(index) = args.iter().position(|a| a == "-vf") {
        args[index + 1] = format!("scale={width}:{height},{}", args[index + 1]);
    }
    Ok(args)
}

fn recording_target(
    rect: Option<(u32, u32, u32, u32)>,
    monitors: &[crate::capture::native::MonitorRect],
    origin: (i32, i32),
) -> Result<(usize, Option<(u32, u32, u32, u32)>, u32, u32), String> {
    let Some(rect) = rect else {
        let index = monitors.iter().position(|m| m.x == 0 && m.y == 0).unwrap_or(0);
        let m = monitors.get(index).ok_or("no active display found")?;
        return Ok((index, None, m.width, m.height));
    };
    let x = i64::from(origin.0) + i64::from(rect.0);
    let y = i64::from(origin.1) + i64::from(rect.1);
    let (index, m) = monitors.iter().enumerate().find(|(_, m)|
        x >= i64::from(m.x) && y >= i64::from(m.y)
        && x + i64::from(rect.2) <= i64::from(m.x) + i64::from(m.width)
        && y + i64::from(rect.3) <= i64::from(m.y) + i64::from(m.height))
        .ok_or("choose a recording region inside one display")?;
    if rect.2 < 2 || rect.3 < 2 { return Err("recording region must be at least 2 by 2 points".into()); }
    let crop = ((x - i64::from(m.x)) as u32, (y - i64::from(m.y)) as u32, rect.2 / 2 * 2, rect.3 / 2 * 2);
    Ok((index, Some(crop), m.width, m.height))
}

pub(crate) fn build_camera_args(label: &str) -> Result<Vec<String>, String> {
    let devices = avfoundation_devices();
    build_camera_args_with_devices(label, &devices)
}

fn avfoundation_devices() -> Vec<CaptureDevice> {
    let Ok(ffmpeg) = crate::ffmpeg::find_ffmpeg() else {
        return Vec::new();
    };
    let output = Command::new(ffmpeg)
        .args([
            "-hide_banner",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ])
        .output();
    let Ok(output) = output else {
        return Vec::new();
    };
    let mut text = String::from_utf8_lossy(&output.stderr).to_string();
    text.push_str(&String::from_utf8_lossy(&output.stdout));
    parse_avfoundation_devices(&text)
}

fn resolve_capture_device_index(kind: &str, preferred: &str) -> Option<u32> {
    resolve_capture_device_index_with_devices(kind, preferred, &avfoundation_devices())
}

fn resolve_capture_device_index_with_devices(
    kind: &str,
    preferred: &str,
    devices: &[CaptureDevice],
) -> Option<u32> {
    let preferred = preferred.trim();
    if !preferred.is_empty() {
        if let Some(device) = devices
            .iter()
            .find(|device| device.kind == kind && device.label == preferred)
        {
            return Some(device.index);
        }
    }
    devices
        .iter()
        .find_map(|device| (device.kind == kind).then_some(device.index))
}

fn screen_index(devices: &[CaptureDevice]) -> u32 {
    resolve_capture_device_index_with_devices("screen", "", devices)
        .unwrap_or(0)
}

fn build_recording_args_with_devices(
    tmp: &Path,
    rect: Option<(u32, u32, u32, u32)>,
    capture_cursor: bool,
    mic_enabled: bool,
    mic_device: &str,
    devices: &[CaptureDevice],
) -> Vec<String> {
    let screen = screen_index(devices);
    let mic = mic_enabled
        .then(|| resolve_capture_device_index_with_devices("audioinput", mic_device, devices))
        .flatten();
    let mut args = vec![
        "-hide_banner".into(),
        "-loglevel".into(),
        "warning".into(),
        "-y".into(),
        "-f".into(),
        "avfoundation".into(),
        "-framerate".into(),
        "30".into(),
        "-capture_cursor".into(),
        if capture_cursor { "1" } else { "0" }.into(),
        "-i".into(),
        format!("{screen}:none"),
    ];
    if let Some(mic) = mic {
        // Separate sessions avoid AVFoundation's combined screen/audio input
        // blocking while it negotiates the microphone format on newer macOS.
        args.extend(["-thread_queue_size".into(), "512".into(), "-f".into(),
            "avfoundation".into(), "-i".into(), format!("none:{mic}")]);
    }
    args.extend(["-map".into(), "0:v".into()]);
    if mic.is_some() { args.extend(["-map".into(), "1:a".into()]); }
    if let Some((x, y, w, h)) = rect {
        args.extend([
            "-vf".into(),
            format!("crop={}:{}:{}:{}", w.max(2), h.max(2), x, y),
        ]);
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
    ]);
    if mic.is_some() {
        args.extend(["-c:a".into(), "aac".into()]);
    }
    args.extend([
        "-movflags".into(),
        "+faststart".into(),
        tmp.to_string_lossy().into_owned(),
    ]);
    args
}

fn build_camera_args_with_devices(
    label: &str,
    devices: &[CaptureDevice],
) -> Result<Vec<String>, String> {
    let camera = resolve_capture_device_index_with_devices("videoinput", label, devices)
        .ok_or_else(|| "no camera found".to_string())?;
    Ok(vec![
        "-hide_banner".into(),
        "-loglevel".into(),
        "error".into(),
        "-f".into(),
        "avfoundation".into(),
        "-framerate".into(),
        "30".into(),
        "-pixel_format".into(),
        "nv12".into(),
        "-i".into(),
        format!("{camera}:none"),
        "-an".into(),
        "-vf".into(),
        "fps=15,scale=640:-2".into(),
        "-q:v".into(),
        "5".into(),
        "-f".into(),
        "mjpeg".into(),
        "pipe:1".into(),
    ])
}

fn parse_avfoundation_devices(text: &str) -> Vec<CaptureDevice> {
    let mut out = Vec::new();
    let mut section: Option<&str> = None;
    for line in text.lines() {
        if line.contains("AVFoundation video devices") {
            section = Some("video");
            continue;
        }
        if line.contains("AVFoundation audio devices") {
            section = Some("audioinput");
            continue;
        }
        let Some(section) = section else { continue };
        let Some(open) = line.rfind('[') else {
            continue;
        };
        let Some(close_rel) = line[open + 1..].find(']') else {
            continue;
        };
        let index_text = &line[open + 1..open + 1 + close_rel];
        let Ok(index) = index_text.trim().parse::<u32>() else {
            continue;
        };
        let label = line[open + 1 + close_rel + 1..].trim();
        if label.is_empty() {
            continue;
        }
        let kind = if section == "video" && label.starts_with("Capture screen") {
            "screen"
        } else if section == "video" {
            "videoinput"
        } else {
            "audioinput"
        };
        out.push(CaptureDevice {
            kind: kind.into(),
            index,
            label: label.into(),
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recording_region_uses_display_local_coordinates() {
        use crate::capture::native::MonitorRect;
        let monitors = [MonitorRect { x: -1920, y: -200, width: 1920, height: 1080 },
            MonitorRect { x: 0, y: 0, width: 2560, height: 1440 }];
        assert_eq!(recording_target(Some((2020, 250, 641, 361)), &monitors, (-1920, -200)).unwrap(),
            (1, Some((100, 50, 640, 360)), 2560, 1440));
        assert!(recording_target(Some((1900, 250, 100, 100)), &monitors, (-1920, -200)).is_err());
        assert_eq!(recording_target(None, &monitors, (-1920, -200)).unwrap(), (1, None, 2560, 1440));
    }
    use std::path::Path;

    #[test]
    fn parses_avfoundation_devices() {
        let text = r#"
[AVFoundation indev @ 0x123] AVFoundation video devices:
[AVFoundation indev @ 0x123] [0] FaceTime HD Camera
[AVFoundation indev @ 0x123] [1] Capture screen 0
[AVFoundation indev @ 0x123] AVFoundation audio devices:
[AVFoundation indev @ 0x123] [0] MacBook Pro Microphone
"#;

        assert_eq!(
            parse_avfoundation_devices(text),
            vec![
                CaptureDevice {
                    kind: "videoinput".into(),
                    index: 0,
                    label: "FaceTime HD Camera".into(),
                },
                CaptureDevice {
                    kind: "screen".into(),
                    index: 1,
                    label: "Capture screen 0".into(),
                },
                CaptureDevice {
                    kind: "audioinput".into(),
                    index: 0,
                    label: "MacBook Pro Microphone".into(),
                },
            ]
        );
    }

    #[test]
    fn build_recording_args_targets_screen_and_optional_microphone() {
        let devices = vec![
            CaptureDevice {
                kind: "screen".into(),
                index: 1,
                label: "Capture screen 0".into(),
            },
            CaptureDevice {
                kind: "audioinput".into(),
                index: 2,
                label: "Studio Mic".into(),
            },
        ];

        let args = build_recording_args_with_devices(
            Path::new("/tmp/out.mp4"),
            Some((20, 30, 640, 360)),
            true,
            true,
            "Studio Mic",
            &devices,
        );

        assert!(args.windows(2).any(|w| w == ["-f", "avfoundation"]));
        assert!(args.windows(2).any(|w| w == ["-capture_cursor", "1"]));
        assert!(args.windows(2).any(|w| w == ["-i", "1:none"]));
        assert!(args.windows(2).any(|w| w == ["-i", "none:2"]));
        assert!(args.windows(2).any(|w| w == ["-map", "1:a"]));
        assert!(args.iter().any(|arg| arg.contains("crop=640:360:20:30")));
        assert_eq!(args.last().map(String::as_str), Some("/tmp/out.mp4"));
    }

    #[test]
    fn build_camera_args_targets_selected_camera() {
        let devices = vec![CaptureDevice {
            kind: "videoinput".into(),
            index: 3,
            label: "Continuity Camera".into(),
        }];

        let args = build_camera_args_with_devices("Continuity Camera", &devices).unwrap();

        assert!(args.windows(2).any(|w| w == ["-f", "avfoundation"]));
        assert!(args.windows(2).any(|w| w == ["-i", "3:none"]));
        assert!(args.windows(2).any(|w| w == ["-f", "mjpeg"]));
    }
}
