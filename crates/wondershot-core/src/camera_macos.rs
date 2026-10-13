use std::io::Read;
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Arc, Mutex, OnceLock, Weak};
use std::time::Duration;

pub struct CameraStream {
    child: Arc<Mutex<Child>>,
    frames: Mutex<mpsc::Receiver<Vec<u8>>>,
    reader: Option<std::thread::JoinHandle<()>>,
}

static CHILDREN: OnceLock<Mutex<Vec<Weak<Mutex<Child>>>>> = OnceLock::new();

pub fn stop_all() {
    if let Ok(children) = CHILDREN.get_or_init(Default::default).lock() {
        for child in children.iter().filter_map(Weak::upgrade) {
            if let Ok(mut child) = child.lock() { let _ = child.kill(); let _ = child.wait(); }
        }
    }
}

pub fn open(label: &str) -> Result<CameraStream, String> {
    let args = crate::record::recorder::build_camera_args(label)?;
    let ffmpeg = crate::ffmpeg::find_ffmpeg()?;
    let mut child = Command::new(ffmpeg)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("could not start ffmpeg camera stream: {e}"))?;
    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| "ffmpeg camera stream did not expose stdout".to_string())?;
    let (sender, frames) = mpsc::sync_channel(2);
    let reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let mut scratch = [0u8; 8192];
        while let Ok(n) = stdout.read(&mut scratch) {
            if n == 0 { break; }
            buf.extend_from_slice(&scratch[..n]);
            while let Some(frame) = pop_jpeg(&mut buf) {
                match sender.try_send(frame) {
                    Err(mpsc::TrySendError::Disconnected(_)) => return,
                    _ => {} // Discard frames when the consumer is slower than the camera.
                }
            }
            if buf.len() > 16 * 1024 * 1024 { buf.clear(); }
        }
    });
    let child = Arc::new(Mutex::new(child));
    if let Ok(mut children) = CHILDREN.get_or_init(Default::default).lock() {
        children.retain(|child| child.strong_count() > 0);
        children.push(Arc::downgrade(&child));
    }
    Ok(CameraStream { child, frames: Mutex::new(frames), reader: Some(reader) })
}

pub fn open_with_retry(label: &str, attempts: u32, delay_ms: u64) -> Result<CameraStream, String> {
    let mut last = String::new();
    for i in 0..attempts {
        match open(label) {
            Ok(stream) => return Ok(stream),
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
        self.frames.lock().ok()?.recv_timeout(Duration::from_millis(timeout_ms)).ok()
    }
}

impl Drop for CameraStream {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
        if let Some(reader) = self.reader.take() { let _ = reader.join(); }
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
