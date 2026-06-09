//! Pure pixel operations — no UI, unit-testable.
//!
//! Ports `wondershot/imageops.py` to Rust on top of the `image` crate.
//! All functions take/return `image::RgbaImage`; rects are `(x, y, w, h)`.

use image::RgbaImage;

/// Return the sub-image inside the rect `(x, y, w, h)`.
pub fn crop(img: &RgbaImage, x: u32, y: u32, w: u32, h: u32) -> RgbaImage {
    image::imageops::crop_imm(img, x, y, w, h).to_image()
}

/// Remove the band `[a, b)` along one axis and join the remaining halves.
/// `horizontal=true` removes ROWS `a..b` (height shrinks); `false` removes
/// COLUMNS (width shrinks).
pub fn cut_out(img: &RgbaImage, a: u32, b: u32, horizontal: bool) -> RgbaImage {
    let (w, h) = img.dimensions();
    if horizontal {
        let band = b.min(h).saturating_sub(a);
        let new_h = h - band;
        let mut out = RgbaImage::new(w, new_h);
        let mut dy = 0;
        for y in 0..h {
            if y >= a && y < b {
                continue;
            }
            for x in 0..w {
                out.put_pixel(x, dy, *img.get_pixel(x, y));
            }
            dy += 1;
        }
        out
    } else {
        let band = b.min(w).saturating_sub(a);
        let new_w = w - band;
        let mut out = RgbaImage::new(new_w, h);
        for y in 0..h {
            let mut dx = 0;
            for x in 0..w {
                if x >= a && x < b {
                    continue;
                }
                out.put_pixel(dx, y, *img.get_pixel(x, y));
                dx += 1;
            }
        }
        out
    }
}

/// Pixelate the rect region: downscale by `block` (averaging) then
/// nearest-upscale back. Returns a rect-sized patch.
pub fn pixelated_patch(img: &RgbaImage, rect: (u32, u32, u32, u32), block: u32) -> RgbaImage {
    let (x, y, w, h) = rect;
    let region = image::imageops::crop_imm(img, x, y, w, h).to_image();
    let block = block.max(1);
    let small_w = (w / block).max(1);
    let small_h = (h / block).max(1);
    let small = image::imageops::resize(
        &region,
        small_w,
        small_h,
        image::imageops::FilterType::Triangle,
    );
    image::imageops::resize(&small, w, h, image::imageops::FilterType::Nearest)
}

/// Gaussian-blur the rect region (sigma ~ radius), returning a rect-sized patch.
/// The source is padded by `radius` (clamped to image bounds) so edge pixels
/// blur against their real neighbours, then cropped back to the rect.
pub fn blurred_patch(img: &RgbaImage, rect: (u32, u32, u32, u32), radius: u32) -> RgbaImage {
    let (x, y, w, h) = rect;
    let (iw, ih) = img.dimensions();
    let pad = radius;
    let px = x.saturating_sub(pad);
    let py = y.saturating_sub(pad);
    let pw = (w + (x - px) + pad).min(iw - px);
    let ph = (h + (y - py) + pad).min(ih - py);
    let region = image::imageops::crop_imm(img, px, py, pw, ph).to_image();
    let blurred = image::imageops::blur(&region, radius.max(1) as f32);
    let off_x = x - px;
    let off_y = y - py;
    image::imageops::crop_imm(&blurred, off_x, off_y, w, h).to_image()
}

