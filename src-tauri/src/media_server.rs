//! Loopback HTTP media streamer for the video player.
//!
//! WebKitGTK renders `<video>` through GStreamer, whose HTTP source element
//! only speaks http(s) — it cannot read Tauri's `asset://` custom scheme, so
//! a `<video src="asset://…">` fails with MEDIA_ERR_SRC_NOT_SUPPORTED even
//! though `fetch()` on the same URL works (fetch rides WebKit's network layer
//! where the scheme handler is registered). The standard fix: serve media
//! over 127.0.0.1 with Range support.
//!
//! Security posture: binds loopback only, serves GET only, and only files
//! that live inside the user's configured library dirs (canonicalized prefix
//! check per request — the dirs are re-read so settings changes apply).

use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;
use wondershot_core::settings::Settings;

/// Managed state: the bound port (0 = server failed to start).
pub struct MediaServer(pub u16);

#[tauri::command]
pub fn media_server_port(state: tauri::State<MediaServer>) -> u16 {
    state.0
}

fn content_type(path: &str) -> &'static str {
    match path.rsplit('.').next().map(|e| e.to_ascii_lowercase()).as_deref() {
        Some("mp4") | Some("m4v") => "video/mp4",
        Some("webm") => "video/webm",
        Some("mkv") => "video/x-matroska",
        Some("mov") => "video/quicktime",
        Some("avi") => "video/x-msvideo",
        Some("gif") => "image/gif",
        _ => "application/octet-stream",
    }
}

/// Is `path` inside one of the (canonicalized) library dirs?
fn allowed(path: &PathBuf) -> bool {
    let Ok(real) = path.canonicalize() else { return false };
    Settings::load()
        .library_dirs()
        .iter()
        .filter_map(|d| PathBuf::from(d).canonicalize().ok())
        .any(|d| real.starts_with(&d))
}

/// Parse a `bytes=start-end` Range header against `len`. Returns (start, end_inclusive).
fn parse_range(raw: &str, len: u64) -> Option<(u64, u64)> {
    let spec = raw.trim().strip_prefix("bytes=")?;
    // Single range only (gst/webkit send one); multipart isn't worth it.
    let (a, b) = spec.split_once('-')?;
    match (a.is_empty(), b.is_empty()) {
        (false, true) => {
            let start: u64 = a.parse().ok()?;
            (start < len).then(|| (start, len - 1))
        }
        (false, false) => {
            let start: u64 = a.parse().ok()?;
            let end: u64 = b.parse().ok()?;
            (start <= end && start < len).then(|| (start, end.min(len - 1)))
        }
        (true, false) => {
            let suffix: u64 = b.parse().ok()?;
            let start = len.saturating_sub(suffix);
            (len > 0).then(|| (start, len - 1))
        }
        (true, true) => None,
    }
}

/// Start the streamer on an ephemeral loopback port; returns the port.
pub fn start() -> u16 {
    let server = match tiny_http::Server::http("127.0.0.1:0") {
        Ok(s) => s,
        Err(e) => {
            eprintln!("media server unavailable: {e}");
            return 0;
        }
    };
    let port = match server.server_addr().to_ip() {
        Some(a) => a.port(),
        None => return 0,
    };

    // GStreamer holds several keep-alive connections at once (a probe + the
    // actual stream); a single sequential accept loop deadlocks playback, so
    // run a small worker pool.
    let server = std::sync::Arc::new(server);
    for _ in 0..4 {
        let server = server.clone();
        std::thread::spawn(move || loop {
            let request = match server.recv() {
                Ok(r) => r,
                Err(_) => break,
            };
            handle(request);
        });
    }

    port
}

/// Each new /camera request bumps this; older streams notice and end, so the
/// (exclusive) v4l2 device is released for the newcomer instead of the two
/// fighting over it.
static CAMERA_GEN: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Streams MJPEG parts from a backend camera pipeline. tiny_http pulls this
/// Reader until the client disconnects; dropping it tears the pipeline down.
struct MjpegReader {
    stream: wondershot_core::camera::CameraStream,
    buf: Vec<u8>,
    pos: usize,
    generation: u64,
}

impl std::io::Read for MjpegReader {
    fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
        use std::sync::atomic::Ordering;
        while self.pos >= self.buf.len() {
            // A newer stream superseded this one → end promptly (frees the cam).
            if CAMERA_GEN.load(Ordering::SeqCst) != self.generation {
                return Ok(0);
            }
            // Short pulls so supersession is noticed fast; tolerate brief
            // gaps (exposure adjustments etc.) before declaring the cam gone.
            let mut misses = 0u32;
            let jpeg = loop {
                match self.stream.next_jpeg_timeout(500) {
                    Some(j) => break Some(j),
                    None => {
                        misses += 1;
                        if CAMERA_GEN.load(Ordering::SeqCst) != self.generation || misses >= 8 {
                            break None;
                        }
                    }
                }
            };
            let Some(jpeg) = jpeg else {
                return Ok(0); // superseded or ~4s of silence → end the stream
            };
            self.buf = format!(
                "--wsframe\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\n\r\n",
                jpeg.len()
            )
            .into_bytes();
            self.buf.extend_from_slice(&jpeg);
            self.buf.extend_from_slice(b"\r\n");
            self.pos = 0;
        }
        let n = (self.buf.len() - self.pos).min(out.len());
        out[..n].copy_from_slice(&self.buf[self.pos..self.pos + n]);
        self.pos += n;
        Ok(n)
    }
}

