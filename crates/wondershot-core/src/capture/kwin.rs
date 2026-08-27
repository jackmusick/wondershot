#[cfg(target_os = "linux")]
use std::collections::HashMap;

#[cfg(target_os = "linux")]
fn qimage_to_rgba(
    bytes: &[u8],
    width: u32,
    height: u32,
    stride: usize,
    format: u32,
) -> Result<Vec<u8>, String> {
    let row_bytes = width as usize * 4;
    let expected = stride
        .checked_mul(height as usize)
        .ok_or_else(|| "KWin capture dimensions overflowed".to_string())?;
    if bytes.len() < expected {
        return Err(format!(
            "KWin capture was truncated ({} of {expected} bytes)",
            bytes.len()
        ));
    }
    if stride < row_bytes {
        return Err("KWin capture stride is smaller than its image width".into());
    }

    let mut rgba = Vec::with_capacity(row_bytes * height as usize);
    for row in bytes[..expected].chunks_exact(stride) {
        let row = &row[..row_bytes];
        match format {
            // QImage RGB32 / ARGB32 / ARGB32_Premultiplied are BGRA in memory
            // on the little-endian Linux systems supported by KWin.
            4 | 5 | 6 => {
                for pixel in row.chunks_exact(4) {
                    rgba.extend_from_slice(&[pixel[2], pixel[1], pixel[0], pixel[3]]);
                }
            }
            // QImage RGBX8888 / RGBA8888 / RGBA8888_Premultiplied are already
            // byte-ordered RGBA.
            16 | 17 | 18 => rgba.extend_from_slice(row),
            other => return Err(format!("unsupported KWin QImage format {other}")),
        }
    }
    Ok(rgba)
}

/// Capture KWin's complete logical workspace directly into a PNG. KWin writes
/// raw QImage bytes to the supplied pipe and returns their layout as metadata.
/// This gives Wondershot a frozen frame without starting Spectacle or asking
/// the portal to provide its own picker.
#[cfg(target_os = "linux")]
pub async fn capture_workspace(path: &std::path::Path, cursor: bool) -> Result<(), String> {
    use std::io::Read;
    use std::os::fd::AsFd;
    use zbus::zvariant::{Fd, OwnedValue, Value};

    let (read_fd, write_fd) = rustix::pipe::pipe().map_err(|error| error.to_string())?;
    let connection = zbus::Connection::session()
        .await
        .map_err(|error| format!("could not connect to the KDE session bus: {error}"))?;
    let proxy = zbus::Proxy::new(
        &connection,
        "org.kde.KWin.ScreenShot2",
        "/org/kde/KWin/ScreenShot2",
        "org.kde.KWin.ScreenShot2",
    )
    .await
    .map_err(|error| format!("KWin screenshot service is unavailable: {error}"))?;

    let mut options: HashMap<&str, Value<'_>> = HashMap::new();
    options.insert("include-cursor", cursor.into());
    options.insert("native-resolution", false.into());
    let metadata: HashMap<String, OwnedValue> = proxy
        .call(
            "CaptureWorkspace",
            &(options, Fd::from(write_fd.as_fd())),
        )
        .await
        .map_err(|error| format!("KWin workspace capture failed: {error}"))?;
    drop(write_fd);

    let number = |key: &str| -> Result<u32, String> {
        metadata
            .get(key)
            .ok_or_else(|| format!("KWin capture omitted {key} metadata"))
            .and_then(|value| {
                u32::try_from(value)
                    .map_err(|_| format!("KWin returned invalid {key} metadata"))
            })
    };
    let width = number("width")?;
    let height = number("height")?;
    let stride = number("stride")? as usize;
    let format = number("format")?;
    let expected = stride
        .checked_mul(height as usize)
        .ok_or_else(|| "KWin capture dimensions overflowed".to_string())?;

    let bytes = tokio::task::spawn_blocking(move || {
        let mut file = std::fs::File::from(read_fd);
        let mut bytes = Vec::with_capacity(expected);
        file.read_to_end(&mut bytes).map_err(|error| error.to_string())?;
        Ok::<_, String>(bytes)
    })
    .await
    .map_err(|error| format!("KWin capture reader failed: {error}"))??;
    let rgba = qimage_to_rgba(&bytes, width, height, stride, format)?;
    let image = image::RgbaImage::from_raw(width, height, rgba)
        .ok_or_else(|| "KWin returned an invalid image buffer".to_string())?;
    image.save(path).map_err(|error| error.to_string())
}

