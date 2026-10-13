#![cfg(target_os = "macos")]

use std::{process::Command, sync::{Arc, Mutex}, time::Duration};
use wondershot_core::{ffmpeg::find_ffmpeg, record::recorder::{Recorder, RecEvent}};

// These use real FFmpeg and playable files, without taking over the screen,
// requesting camera/microphone access, or writing to the user's library.
fn record(paused_stop: bool) {
    let dir = tempfile::tempdir().unwrap();
    let tmp = dir.path().join("recording.tmp.mp4");
    let out = dir.path().join("recording.mp4");
    let args = ["-y", "-re", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", tmp.to_str().unwrap()].join("\n");
    let events = Arc::new(Mutex::new(Vec::new()));
    let received = events.clone();
    let rec = Recorder::launch(&args, tmp, out.clone(), move |event| received.lock().unwrap().push(event)).unwrap();
    std::thread::sleep(Duration::from_millis(1200));
    rec.pause();
    let segment = dir.path().join("recording.tmp.segment-0.mp4");
    let size = std::fs::metadata(&segment).unwrap().len();
    let mut expected_frames = frame_count(&segment);
    std::thread::sleep(Duration::from_millis(1200));
    assert_eq!(std::fs::metadata(&segment).unwrap().len(), size, "pause must stop capturing");
    if !paused_stop {
        rec.resume(); std::thread::sleep(Duration::from_millis(1200)); rec.pause();
        expected_frames += frame_count(&dir.path().join("recording.tmp.segment-1.mp4"));
    }
    rec.stop();
    let events = events.lock().unwrap();
    assert!(events.iter().any(|e| matches!(e, RecEvent::Finished(p) if p == &out)), "{events:?}");
    assert!(!events.iter().any(|e| matches!(e, RecEvent::Failed(_))), "{events:?}");
    let frames = frame_count(&out);
    assert!(frames > 0 && frames.abs_diff(expected_frames) <= 1,
        "combined file has {frames} frames; active segments contain {expected_frames}");
}

fn frame_count(path: &std::path::Path) -> usize {
    let decoded = Command::new(find_ffmpeg().unwrap()).args(["-v", "error", "-i"]).arg(path)
        .args(["-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]).output().unwrap();
    assert!(decoded.status.success(), "{}", String::from_utf8_lossy(&decoded.stderr));
    decoded.stdout.len() / (160 * 120 * 3)
}

#[test]
#[ignore = "real FFmpeg integration; run with cargo test -p wondershot-core --test macos_media_smoke -- --ignored"]
fn recording_pause_resume_produces_playable_active_time_only() { record(false); }

#[test]
#[ignore = "real FFmpeg integration"]
fn recording_can_stop_while_paused() { record(true); }

fn ffmpeg_run(args: Vec<String>) {
    let result = Command::new(find_ffmpeg().unwrap()).args(args).output().unwrap();
    assert!(result.status.success(), "{}", String::from_utf8_lossy(&result.stderr));
}

#[test]
#[ignore = "real FFmpeg video processing integration"]
fn video_trim_frame_gif_and_timed_redaction_produce_valid_media() {
    use wondershot_core::video;
    use image::AnimationDecoder;
    let dir = tempfile::tempdir().unwrap();
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../static/fixtures/video.mp4");
    let src = source.to_str().unwrap();
    let frame = dir.path().join("frame.png");
    ffmpeg_run(video::build_frame_grab_args(src, 1.0, frame.to_str().unwrap()));
    let baseline = image::open(&frame).unwrap().to_rgb8();
    assert_eq!(baseline.dimensions(), (320, 180));

    let trimmed = dir.path().join("trim.mp4");
    ffmpeg_run(video::build_trim_args(src, 1.0, 2.0, trimmed.to_str().unwrap(), true, "libx264"));
    let decoded = Command::new(find_ffmpeg().unwrap()).args(["-v", "error", "-i"]).arg(&trimmed)
        .args(["-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]).output().unwrap();
    assert!(decoded.status.success());
    assert_eq!(decoded.stdout.len() / (320 * 180 * 3), 10, "trim must contain exactly one second");

    let gif = dir.path().join("range.gif");
    ffmpeg_run(video::build_gif_args(src, gif.to_str().unwrap(), 5, 160, Some(1.0), Some(3.0)));
    let decoder = image::codecs::gif::GifDecoder::new(std::io::BufReader::new(std::fs::File::open(gif).unwrap())).unwrap();
    let frames = decoder.into_frames().collect_frames().unwrap();
    assert_eq!(frames.len(), 10);
    assert_eq!(frames[0].buffer().dimensions(), (160, 90));

    let redacted = dir.path().join("blur.mp4");
    let (graph, label) = video::build_blur_filter(&[video::Redaction { x: 40, y: 40, w: 100, h: 80, start: 0.5, end: 1.5 }], 8, 320, 180);
    ffmpeg_run(vec!["-y".into(), "-i".into(), src.into(), "-filter_complex".into(), graph, "-map".into(), format!("[{label}]"), "-c:v".into(), "libx264".into(), "-crf".into(), "0".into(), redacted.to_str().unwrap().into()]);
    let blurred_frame = dir.path().join("blurred.png");
    ffmpeg_run(video::build_frame_grab_args(redacted.to_str().unwrap(), 1.0, blurred_frame.to_str().unwrap()));
    let blurred = image::open(blurred_frame).unwrap().to_rgb8();
    let difference = |x0: u32, y0: u32, w: u32, h: u32| -> f64 {
        let sum: u64 = (y0..y0+h).flat_map(|y| (x0..x0+w).map(move |x| (x,y))).map(|(x,y)| {
            baseline.get_pixel(x,y).0.iter().zip(blurred.get_pixel(x,y).0).map(|(a,b)| a.abs_diff(b) as u64).sum::<u64>()
        }).sum();
        sum as f64 / (w*h*3) as f64
    };
    assert!(difference(40, 40, 100, 80) > 5.0, "selected region must be visibly blurred");
    assert!(difference(200, 40, 100, 80) < 3.0, "unselected region must stay intact");
    let outside_frame = dir.path().join("outside.png");
    ffmpeg_run(video::build_frame_grab_args(redacted.to_str().unwrap(), 2.0, outside_frame.to_str().unwrap()));
    ffmpeg_run(video::build_frame_grab_args(src, 2.0, frame.to_str().unwrap()));
    let original = image::open(frame).unwrap().to_rgb8();
    let outside = image::open(outside_frame).unwrap().to_rgb8();
    let average = original.as_raw().iter().zip(outside.as_raw()).map(|(a,b)| a.abs_diff(*b) as f64).sum::<f64>() / original.as_raw().len() as f64;
    assert!(average < 3.0, "blur must stop outside its selected time span: {average}");
}