/// `/camera?label=<urlencoded gst display name>` → live MJPEG of that camera
/// (empty label = first available). Runs on its own thread — the stream lives
/// as long as the bubble's <img> keeps the connection open, and must not
/// occupy a worker-pool slot.
fn camera_handle(request: tiny_http::Request) {
    let url = request.url().to_string();
    let label = url
        .split_once("label=")
        .map(|(_, v)| urlencoding_decode(v.split('&').next().unwrap_or(v)))
        .unwrap_or_default();
    let generation = CAMERA_GEN.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1;
    // Retry across the previous stream's release window (≤ ~4s worst case).
    match wondershot_core::camera::open_with_retry(&label, 15, 350) {
        Ok(stream) => {
            let ctype = tiny_http::Header::from_bytes(
                &b"Content-Type"[..],
                &b"multipart/x-mixed-replace; boundary=wsframe"[..],
            )
            .unwrap();
            let reader = MjpegReader { stream, buf: Vec::new(), pos: 0, generation };
            let _ = request.respond(tiny_http::Response::new(
                tiny_http::StatusCode(200),
                vec![ctype],
                Box::new(reader) as Box<dyn std::io::Read + Send>,
                None, // chunked — the stream has no length
                None,
            ));
        }
        Err(e) => {
            eprintln!("camera stream unavailable: {e}");
            let _ = request.respond(tiny_http::Response::empty(503));
        }
    }
}

fn handle(request: tiny_http::Request) {
    // Camera streams are long-lived: hand them their own thread instead of
    // pinning a worker-pool slot for the bubble's whole lifetime.
    if request.url().starts_with("/camera") {
        std::thread::spawn(move || camera_handle(request));
        return;
    }
    // ?path=<urlencoded absolute path>
    let url = request.url().to_string();
    let path = url
        .split_once("path=")
        .map(|(_, v)| v.split('&').next().unwrap_or(v))
        .map(urlencoding_decode)
        .unwrap_or_default();
    let pb = PathBuf::from(&path);

    if !matches!(request.method(), tiny_http::Method::Get) || !allowed(&pb) {
        let _ = request.respond(tiny_http::Response::empty(403));
        return;
    }
    let Ok(mut f) = std::fs::File::open(&pb) else {
        let _ = request.respond(tiny_http::Response::empty(404));
        return;
    };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    let ctype =
        tiny_http::Header::from_bytes(&b"Content-Type"[..], content_type(&path).as_bytes()).unwrap();
    let accept = tiny_http::Header::from_bytes(&b"Accept-Ranges"[..], &b"bytes"[..]).unwrap();

    let range = request
        .headers()
        .iter()
        .find(|h| h.field.equiv("Range"))
        .and_then(|h| parse_range(h.value.as_str(), len));

    let response = match range {
        Some((start, end)) => {
            if f.seek(SeekFrom::Start(start)).is_err() {
                let _ = request.respond(tiny_http::Response::empty(500));
                return;
            }
            let n = end - start + 1;
            let crange = tiny_http::Header::from_bytes(
                &b"Content-Range"[..],
                format!("bytes {start}-{end}/{len}").as_bytes(),
            )
            .unwrap();
            tiny_http::Response::new(
                tiny_http::StatusCode(206),
                vec![ctype, accept, crange],
                Box::new(f.take(n)) as Box<dyn Read + Send>,
                Some(n as usize),
                None,
            )
        }
        None => tiny_http::Response::new(
            tiny_http::StatusCode(200),
            vec![ctype, accept],
            Box::new(f) as Box<dyn Read + Send>,
            Some(len as usize),
            None,
        ),
    };
    let _ = request.respond(response);
}

/// Minimal %XX decoder (std has no urlencoding; the only non-trivial chars in
/// our own URLs are %2F and friends from encodeURIComponent).
fn urlencoding_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() + 1 && i + 2 < bytes.len() + 1 {
            if let (Some(h), Some(l)) = (
                bytes.get(i + 1).and_then(|b| (*b as char).to_digit(16)),
                bytes.get(i + 2).and_then(|b| (*b as char).to_digit(16)),
            ) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        }
        out.push(if bytes[i] == b'+' { b' ' } else { bytes[i] });
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn range_parsing() {
        assert_eq!(parse_range("bytes=0-99", 1000), Some((0, 99)));
        assert_eq!(parse_range("bytes=500-", 1000), Some((500, 999)));
        assert_eq!(parse_range("bytes=-100", 1000), Some((900, 999)));
        assert_eq!(parse_range("bytes=0-9999", 1000), Some((0, 999)));
        assert_eq!(parse_range("bytes=1000-", 1000), None);
        assert_eq!(parse_range("bogus", 1000), None);
    }

    #[test]
    fn urldecode() {
        assert_eq!(urlencoding_decode("%2Fhome%2Fjack%2Fa%20b.mp4"), "/home/jack/a b.mp4");
        assert_eq!(urlencoding_decode("plain"), "plain");
    }
}
