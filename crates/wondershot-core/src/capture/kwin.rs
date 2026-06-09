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
}
