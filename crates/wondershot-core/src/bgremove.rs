//! AI background removal via U²-Net ONNX — pure preprocessing/composite plus a
//! gated inference path.
//!
//! Ports `wondershot/bgremove.py` (which used rembg/u2net). Here the pipeline is
//! explicit: input image → resize 320×320 → ImageNet normalize → tensor
//! (1,3,320,320) → run u2net.onnx → output mask (1,1,320,320) ch0 → min-max
//! normalize → resize mask to original size → apply as the ALPHA channel.
//!
//! The ONNX inference itself is gated behind the `bgremove-onnx` cargo feature
//! (which pulls `ort` + a prebuilt onnxruntime). The pure helpers
//! (`normalize_input`, `apply_mask`, `resize_to_input`) compile and test with no
//! `ort` dependency. When the feature is off, `remove_background` returns an
//! error rather than blocking the build.

use image::RgbaImage;
use std::path::PathBuf;

/// Model input side length (u2net expects 320×320).
pub const INPUT_SIZE: u32 = 320;

/// ImageNet normalization constants (per RGB channel).
const MEAN: [f32; 3] = [0.485, 0.456, 0.406];
const STD: [f32; 3] = [0.229, 0.224, 0.225];

/// Path the editor/packaging expects the model at: `~/.cache/wondershot/u2net.onnx`.
pub fn model_path() -> PathBuf {
    let base = dirs::cache_dir().unwrap_or_else(|| PathBuf::from("."));
    base.join("wondershot").join("u2net.onnx")
}

/// Whether the model file is present (gates the editor "Remove BG" button).
pub fn model_available() -> bool {
    model_path().exists()
}

/// Resize an RGBA image to the model's 320×320 input (Lanczos3).
pub fn resize_to_input(img: &RgbaImage) -> RgbaImage {
    image::imageops::resize(
        img,
        INPUT_SIZE,
        INPUT_SIZE,
        image::imageops::FilterType::Lanczos3,
    )
}

/// ImageNet-normalize a 320×320 RGBA image into a CHW `f32` tensor body
/// `(3*320*320)`: the full R plane, then G, then B. Each channel `c` is
/// `(pixel_c/255.0 - mean[c]) / std[c]`. Alpha is ignored.
///
/// Assumes `img` is already 320×320 (the caller resizes first).
pub fn normalize_input(img: &RgbaImage) -> Vec<f32> {
    let n = (INPUT_SIZE * INPUT_SIZE) as usize;
    let mut out = vec![0.0f32; 3 * n];
    for (i, px) in img.pixels().enumerate() {
        for c in 0..3 {
            let v = px[c] as f32 / 255.0;
            out[c * n + i] = (v - MEAN[c]) / STD[c];
        }
    }
    out
}

/// Set each pixel's alpha from `mask[y*w + x]`, preserving RGB. `mask` is the
/// original-size, row-major per-pixel alpha (already resized back to `w×h`).
pub fn apply_mask(img: &mut RgbaImage, mask: &[u8], w: u32, h: u32) {
    for y in 0..h {
        for x in 0..w {
            let idx = (y * w + x) as usize;
            let a = mask.get(idx).copied().unwrap_or(255);
            let mut p = *img.get_pixel(x, y);
            p[3] = a;
            img.put_pixel(x, y, p);
        }
    }
}

/// Min-max normalize a raw mask plane to `u8` in `[0, 255]`. Used on the u2net
/// output channel 0 before resizing it back to the original image size.
#[cfg_attr(not(feature = "bgremove-onnx"), allow(dead_code))]
fn normalize_mask(raw: &[f32]) -> Vec<u8> {
    let (mut lo, mut hi) = (f32::INFINITY, f32::NEG_INFINITY);
    for &v in raw {
        if v < lo {
            lo = v;
        }
        if v > hi {
            hi = v;
        }
    }
    let span = hi - lo;
    raw.iter()
        .map(|&v| {
            let t = if span > 0.0 { (v - lo) / span } else { 0.0 };
            (t * 255.0).round().clamp(0.0, 255.0) as u8
        })
        .collect()
}

