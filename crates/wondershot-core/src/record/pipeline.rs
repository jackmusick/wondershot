//! Pure GStreamer pipeline-description builder.
//!
//! Ports `wondershot/record.py:build_pipeline_description` VERBATIM — the exact
//! `gst-launch`-style string. No GStreamer dependency: this is pure string
//! building, runnable on every platform.

/// Options controlling the recording pipeline. Mirrors the keyword arguments of
/// the Python `build_pipeline_description`.
#[derive(Debug, Clone, Default)]
pub struct PipelineOpts {
    pub mic_enabled: bool,
    pub mic_device: String,
    pub noise_suppression: bool,
    pub have_webrtcdsp: bool,
    /// (left, top, right, bottom) crop borders, already resolved to insets.
    pub crop: Option<(u32, u32, u32, u32)>,
    pub halo: bool,
}

/// Build the `Gst.parse_launch` pipeline string.
///
/// Ports `record.py:build_pipeline_description` verbatim. PURE — no Gst, no
/// portal, no I/O.
///
/// The `videorate ! video/x-raw,format=I420,framerate=30/1` segment is the
/// no-PTS landmine fix and is kept VERBATIM. `identity name=pause` is the C1
/// pause tap and MUST sit on RAW frames BEFORE `x264enc`.
pub fn build_pipeline_description(fd: i32, node: u32, tmp: &str, opts: &PipelineOpts) -> String {
    // crop: insets, inserted right after `videoconvert ! `, before videorate.
    let crop_seg = match opts.crop {
        Some((left, top, right, bottom)) => format!(
            "videocrop top={top} left={left} right={right} bottom={bottom} ! "
        ),
        None => String::new(),
    };
    // cairooverlay needs an alpha-capable format; wrap it in videoconvert.
    let halo_seg = if opts.halo {
        "videoconvert ! cairooverlay name=halo ! "
    } else {
        ""
    };

    let video = format!(
        "pipewiresrc fd={fd} path={node} do-timestamp=true ! \
         queue ! videoconvert ! \
         {crop_seg}\
         videorate ! video/x-raw,format=I420,framerate=30/1 ! \
         identity name=pause ! \
         {halo_seg}\
         x264enc speed-preset=veryfast tune=zerolatency \
         bitrate=8000 key-int-max=120 ! \
         h264parse ! queue ! mux. "
    );

    let mut audio = String::new();
    if opts.mic_enabled {
        // mic_device is already the resolved pulse device string (or empty).
        let dev = if opts.mic_device.is_empty() {
            String::new()
        } else {
            format!("device={} ", opts.mic_device)
        };
        let dsp = if opts.noise_suppression && opts.have_webrtcdsp {
            "audio/x-raw,rate=48000,channels=1 ! webrtcdsp \
             echo-cancel=false noise-suppression=true \
             noise-suppression-level=very-high gain-control=false \
             high-pass-filter=true ! "
        } else {
            ""
        };
        audio = format!(
            "pulsesrc {dev}do-timestamp=true ! \
             queue ! audioconvert ! audioresample ! \
             {dsp}audioconvert ! avenc_aac bitrate=160000 ! \
             aacparse ! queue ! mux. "
        );
    }

    format!("{video}{audio}mp4mux name=mux ! filesink location={tmp}")
}

#[cfg(test)]
mod tests {
    use super::*;
    fn opts() -> PipelineOpts {
        PipelineOpts::default()
    }
    #[test]
    fn has_verbatim_no_pts_fix() {
        assert!(build_pipeline_description(7, 42, "/tmp/x.mp4", &opts())
            .contains("videorate ! video/x-raw,format=I420,framerate=30/1"));
    }
    #[test]
    fn pause_tap_precedes_encoder() {
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &opts());
        assert!(d.find("identity name=pause").unwrap() < d.find("x264enc").unwrap());
    }
    #[test]
    fn x264_and_sink_verbatim() {
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &opts());
        assert!(d.contains("x264enc speed-preset=veryfast tune=zerolatency bitrate=8000 key-int-max=120"));
        assert!(d.contains("mp4mux name=mux"));
        assert!(d.contains("filesink location=/tmp/x.mp4"));
        assert!(d.contains("pipewiresrc fd=7 path=42 do-timestamp=true"));
    }
    #[test]
    fn audio_included_when_mic_enabled() {
        let o = PipelineOpts { mic_enabled: true, mic_device: "alsa_input.x".into(), ..opts() };
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &o);
        assert!(d.contains("pulsesrc device=alsa_input.x do-timestamp=true"));
        assert!(d.contains("avenc_aac bitrate=160000"));
    }
    #[test]
    fn no_audio_when_mic_disabled() {
        assert!(!build_pipeline_description(7, 42, "/t.mp4", &opts()).contains("pulsesrc"));
    }
    #[test]
    fn webrtcdsp_only_when_available_and_enabled() {
        let on = PipelineOpts { mic_enabled: true, noise_suppression: true, have_webrtcdsp: true, ..opts() };
        assert!(build_pipeline_description(7, 42, "/t.mp4", &on).contains("webrtcdsp"));
        let off = PipelineOpts { mic_enabled: true, noise_suppression: true, have_webrtcdsp: false, ..opts() };
        assert!(!build_pipeline_description(7, 42, "/t.mp4", &off).contains("webrtcdsp"));
        // dsp requires BOTH noise_suppression and have_webrtcdsp
        let nosup = PipelineOpts { mic_enabled: true, noise_suppression: false, have_webrtcdsp: true, ..opts() };
        assert!(!build_pipeline_description(7, 42, "/t.mp4", &nosup).contains("webrtcdsp"));
    }
    #[test]
    fn mic_without_device_omits_device_prop() {
        let o = PipelineOpts { mic_enabled: true, mic_device: String::new(), ..opts() };
        let d = build_pipeline_description(7, 42, "/t.mp4", &o);
        assert!(d.contains("pulsesrc do-timestamp=true")); // no 'device='
    }
}
