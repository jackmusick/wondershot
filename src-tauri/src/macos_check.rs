//! Signed, packaged-app checks that do not move the mouse or touch the library.
use std::{path::PathBuf, process::Command, sync::{Arc, Mutex}, time::Duration};
use wondershot_core::{capture::macos, ffmpeg, record::recorder::{self, Recorder, RecEvent}};

struct Scratch(PathBuf);
impl Drop for Scratch {
    fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); }
}

pub fn run() -> Result<(), String> {
    let ffmpeg = ffmpeg::find_ffmpeg()?;
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let resources = executable.parent().and_then(|p| p.parent()).ok_or("not running from an app bundle")?.join("Resources");
    if !ffmpeg.starts_with(&resources) { return Err(format!("FFmpeg is not bundled: {}", ffmpeg.display())); }
    println!("[PASS] bundled FFmpeg: {}", ffmpeg.display());
    if !macos::screen_capture_access_granted() { return Err("Screen Recording permission not granted to this app build".into()); }
    println!("[PASS] Screen Recording permission");
    let scratch = Scratch(std::env::temp_dir().join(format!("wondershot-desktop-check-{}", std::process::id())));
    std::fs::create_dir_all(&scratch.0).map_err(|e| e.to_string())?;
    let monitors = macos::monitor_rects();
    if monitors.is_empty() { return Err("no displays found".into()); }
    let (ox, oy) = macos::virtual_origin();
    let m = monitors.iter().find(|m| m.x == 0 && m.y == 0).unwrap_or(&monitors[0]);
    let rect = ((m.x - ox) as u32, (m.y - oy) as u32, m.width.min(640) / 2 * 2, m.height.min(360) / 2 * 2);
    let screenshot = scratch.0.join("capture.png");
    macos::capture_region_to(&screenshot, rect, false)?;
    let image = image::open(&screenshot).map_err(|e| e.to_string())?;
    if image.width() == 0 || image.height() == 0 { return Err("screenshot is empty".into()); }
    println!("[PASS] native region screenshot: {}x{} pixels", image.width(), image.height());
    if std::env::args().any(|a| a == "--with-camera") {
        crate::macos_permissions::ensure("camera")?;
        let settings = wondershot_core::settings::Settings::load();
        let label = std::env::args().find_map(|a| a.strip_prefix("--camera-label=").map(String::from))
            .unwrap_or(settings.camera_device);
        let stream = wondershot_core::camera::open(&label)?;
        let jpeg = stream.next_jpeg_timeout(8000).ok_or("camera produced no frames")?;
        image::load_from_memory(&jpeg).map_err(|e| e.to_string())?;
        println!("[PASS] native camera JPEG frame");
    }
    let tmp = scratch.0.join("recording.tmp.mp4");
    let out = scratch.0.join("recording.mp4");
    let with_mic = std::env::args().any(|a| a == "--with-microphone");
    let settings = wondershot_core::settings::Settings::load();
    if with_mic { crate::macos_permissions::ensure("microphone")?; }
    let args = recorder::build_recording_args(&tmp, Some(rect), false, with_mic, &settings.mic_device)?.join("\n");
    let events = Arc::new(Mutex::new(Vec::new()));
    let collected = events.clone();
    let rec = Recorder::launch(&args, tmp, out.clone(), move |e| collected.lock().unwrap().push(e))?;
    std::thread::sleep(Duration::from_millis(1800));
    rec.pause();
    std::thread::sleep(Duration::from_millis(600));
    rec.resume();
    std::thread::sleep(Duration::from_millis(1400));
    rec.stop();
    let events = events.lock().map_err(|e| e.to_string())?;
    if let Some(error) = events.iter().find_map(|e| if let RecEvent::Failed(s) = e { Some(s) } else { None }) { return Err(error.clone()); }
    if !events.iter().any(|e| matches!(e, RecEvent::Finished(_))) { return Err("native recording did not finish".into()); }
    let mut decode = Command::new(&ffmpeg);
    decode.args(["-v", "error", "-i"]).arg(&out).args(["-map", "0:v"]);
    if with_mic { decode.args(["-map", "0:a"]); }
    let decoded = decode.args(["-f", "null", "-"])
        .output().map_err(|e| e.to_string())?;
    if !decoded.status.success() { return Err(String::from_utf8_lossy(&decoded.stderr).into_owned()); }
    println!("[PASS] native screen recording, pause/resume, MP4 finalization, and playback decode");
    if with_mic { println!("[PASS] microphone audio track decoded"); }
    Ok(())
}
