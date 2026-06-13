use std::io::Read;
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use std::process::{Child, ChildStdout, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub struct CameraStream {
    child: Mutex<Child>,
    stdout: Mutex<ChildStdout>,
    buf: Mutex<Vec<u8>>,
}

pub fn open(label: &str) -> Result<CameraStream, String> {
    let camera = resolve_camera_label(label)?;
    let ffmpeg = crate::ffmpeg::find_ffmpeg()?;
    let mut command = Command::new(ffmpeg);
    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000);
    let mut child = command
        .args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "dshow",
            "-i",
            &format!("video={camera}"),
            "-an",
            "-vf",
            "fps=15,scale=640:-2",
            "-q:v",
            "5",
            "-f",
            "mjpeg",
            "pipe:1",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("could not start ffmpeg camera stream: {e}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "ffmpeg camera stream did not expose stdout".to_string())?;
    Ok(CameraStream { child: Mutex::new(child), stdout: Mutex::new(stdout), buf: Mutex::new(Vec::new()) })
}

pub fn open_with_retry(label: &str, attempts: u32, delay_ms: u64) -> Result<CameraStream, String> {
    let mut last = String::new();
    for i in 0..attempts {
        match open(label) {
            Ok(s) => return Ok(s),
            Err(e) => {
                last = e;
                if i + 1 < attempts {
                    std::thread::sleep(Duration::from_millis(delay_ms));
                }
            }
        }
    }
    Err(last)
}

impl CameraStream {
    pub fn next_jpeg(&self) -> Option<Vec<u8>> {
        self.next_jpeg_timeout(5000)
    }

    pub fn next_jpeg_timeout(&self, timeout_ms: u64) -> Option<Vec<u8>> {
        let deadline = Instant::now() + Duration::from_millis(timeout_ms);
        let mut scratch = [0u8; 8192];
        loop {
            {
                let mut buf = self.buf.lock().ok()?;
                if let Some(frame) = pop_jpeg(&mut buf) {
                    return Some(frame);
                }
            }
            if Instant::now() >= deadline {
                return None;
            }
            let n = self.stdout.lock().ok()?.read(&mut scratch).ok()?;
            if n == 0 {
                return None;
            }
            self.buf.lock().ok()?.extend_from_slice(&scratch[..n]);
        }
    }
}

impl Drop for CameraStream {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn pop_jpeg(buf: &mut Vec<u8>) -> Option<Vec<u8>> {
    let start = buf.windows(2).position(|w| w == [0xff, 0xd8])?;
    if start > 0 {
        buf.drain(..start);
    }
    let end = buf.windows(2).position(|w| w == [0xff, 0xd9])? + 2;
    Some(buf.drain(..end).collect())
}

fn resolve_camera_label(label: &str) -> Result<String, String> {
    crate::record::recorder::resolve_capture_device("videoinput", label)
        .ok_or_else(|| "no camera found".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pops_complete_jpeg_and_keeps_tail() {
        let mut buf = vec![1, 2, 0xff, 0xd8, 9, 8, 0xff, 0xd9, 7];
        assert_eq!(pop_jpeg(&mut buf), Some(vec![0xff, 0xd8, 9, 8, 0xff, 0xd9]));
        assert_eq!(buf, vec![7]);
    }
}
