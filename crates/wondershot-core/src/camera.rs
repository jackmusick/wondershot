//! Backend camera frames for the bubble: a gst pipeline producing JPEG
//! frames, streamed to the webview as MJPEG by the loopback media server.
//!
//! Why not webview `getUserMedia`: WebKitGTK's capture-portal path is
//! unreliable in the Flatpak sandbox (it aborted the web process at launch on
//! KDE/Wayland, and silently produces no frames on the same setup). The
//! sandbox already has `--device=all`, so reading the camera with GStreamer —
//! the stack the recorder uses anyway — sidesteps the webview entirely.

use gstreamer as gst;
use gstreamer_app as gst_app;

pub struct CameraStream {
    pipeline: gst::Pipeline,
    appsink: gst_app::AppSink,
}

/// Open the camera whose gst display name matches `label` (Settings stores
/// these — same enumeration as `list_capture_devices`); empty/no-match falls
/// back to the first available camera.
pub fn open(label: &str) -> Result<CameraStream, String> {
    use gst::prelude::*;
    gst::init().map_err(|e| e.to_string())?;

    // Dev affordance: a moving test pattern on camera-less machines (the dev
    // server), exercising the whole stream path minus the physical device.
    let src = if std::env::var_os("WONDERSHOT_FAKE_CAMERA").is_some() {
        gst::ElementFactory::make("videotestsrc")
            .property_from_str("pattern", "ball")
            .property("is-live", true)
            .build()
            .map_err(|e| e.to_string())?
    } else {
        let monitor = gst::DeviceMonitor::new();
        monitor.add_filter(Some("Video/Source"), None);
        monitor
            .start()
            .map_err(|e| format!("device monitor failed: {e}"))?;
        let devices: Vec<gst::Device> = monitor.devices().into_iter().collect();
        monitor.stop();

        let device = devices
            .iter()
            .find(|d| {
                let n = d.display_name();
                !label.is_empty()
                    && (n == label || n.starts_with(label) || label.starts_with(n.as_str()))
            })
            .or_else(|| devices.first());
        match device {
            Some(d) => d
                .create_element(None)
                .map_err(|e| format!("camera element failed: {e}"))?,
            None => return Err("no camera found".into()),
        }
    };

    let convert = gst::ElementFactory::make("videoconvert")
        .build()
        .map_err(|e| e.to_string())?;
    let rate = gst::ElementFactory::make("videorate")
        .build()
        .map_err(|e| e.to_string())?;
    let enc = gst::ElementFactory::make("jpegenc")
        .property("quality", 75i32)
        .build()
        .map_err(|e| e.to_string())?;
    let appsink = gst_app::AppSink::builder()
        .max_buffers(2)
        .drop(true)
        .sync(false)
        .build();

    let pipeline = gst::Pipeline::new();
    pipeline
        .add_many([&src, &convert, &rate, &enc, appsink.upcast_ref()])
        .map_err(|e| e.to_string())?;
    src.link(&convert).map_err(|_| "link src→convert failed".to_string())?;
    convert.link(&rate).map_err(|_| "link convert→rate failed".to_string())?;
    // Cap the preview at 15 fps — it's a bubble, not a recording.
    let caps = gst::Caps::builder("video/x-raw")
        .field("framerate", gst::Fraction::new(15, 1))
        .build();
    rate.link_filtered(&enc, &caps)
        .map_err(|_| "link rate→jpegenc failed".to_string())?;
    enc.link(appsink.upcast_ref::<gst::Element>())
        .map_err(|_| "link jpegenc→appsink failed".to_string())?;

    pipeline
        .set_state(gst::State::Playing)
        .map_err(|e| format!("camera pipeline would not start: {e}"))?;
    Ok(CameraStream { pipeline, appsink })
}

impl CameraStream {
    /// Block (up to 5s) for the next JPEG frame; None on timeout/EOS — the
    /// server treats that as end-of-stream.
    pub fn next_jpeg(&self) -> Option<Vec<u8>> {
        let sample = self
            .appsink
            .try_pull_sample(gst::ClockTime::from_seconds(5))?;
        let buffer = sample.buffer()?;
        let map = buffer.map_readable().ok()?;
        Some(map.as_slice().to_vec())
    }
}

impl Drop for CameraStream {
    fn drop(&mut self) {
        use gst::prelude::*;
        let _ = self.pipeline.set_state(gst::State::Null);
    }
}
