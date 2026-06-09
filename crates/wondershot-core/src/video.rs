//! Pure ffmpeg argument and filter-graph builders — no ffmpeg dependency.
//!
//! Ports the string-building helpers from `wondershot/video.py`
//! (`build_blur_filter`, `build_gif_args`, `build_frame_grab_args`,
//! `build_trim_args`, and the output-name helpers). All functions build
//! arguments/strings only; running ffmpeg lives elsewhere.

use serde::{Deserialize, Serialize};

/// A blur region active for a span of the video, in video pixel coords.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Redaction {
    pub x: i64,
    pub y: i64,
    pub w: i64,
    pub h: i64,
    pub start: f64,
    pub end: f64,
}

/// ffmpeg `filter_complex` applying each redaction as a blurred overlay
/// enabled only inside its time range. Returns `(graph, output_label)`.
///
/// Verbatim port of `video.py::build_blur_filter`: a `split` feeds one
/// copy per redaction, each cropped + boxblurred and overlaid back onto
/// the running result, gated by `between(t, start, end)`.
pub fn build_blur_filter(
    redactions: &[Redaction],
    blur: i64,
    video_w: i64,
    video_h: i64,
) -> (String, String) {
    let n = redactions.len();
    let splits: String = (0..n).map(|i| format!("[c{i}]")).collect();
    let mut parts: Vec<String> = vec![format!("[0:v]split={}[base]{}", n + 1, splits)];
    let mut cur = String::from("base");
    for (i, r) in redactions.iter().enumerate() {
        let mut x = r.x.max(0);
        let mut y = r.y.max(0);
        let mut w = r.w;
        let mut h = r.h;
        if video_w != 0 && video_h != 0 {
            // clamp to frame
            x = x.min(video_w - 4);
            y = y.min(video_h - 4);
            w = w.min(video_w - x);
            h = h.min(video_h - y);
        }
        // encoders want even dims
        w = (4).max(w - w % 2);
        h = (4).max(h - h % 2);
        x -= x % 2;
        y -= y % 2;
        parts.push(format!("[c{i}]crop={w}:{h}:{x}:{y},boxblur={blur}[b{i}]"));
        let out = format!("v{i}");
        parts.push(format!(
            "[{cur}][b{i}]overlay={x}:{y}:enable='between(t,{:.3},{:.3})'[{out}]",
            r.start, r.end
        ));
        cur = out;
    }
    (parts.join(";"), cur)
}

/// ffmpeg args extracting one frame at `position_s` seconds.
pub fn build_frame_grab_args(src: &str, position_s: f64, out: &str) -> Vec<String> {
    vec![
        "-y".into(),
        "-ss".into(),
        format!("{:.3}", position_s),
        "-i".into(),
        src.into(),
        "-frames:v".into(),
        "1".into(),
        out.into(),
    ]
}

/// ffmpeg args trimming `src` to `[start, end]`.
///
/// Both `-ss` and `-to` are INPUT options (before `-i`), so both are
/// absolute source timestamps. Stream copy snaps the start to the previous
/// keyframe; re-encode cuts exactly.
pub fn build_trim_args(
    src: &str,
    start: f64,
    end: f64,
    out: &str,
    reencode: bool,
    encoder: &str,
) -> Vec<String> {
    let mut args: Vec<String> = vec![
        "-y".into(),
        "-ss".into(),
        format!("{:.3}", start),
        "-to".into(),
        format!("{:.3}", end),
        "-i".into(),
        src.into(),
    ];
    if reencode {
        let enc_opts: Vec<String> = if encoder == "libx264" {
            vec!["-crf".into(), "20".into(), "-preset".into(), "veryfast".into()]
        } else {
            vec!["-q:v".into(), "4".into()]
        };
        args.push("-c:v".into());
        args.push(encoder.into());
        args.extend(enc_opts);
        args.extend(["-c:a".into(), "aac".into(), "-b:a".into(), "160k".into()]);
    } else {
        args.extend(["-c".into(), "copy".into()]);
    }
    if matches!(ext_lower(out).as_str(), "mp4" | "m4v" | "mov") {
        args.extend(["-movflags".into(), "+faststart".into()]); // instant seeking
    }
    args.push(out.into());
    args
}