/// Make corners transparent with the given radius (quarter-circle mask).
pub fn rounded_corners(img: &RgbaImage, radius: u32) -> RgbaImage {
    let (w, h) = img.dimensions();
    let mut out = img.clone();
    let r = radius as i64;
    let corners = [
        (0i64, 0i64, r, r),
        ((w as i64) - 1, 0, (w as i64) - 1 - r, r),
        (0, (h as i64) - 1, r, (h as i64) - 1 - r),
        ((w as i64) - 1, (h as i64) - 1, (w as i64) - 1 - r, (h as i64) - 1 - r),
    ];
    for (cx, cy, center_x, center_y) in corners {
        let (sx, ex) = (cx.min(center_x), cx.max(center_x));
        let (sy, ey) = (cy.min(center_y), cy.max(center_y));
        for yy in sy..=ey {
            for xx in sx..=ex {
                let dx = (xx - center_x) as f64;
                let dy = (yy - center_y) as f64;
                if dx * dx + dy * dy > (r as f64) * (r as f64)
                    && xx >= 0
                    && yy >= 0
                    && (xx as u32) < w
                    && (yy as u32) < h
                {
                    let mut p = *out.get_pixel(xx as u32, yy as u32);
                    p[3] = 0;
                    out.put_pixel(xx as u32, yy as u32, p);
                }
            }
        }
    }
    out
}

/// Fade alpha to 0 over the bottom `height` rows (linear).
pub fn bottom_fade(img: &RgbaImage, height: u32) -> RgbaImage {
    let (w, h) = img.dimensions();
    let mut out = img.clone();
    let fade = height.min(h).max(1);
    let start = h - fade;
    for y in start..h {
        let t = (y - start) as f64 / fade as f64; // 0 at start -> ~1 at bottom
        let scale = 1.0 - t;
        for x in 0..w {
            let mut p = *out.get_pixel(x, y);
            p[3] = (p[3] as f64 * scale) as u8;
            out.put_pixel(x, y, p);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgba, RgbaImage};

    fn solid(w: u32, h: u32, px: [u8; 4]) -> RgbaImage {
        RgbaImage::from_pixel(w, h, Rgba(px))
    }

    #[test]
    fn crop_returns_exact_subimage() {
        let mut img = solid(10, 10, [255, 255, 255, 255]);
        img.put_pixel(5, 5, Rgba([1, 2, 3, 4]));
        let out = crop(&img, 5, 5, 3, 3);
        assert_eq!(out.dimensions(), (3, 3));
        assert_eq!(out.get_pixel(0, 0), &Rgba([1, 2, 3, 4]));
    }

    #[test]
    fn cut_out_vertical_removes_columns_and_joins() {
        let img = solid(10, 4, [9, 9, 9, 255]);
        let out = cut_out(&img, 3, 6, false);
        assert_eq!(out.dimensions(), (7, 4));
    }

    #[test]
    fn cut_out_horizontal_removes_rows_and_joins() {
        let img = solid(6, 4, [9, 9, 9, 255]);
        let out = cut_out(&img, 1, 3, true);
        assert_eq!(out.dimensions(), (6, 2));
    }

    #[test]
    fn pixelated_patch_is_rect_sized_and_blocky() {
        let mut img = solid(40, 40, [0, 0, 0, 255]);
        for y in 0..40 {
            for x in 0..40 {
                img.put_pixel(x, y, Rgba([(x * 6) as u8, (y * 6) as u8, 0, 255]));
            }
        }
        let patch = pixelated_patch(&img, (0, 0, 40, 40), 20);
        assert_eq!(patch.dimensions(), (40, 40));
        let a = patch.get_pixel(0, 0);
        let b = patch.get_pixel(10, 10);
        assert_eq!(a, b);
    }

    #[test]
    fn blurred_patch_is_rect_sized() {
        let img = solid(40, 40, [120, 120, 120, 255]);
        let patch = blurred_patch(&img, (5, 5, 20, 20), 4);
        assert_eq!(patch.dimensions(), (20, 20));
    }

    #[test]
    fn rounded_corners_makes_corner_transparent() {
        let img = solid(40, 40, [255, 255, 255, 255]);
        let out = rounded_corners(&img, 10);
        assert_eq!(out.get_pixel(0, 0)[3], 0);
        assert_eq!(out.get_pixel(20, 20)[3], 255);
    }

    #[test]
    fn bottom_fade_reduces_alpha_at_bottom_only() {
        let img = solid(20, 40, [255, 255, 255, 255]);
        let out = bottom_fade(&img, 10);
        assert_eq!(out.get_pixel(0, 0)[3], 255);
        assert!(out.get_pixel(0, 39)[3] < 255);
    }
}