/// Parse KWin's `"x,y,w,h"` callback. None for wrong arity, non-numeric, or w/h <= 0. Floats truncate.
pub fn parse_geometry_reply(text: &str) -> Option<(i64, i64, i64, i64)> {
    let parts: Vec<&str> = text.split(',').collect();
    if parts.len() != 4 {
        return None;
    }
    let nums: Option<Vec<i64>> = parts
        .iter()
        .map(|p| p.trim().parse::<f64>().ok().map(|f| f as i64))
        .collect();
    let n = nums?;
    let (x, y, w, h) = (n[0], n[1], n[2], n[3]);
    if w <= 0 || h <= 0 {
        return None;
    }
    Some((x, y, w, h))
}

/// Map a logical rect into a fullscreen image's pixel space (HiDPI-aware). None if empty after clamp.
pub fn map_global_rect(
    rect: (i64, i64, i64, i64),
    virtual_rect: (i64, i64, i64, i64),
    img_w: i64,
    img_h: i64,
) -> Option<(i64, i64, i64, i64)> {
    let (rx, ry, rw, rh) = rect;
    let (vx, vy, vw, vh) = virtual_rect;
    if vw <= 0 || vh <= 0 || img_w <= 0 || img_h <= 0 {
        return None;
    }
    let sx = img_w as f64 / vw as f64;
    let sy = img_h as f64 / vh as f64;
    let mx = ((rx - vx) as f64 * sx).round() as i64;
    let my = ((ry - vy) as f64 * sy).round() as i64;
    let mw = (rw as f64 * sx).round() as i64;
    let mh = (rh as f64 * sy).round() as i64;
    let x0 = mx.max(0);
    let y0 = my.max(0);
    let x1 = (mx + mw).min(img_w);
    let y1 = (my + mh).min(img_h);
    if x1 <= x0 || y1 <= y0 {
        return None;
    }
    Some((x0, y0, x1 - x0, y1 - y0))
}

/// KWin geometry JS (matches kwin.py:build_geometry_script).
pub fn build_geometry_script(service: &str, path: &str, iface: &str, method: &str) -> String {
    format!(
        "var w = workspace.activeWindow || workspace.activeClient;\n\
         if (w && w.frameGeometry) {{\n\
         \x20   var g = w.frameGeometry;\n\
         \x20   callDBus(\"{service}\", \"{path}\", \"{iface}\", \"{method}\",\n\
         \x20            \"\" + g.x + \",\" + g.y + \",\" + g.width + \",\" + g.height);\n\
         }} else {{\n\
         \x20   callDBus(\"{service}\", \"{path}\", \"{iface}\", \"{method}\", \"\");\n\
         }}\n"
    )
}

/// Crop the image at `path` in place to a global rect. False = left unchanged.
pub fn crop_file_to_global_rect(
    path: &std::path::Path,
    rect: (i64, i64, i64, i64),
    virtual_rect: (i64, i64, i64, i64),
) -> bool {
    let Ok(img) = image::open(path) else {
        return false;
    };
    let (iw, ih) = (img.width() as i64, img.height() as i64);
    let Some((x, y, w, h)) = map_global_rect(rect, virtual_rect, iw, ih) else {
        return false;
    };
    let cropped = img.crop_imm(x as u32, y as u32, w as u32, h as u32);
    cropped.save(path).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_geometry_reply_handles_floats_negatives_and_rejects_bad() {
        assert_eq!(parse_geometry_reply("10,20,300,400"), Some((10, 20, 300, 400)));
        assert_eq!(parse_geometry_reply("-5,0,800,600"), Some((-5, 0, 800, 600)));
        assert_eq!(parse_geometry_reply("1.0,2.0,3.0,4.0"), Some((1, 2, 3, 4)));
        assert_eq!(parse_geometry_reply(""), None);
        assert_eq!(parse_geometry_reply("1,2,3"), None);
        assert_eq!(parse_geometry_reply("1,2,0,400"), None);
        assert_eq!(parse_geometry_reply("a,b,c,d"), None);
    }

    #[test]
    fn map_global_rect_scales_translates_clamps() {
        let m = map_global_rect((100, 100, 200, 200), (0, 0, 1000, 1000), 2000, 2000);
        assert_eq!(m, Some((200, 200, 400, 400)));
        let m2 = map_global_rect((-100, 0, 50, 50), (-100, 0, 1000, 1000), 1000, 1000);
        assert_eq!(m2, Some((0, 0, 50, 50)));
        assert_eq!(map_global_rect((5000, 5000, 10, 10), (0, 0, 1000, 1000), 1000, 1000), None);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn converts_kwin_bgra_and_ignores_row_padding() {
        let bytes = [3, 2, 1, 255, 7, 6, 5, 255, 99, 99, 99, 99];
        assert_eq!(
            qimage_to_rgba(&bytes, 2, 1, 12, 4).unwrap(),
            [1, 2, 3, 255, 5, 6, 7, 255]
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn preserves_kwin_rgba_bytes() {
        let bytes = [1, 2, 3, 4];
        assert_eq!(qimage_to_rgba(&bytes, 1, 1, 4, 17).unwrap(), bytes);
    }
}