/// ffmpeg args for the two-pass palette GIF convert.
///
/// `-ss`/`-to` are INPUT options (before `-i`): absolute source timestamps.
/// scale never upsizes (`min(max_width, iw)`) and lanczos keeps text legible.
/// The range is applied only when both ends are given.
pub fn build_gif_args(
    src: &str,
    out: &str,
    fps: i64,
    max_width: i64,
    start: Option<f64>,
    end: Option<f64>,
) -> Vec<String> {
    let mut args: Vec<String> = vec!["-y".into()];
    if let (Some(s), Some(e)) = (start, end) {
        args.extend(["-ss".into(), format!("{:.3}", s), "-to".into(), format!("{:.3}", e)]);
    }
    let vf = format!(
        "fps={fps},scale='min({max_width},iw)':-1:flags=lanczos,\
         split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    );
    args.extend(["-i".into(), src.into(), "-vf".into(), vf, out.into()]);
    args
}

// -- output-name helpers ------------------------------------------------------

/// Split a file name into `(stem, ext)` where `ext` excludes the dot.
/// Mirrors Python's `os.path.splitext` on a basename (no leading-dot files
/// here in practice).
fn split_ext(name: &str) -> (&str, &str) {
    match name.rfind('.') {
        Some(i) if i > 0 => (&name[..i], &name[i + 1..]),
        _ => (name, ""),
    }
}

fn ext_lower(name: &str) -> String {
    split_ext(name).1.to_lowercase()
}

/// `<stem>.gif` library name for a GIF export.
pub fn gif_name(src_name: &str) -> String {
    format!("{}.gif", split_ext(src_name).0)
}

/// `<stem>-frame.png` library name for a grabbed frame.
pub fn frame_name(src_name: &str) -> String {
    format!("{}-frame.png", split_ext(src_name).0)
}

/// `<stem>-redacted.<ext>` library name for a blurred video (keeps ext).
pub fn redacted_name(src_name: &str) -> String {
    let (stem, ext) = split_ext(src_name);
    format!("{stem}-redacted.{ext}")
}

/// `<stem>-trimmed.<ext>` library name.
///
/// Stream copy must keep the source container; re-encode is always
/// x264-family, so it always lands in `.mp4`.
pub fn trimmed_name(src_name: &str, reencode: bool) -> String {
    let (stem, ext) = split_ext(src_name);
    let ext = if reencode { "mp4" } else { ext };
    format!("{stem}-trimmed.{ext}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn single_redaction_graph() {
        let r = vec![Redaction { x: 100, y: 50, w: 200, h: 120, start: 2.0, end: 6.5 }];
        let (g, out) = build_blur_filter(&r, 14, 0, 0);
        assert!(g.contains("split=2[base][c0]"), "graph: {g}");
        assert!(g.contains("[c0]crop=200:120:100:50,boxblur=14[b0]"), "graph: {g}");
        assert!(
            g.contains("[base][b0]overlay=100:50:enable='between(t,2.000,6.500)'[v0]"),
            "graph: {g}"
        );
        assert_eq!(out, "v0");
    }

    #[test]
    fn odd_dims_rounded_even() {
        let r = vec![Redaction { x: 11, y: 7, w: 101, h: 51, start: 0.0, end: 1.0 }];
        assert!(build_blur_filter(&r, 14, 0, 0).0.contains("crop=100:50:10:6"));
    }

    #[test]
    fn multiple_redactions_chain() {
        let r = vec![
            Redaction { x: 0, y: 0, w: 10, h: 10, start: 0.0, end: 1.0 },
            Redaction { x: 20, y: 20, w: 10, h: 10, start: 1.0, end: 2.0 },
        ];
        let (g, out) = build_blur_filter(&r, 14, 0, 0);
        assert!(g.contains("split=3[base][c0][c1]"), "graph: {g}");
        assert!(
            g.contains("[v0][b1]overlay=20:20:enable='between(t,1.000,2.000)'[v1]"),
            "graph: {g}"
        );
        assert_eq!(out, "v1");
    }

    #[test]
    fn rect_clamped_to_frame() {
        // rect beyond frame is clamped (video_w=200,video_h=150)
        let r = vec![Redaction { x: 198, y: 148, w: 50, h: 50, start: 0.0, end: 1.0 }];
        let (g, _) = build_blur_filter(&r, 14, 200, 150);
        assert!(g.contains("crop="));
    }

    #[test]
    fn rect_clamped_to_frame_python_case() {
        // Exact parity with test_video_filter.py::test_rect_clamped_to_frame
        let r = vec![Redaction { x: 600, y: 340, w: 200, h: 100, start: 0.0, end: 1.0 }];
        let (g, _) = build_blur_filter(&r, 14, 640, 360);
        assert!(g.contains("crop=40:20:600:340"), "graph: {g}");
    }

    #[test]
    fn blur_strength_override() {
        let r = vec![Redaction { x: 0, y: 0, w: 10, h: 10, start: 0.0, end: 1.0 }];
        assert!(build_blur_filter(&r, 30, 0, 0).0.contains("boxblur=30"));
    }

    #[test]
    fn gif_args_with_range() {
        assert_eq!(
            build_gif_args("/in.mp4", "/out.gif", 12, 720, Some(1.0), Some(3.0)),
            vec![
                "-y",
                "-ss",
                "1.000",
                "-to",
                "3.000",
                "-i",
                "/in.mp4",
                "-vf",
                "fps=12,scale='min(720,iw)':-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                "/out.gif"
            ]
        );
    }

    #[test]
    fn gif_args_no_range() {
        let a = build_gif_args("/in.mp4", "/out.gif", 12, 720, None, None);
        assert_eq!(
            a,
            vec![
                "-y",
                "-i",
                "/in.mp4",
                "-vf",
                "fps=12,scale='min(720,iw)':-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                "/out.gif"
            ]
        );
    }

    #[test]
    fn frame_grab_args() {
        assert_eq!(
            build_frame_grab_args("/in.mp4", 2.5, "/f.png"),
            vec!["-y", "-ss", "2.500", "-i", "/in.mp4", "-frames:v", "1", "/f.png"]
        );
    }

    #[test]
    fn frame_grab_rounds_three_decimals() {
        // Parity with Python test_frame_grab_args: 12.3456 -> 12.346
        let a = build_frame_grab_args("/lib/Recording.mp4", 12.3456, "/f.png");
        assert_eq!(a[1..3], ["-ss".to_string(), "12.346".to_string()]);
    }

    #[test]
    fn trim_args_stream_copy() {
        let a = build_trim_args("/l/in.mp4", 1.0, 8.5, "/l/in-trimmed.mp4", false, "libx264");
        let i = a.iter().position(|s| s == "-i").unwrap();
        assert_eq!(&a[..i], &["-y", "-ss", "1.000", "-to", "8.500"]);
        let c = a.iter().position(|s| s == "-c").unwrap();
        assert_eq!(a[c + 1], "copy");
        assert!(a.iter().any(|s| s == "-movflags"));
        assert_eq!(a.last().unwrap(), "/l/in-trimmed.mp4");
    }

    #[test]
    fn trim_args_copy_to_webm_has_no_movflags() {
        let a = build_trim_args("/l/in.webm", 0.0, 2.0, "/l/in-trimmed.webm", false, "libx264");
        assert!(!a.iter().any(|s| s == "-movflags"));
    }

    #[test]
    fn trim_args_reencode_x264() {
        let a = build_trim_args("/l/in.webm", 0.5, 3.25, "/l/in-trimmed.mp4", true, "libx264");
        let v = a.iter().position(|s| s == "-c:v").unwrap();
        assert_eq!(a[v + 1], "libx264");
        assert!(a.iter().any(|s| s == "-crf") && a.iter().any(|s| s == "-preset"));
        let ai = a.iter().position(|s| s == "-c:a").unwrap();
        assert_eq!(a[ai + 1], "aac");
        assert!(a.iter().any(|s| s == "-movflags"));
    }

    #[test]
    fn trim_args_reencode_fallback_encoder() {
        let a = build_trim_args("/l/in.mp4", 0.0, 1.0, "/l/in-trimmed.mp4", true, "mpeg4");
        assert!(a.iter().any(|s| s == "-q:v") && !a.iter().any(|s| s == "-crf"));
    }

    #[test]
    fn output_names() {
        assert_eq!(gif_name("clip.mp4"), "clip.gif");
        assert_eq!(frame_name("clip.mp4"), "clip-frame.png");
        assert_eq!(redacted_name("clip.mp4"), "clip-redacted.mp4");
        assert_eq!(redacted_name("clip.webm"), "clip-redacted.webm");
        // trimmed_name parity with Python trim_output_name
        assert_eq!(trimmed_name("Rec.webm", false), "Rec-trimmed.webm");
        assert_eq!(trimmed_name("Rec.mp4", false), "Rec-trimmed.mp4");
        assert_eq!(trimmed_name("Rec.webm", true), "Rec-trimmed.mp4");
        assert_eq!(trimmed_name("Rec.mkv", true), "Rec-trimmed.mp4");
    }
}