/// Run u2net on `img`, returning a copy with the background made transparent.
///
/// Requires the model file at `model_path`. Available only behind the
/// `bgremove-onnx` feature; without it this returns an error so the rest of the
/// crate still builds.
#[cfg(feature = "bgremove-onnx")]
pub fn remove_background(
    img: &RgbaImage,
    model_path: &std::path::Path,
) -> Result<RgbaImage, String> {
    use ndarray::Array4;
    use ort::session::Session;
    use ort::value::Tensor;

    let (w, h) = img.dimensions();

    // Resize → normalize → (1,3,320,320) ndarray.
    let resized = resize_to_input(img);
    let chw = normalize_input(&resized);
    let input: Array4<f32> = Array4::from_shape_vec(
        (1, 3, INPUT_SIZE as usize, INPUT_SIZE as usize),
        chw,
    )
    .map_err(|e| format!("input tensor shape error: {e}"))?;

    let mut session = Session::builder()
        .map_err(|e| format!("ort session builder: {e}"))?
        .commit_from_file(model_path)
        .map_err(|e| format!("could not load model {}: {e}", model_path.display()))?;

    let input_name = session.inputs[0].name.clone();
    let tensor = Tensor::from_array(input).map_err(|e| format!("input tensor: {e}"))?;
    let outputs = session
        .run(ort::inputs![input_name => tensor])
        .map_err(|e| format!("inference failed: {e}"))?;

    // Output (1,1,320,320); take channel 0's 320*320 values.
    let (_shape, data) = outputs[0]
        .try_extract_tensor::<f32>()
        .map_err(|e| format!("could not read output: {e}"))?;
    let n = (INPUT_SIZE * INPUT_SIZE) as usize;
    if data.len() < n {
        return Err(format!("unexpected output length {}", data.len()));
    }
    let mask_small = normalize_mask(&data[..n]);

    // Mask is a 320×320 grayscale image; resize back to original (w,h).
    let mask_img = image::GrayImage::from_raw(INPUT_SIZE, INPUT_SIZE, mask_small)
        .ok_or("could not build mask image")?;
    let mask_full = image::imageops::resize(
        &mask_img,
        w,
        h,
        image::imageops::FilterType::Lanczos3,
    );

    let mut out = img.clone();
    apply_mask(&mut out, mask_full.as_raw(), w, h);
    Ok(out)
}

/// Stub when ONNX inference is not compiled in: report unavailability rather
/// than block the build.
#[cfg(not(feature = "bgremove-onnx"))]
pub fn remove_background(
    _img: &RgbaImage,
    _model_path: &std::path::Path,
) -> Result<RgbaImage, String> {
    Err("background removal runtime not available (build with --features bgremove-onnx)".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgba, RgbaImage};

    #[test]
    fn normalize_input_shape_and_values() {
        // a 320x320 solid image -> (1*3*320*320) f32, ImageNet-normalized.
        let img = RgbaImage::from_pixel(320, 320, Rgba([255, 0, 0, 255]));
        let t = normalize_input(&img); // returns Vec<f32> length 3*320*320, CHW order
        assert_eq!(t.len(), 3 * 320 * 320);
        // R channel: (1.0 - 0.485)/0.229 ; G: (0 - 0.456)/0.224 ; B: (0 - 0.406)/0.225
        let r = (1.0f32 - 0.485) / 0.229;
        assert!((t[0] - r).abs() < 1e-4);
        let g = (0.0f32 - 0.456) / 0.224;
        assert!((t[320 * 320] - g).abs() < 1e-4); // first pixel of G plane (CHW)
    }

    #[test]
    fn apply_mask_sets_alpha() {
        let mut img = RgbaImage::from_pixel(2, 2, Rgba([10, 20, 30, 255]));
        let mask = vec![0u8, 255, 128, 0]; // per-pixel alpha, row-major, 2x2
        apply_mask(&mut img, &mask, 2, 2);
        assert_eq!(img.get_pixel(0, 0)[3], 0);
        assert_eq!(img.get_pixel(1, 0)[3], 255);
        assert_eq!(img.get_pixel(0, 1)[3], 128);
        // RGB preserved
        assert_eq!(img.get_pixel(1, 0)[0], 10);
    }
}
