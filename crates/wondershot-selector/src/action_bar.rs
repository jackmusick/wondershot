//! Anti-aliased rendering of the floating capture action bar.
//!
//! The bar is described in logical units (the same 282x58 layout used for hit
//! testing) and rasterised directly at the display's backing scale, so Retina
//! and fractional-scale displays get crisp vector edges instead of an upscaled
//! bitmap. Icons are the exact SVG markup used by the webview action bar in
//! `src/routes/capture-actionbar/+page.svelte`; the size read-out uses a bundled
//! Inter subset with tabular figures.

use std::sync::OnceLock;

use ab_glyph::{point, Font, FontRef, Glyph, PxScale, ScaleFont};
use resvg::tiny_skia::{Pixmap, PremultipliedColorU8, Transform};
use resvg::usvg;

use crate::{ActionBarHit, BAR_HEIGHT, BAR_WIDTH};

// Bifrost dark tokens (src/lib/styles/bifrost-tokens.css, tokens.css).
const SURFACE: &str = "#0a0c0f"; // --bf-paper
const LINE: &str = "#252c34"; // --bf-line
const COOL: &str = "#11151a"; // --bf-cool
const INK: [u8; 3] = [0xf7, 0xf9, 0xfb]; // --bf-ink
const MUTED: [u8; 3] = [0x9c, 0xaa, 0xb5]; // --bf-muted
const ACCENT: &str = "#2fd4d4"; // --toolbar-fg-emphasis
const ACCENT_HOVER: &str = "#63e1e1"; // --toolbar-fg-emphasis-hover
const DANGER: &str = "#ff727a"; // --bf-danger
// Same as the webview action bar: color-mix(in srgb, --bf-danger 80%, --bf-ink).
const DANGER_HOVER: &str = "#fd8d94";
const QUIET: &str = "#9caab5"; // --toolbar-fg (--bf-muted)
const QUIET_HOVER: &str = "#f7f9fb"; // --toolbar-fg-hover (--bf-ink)

// Same markup as the webview action bar (viewBox 0 0 24 24).
const CAMERA_ICON: &str = r#"<path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.8l1.2-1.7h5L15.7 6h1.8A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z"/><circle cx="12" cy="12.5" r="3.3"/>"#;
const RECORD_ICON: &str = r#"<circle cx="12" cy="12" r="6"/>"#;
const CANCEL_ICON: &str = r#"<path d="M6 6l12 12M18 6L6 18"/>"#;

/// Logical layout of the bar, shared with `action_bar_hit_at`.
pub(crate) const BUTTON_TOP: i32 = 7;
pub(crate) const BUTTON_SIZE: i32 = 44;
pub(crate) const CAPTURE_LEFT: i32 = 7;
pub(crate) const RECORD_LEFT: i32 = 59;
pub(crate) const CANCEL_LEFT: i32 = 231;
const SIZE_BOX: (f32, f32, f32, f32) = (111.0, 7.0, 112.0, 44.0);
const STROKE_ICON_SIZE: f32 = 23.0;
const RECORD_ICON_SIZE: f32 = 18.0;
/// Pressed glyphs: --toolbar-pressed-opacity / --toolbar-pressed-scale.
const PRESSED_OPACITY: f32 = 0.6;
const PRESSED_SCALE: f32 = 0.96;
const LABEL_FONT_SIZE: f32 = 13.0;
const LABEL_SEPARATOR_PADDING: f32 = 7.0;

static LABEL_FONT_BYTES: &[u8] = include_bytes!("../assets/fonts/Inter-Medium-SizeLabel.ttf");

fn label_font() -> Option<&'static FontRef<'static>> {
    static FONT: OnceLock<Option<FontRef<'static>>> = OnceLock::new();
    FONT.get_or_init(|| FontRef::try_from_slice(LABEL_FONT_BYTES).ok()).as_ref()
}

fn glyph_color(action: ActionBarHit, hovered: Option<ActionBarHit>) -> &'static str {
    let hover = hovered == Some(action);
    match (action, hover) {
        (ActionBarHit::Capture, false) => ACCENT,
        (ActionBarHit::Capture, true) => ACCENT_HOVER,
        (ActionBarHit::Record, false) => DANGER,
        (ActionBarHit::Record, true) => DANGER_HOVER,
        (ActionBarHit::Cancel, false) => QUIET,
        (ActionBarHit::Cancel, true) => QUIET_HOVER,
    }
}

/// One icon group: `markup` (24x24 viewBox) drawn `size` logical units wide,
/// centred in the button starting at `left`. Like the toolbar's `:active`, a
/// pressed glyph dims and shrinks slightly around its centre.
fn icon_svg(action: ActionBarHit, left: i32, size: f32, paint: &str, markup: &str,
    state: ButtonStates) -> String {
    let pressed = state.pressed == Some(action);
    let (shrink, opacity) = if pressed { (PRESSED_SCALE, PRESSED_OPACITY) } else { (1.0, 1.0) };
    let half = BUTTON_SIZE as f32 / 2.0;
    format!(
        r#"<g transform="translate({cx} {cy}) scale({s}) translate(-12 -12)" opacity="{opacity}" {paint}="{color}">{markup}</g>"#,
        cx = left as f32 + half,
        cy = BUTTON_TOP as f32 + half,
        s = size / 24.0 * shrink,
        color = glyph_color(action, state.hovered),
    )
}

/// Pointer state of the bar's buttons.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct ButtonStates {
    /// Button under the cursor.
    pub hovered: Option<ActionBarHit>,
    /// Button the mouse went down on, until release.
    pub pressed: Option<ActionBarHit>,
}

/// The complete bar as SVG in logical units. Buttons have no fill: hover only
/// changes glyph colour, matching the main toolbar's `.hbtn` styling.
fn bar_svg(state: ButtonStates) -> String {
    let (sx, sy, sw, sh) = SIZE_BOX;
    format!(
        concat!(
            r#"<svg xmlns="http://www.w3.org/2000/svg" width="{bw}" height="{bh}" viewBox="0 0 {bw} {bh}">"#,
            r#"<rect x="0.5" y="0.5" width="{bw1}" height="{bh1}" rx="7.5" fill="{surface}" stroke="{line}"/>"#,
            r#"<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="5.5" fill="{cool}" stroke="{line}"/>"#,
            r#"<g fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{capture}{cancel}</g>"#,
            r#"{record}"#,
            r#"</svg>"#
        ),
        bw = BAR_WIDTH,
        bh = BAR_HEIGHT,
        bw1 = BAR_WIDTH - 1,
        bh1 = BAR_HEIGHT - 1,
        surface = SURFACE,
        line = LINE,
        cool = COOL,
        sx = sx + 0.5,
        sy = sy + 0.5,
        sw = sw - 1.0,
        sh = sh - 1.0,
        capture = icon_svg(ActionBarHit::Capture, CAPTURE_LEFT, STROKE_ICON_SIZE, "stroke", CAMERA_ICON, state),
        cancel = icon_svg(ActionBarHit::Cancel, CANCEL_LEFT, STROKE_ICON_SIZE, "stroke", CANCEL_ICON, state),
        record = icon_svg(ActionBarHit::Record, RECORD_LEFT, RECORD_ICON_SIZE, "fill", RECORD_ICON, state),
    )
}

/// Rasterises the bar at `scale` backing pixels per logical unit into a
/// `width` x `height` premultiplied RGBA pixmap.
pub(crate) fn render_action_bar(
    width: u32,
    height: u32,
    scale: f32,
    state: ButtonStates,
    label: Option<(u32, u32)>,
) -> Option<Pixmap> {
    let mut pixmap = Pixmap::new(width, height)?;
    let tree = usvg::Tree::from_str(&bar_svg(state), &usvg::Options::default()).ok()?;
    resvg::render(&tree, Transform::from_scale(scale, scale), &mut pixmap.as_mut());
    if let Some((w, h)) = label {
        draw_size_label(&mut pixmap, scale, w, h);
    }
    Some(pixmap)
}

/// Draws "W × H" centred in the size box with anti-aliased Inter glyphs.
fn draw_size_label(pixmap: &mut Pixmap, scale: f32, width: u32, height: u32) {
    let Some(font) = label_font() else { return };
    let Some(units_per_em) = font.units_per_em() else { return };
    // CSS font-size is the em size; ab_glyph's PxScale is ascent-to-descent.
    let em = LABEL_FONT_SIZE * scale;
    let scaled = font.as_scaled(PxScale::from(em * font.height_unscaled() / units_per_em));
    let gap = scaled.h_advance(font.glyph_id(' ')) + LABEL_SEPARATOR_PADDING * scale;

    let width_text = width.to_string();
    let height_text = height.to_string();
    let runs: [(&str, [u8; 3], f32); 3] = [
        (&width_text, INK, gap),
        ("\u{00d7}", MUTED, gap),
        (&height_text, INK, 0.0),
    ];
    let advance = |text: &str| text.chars().map(|c| scaled.h_advance(font.glyph_id(c))).sum::<f32>();
    let total: f32 = runs.iter().map(|(text, _, after)| advance(text) + after).sum();

    let (bx, by, bw, bh) = SIZE_BOX;
    let mut x = ((bx + bw / 2.0) * scale - total / 2.0).round();
    // Centre on the figures' ink, not the line box, so digits sit optically mid-box.
    let reference = scaled.scaled_glyph('0');
    let baseline = match font.outline_glyph(reference) {
        Some(outline) => {
            let bounds = outline.px_bounds();
            ((by + bh / 2.0) * scale - (bounds.min.y + bounds.max.y) / 2.0).round()
        }
        None => ((by + bh / 2.0) * scale + (scaled.ascent() + scaled.descent()) / 2.0).round(),
    };

    for (text, color, after) in runs {
        for character in text.chars() {
            let id = font.glyph_id(character);
            let glyph: Glyph = id.with_scale_and_position(scaled.scale(), point(x, baseline));
            if let Some(outline) = font.outline_glyph(glyph) {
                let bounds = outline.px_bounds();
                outline.draw(|gx, gy, coverage| {
                    blend_coverage(
                        pixmap,
                        bounds.min.x as i32 + gx as i32,
                        bounds.min.y as i32 + gy as i32,
                        color,
                        coverage,
                    );
                });
            }
            x += scaled.h_advance(id);
        }
        x += after;
    }
}

fn blend_coverage(pixmap: &mut Pixmap, x: i32, y: i32, color: [u8; 3], coverage: f32) {
    if x < 0 || y < 0 || x >= pixmap.width() as i32 || y >= pixmap.height() as i32 {
        return;
    }
    let index = y as usize * pixmap.width() as usize + x as usize;
    let alpha = coverage.clamp(0.0, 1.0);
    if alpha <= 0.0 {
        return;
    }
    let dst = pixmap.pixels()[index];
    let keep = 1.0 - alpha;
    let mix = |src: u8, dst: u8| (f32::from(src) * alpha + f32::from(dst) * keep).round() as u8;
    let a = (255.0 * alpha + f32::from(dst.alpha()) * keep).round() as u8;
    let r = mix(color[0], dst.red()).min(a);
    let g = mix(color[1], dst.green()).min(a);
    let b = mix(color[2], dst.blue()).min(a);
    if let Some(pixel) = PremultipliedColorU8::from_rgba(r, g, b, a) {
        pixmap.pixels_mut()[index] = pixel;
    }
}

/// Source-over composites a premultiplied pixmap onto the 0RGB frame buffer.
pub(crate) fn composite(buffer: &mut [u32], stride: u32, height: u32, origin: (i32, i32), pixmap: &Pixmap) {
    let pw = pixmap.width() as i32;
    let pixels = pixmap.pixels();
    for py in 0..pixmap.height() as i32 {
        let y = origin.1 + py;
        if y < 0 || y >= height as i32 {
            continue;
        }
        for px in 0..pw {
            let x = origin.0 + px;
            if x < 0 || x >= stride as i32 {
                continue;
            }
            let src = pixels[(py * pw + px) as usize];
            let alpha = u32::from(src.alpha());
            if alpha == 0 {
                continue;
            }
            let target = &mut buffer[(y as u32 * stride + x as u32) as usize];
            let rgb = |s: u8, shift: u32| {
                let d = (*target >> shift) & 0xff;
                (u32::from(s) + (d * (255 - alpha) + 127) / 255).min(255)
            };
            *target = (rgb(src.red(), 16) << 16) | (rgb(src.green(), 8) << 8) | rgb(src.blue(), 0);
        }
    }
}

/// Where and how the bar is drawn on a display, in backing pixels.
#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) struct ActionBarView {
    pub origin: (i32, i32),
    pub size: (u32, u32),
    pub scale: f32,
    pub buttons: ButtonStates,
    pub label: Option<(u32, u32)>,
}

/// Caches the last rendered bar: redraws on every cursor move otherwise
/// re-rasterise identical vector content.
#[derive(Default)]
pub(crate) struct ActionBarCache {
    last: Option<(ActionBarView, Pixmap)>,
}

impl ActionBarCache {
    pub(crate) fn draw(&mut self, buffer: &mut [u32], stride: u32, height: u32, view: ActionBarView) {
        let stale = self.last.as_ref().is_none_or(|(cached, _)| {
            (cached.size, cached.scale, cached.buttons, cached.label)
                != (view.size, view.scale, view.buttons, view.label)
        });
        if stale {
            self.last = render_action_bar(view.size.0, view.size.1, view.scale, view.buttons, view.label)
                .map(|pixmap| (view, pixmap));
        }
        if let Some((_, pixmap)) = &self.last {
            composite(buffer, stride, height, view.origin, pixmap);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rgb(hex: &str) -> u32 {
        u32::from_str_radix(hex.trim_start_matches('#'), 16).unwrap()
    }

    fn hover(action: ActionBarHit) -> ButtonStates {
        ButtonStates { hovered: Some(action), pressed: None }
    }

    fn render(scale: f32, state: ButtonStates, label: Option<(u32, u32)>) -> (Vec<u32>, u32, u32) {
        let w = (BAR_WIDTH as f32 * scale).round() as u32;
        let h = (BAR_HEIGHT as f32 * scale).round() as u32;
        let pixmap = render_action_bar(w, h, scale, state, label).unwrap();
        let mut buffer = vec![0u32; (w * h) as usize];
        composite(&mut buffer, w, h, (0, 0), &pixmap);
        (buffer, w, h)
    }

    #[test]
    fn bundled_label_font_covers_size_readout() {
        let font = label_font().expect("bundled Inter subset parses");
        for c in "0123456789 x\u{00d7}".chars() {
            assert_ne!(font.glyph_id(c).0, 0, "missing glyph for {c:?}");
        }
        // Tabular figures are frozen into the subset so the read-out does not jitter.
        let advance = font.h_advance_unscaled(font.glyph_id('0'));
        for c in "123456789".chars() {
            assert_eq!(font.h_advance_unscaled(font.glyph_id(c)), advance);
        }
    }

    #[test]
    fn retina_bar_is_rasterised_at_physical_resolution_with_antialiasing() {
        let (buffer, w, _) = render(2.0, ButtonStates::default(), Some((1280, 720)));
        // A 2x nearest-neighbour upscale makes every aligned 2x2 block uniform.
        let camera = (2 * (CAPTURE_LEFT + 10)..2 * (CAPTURE_LEFT + 34), 2 * 17..2 * 41);
        let mut non_uniform_blocks = 0;
        let mut intermediate = 0;
        let surface = rgb(SURFACE);
        let accent = rgb(ACCENT);
        for y in camera.1.clone().step_by(2) {
            for x in camera.0.clone().step_by(2) {
                let at = |dx: i32, dy: i32| buffer[((y + dy) as u32 * w + (x + dx) as u32) as usize];
                let block = [at(0, 0), at(1, 0), at(0, 1), at(1, 1)];
                if block.iter().any(|p| *p != block[0]) {
                    non_uniform_blocks += 1;
                }
                intermediate += block.iter().filter(|p| **p != surface && **p != accent).count();
            }
        }
        assert!(non_uniform_blocks > 20, "icon looks nearest-neighbour upscaled");
        assert!(intermediate > 20, "icon edges are not anti-aliased");

        // The size read-out draws anti-aliased ink text inside the size box.
        let cool = rgb(COOL);
        let ink = u32::from(INK[0]) << 16 | u32::from(INK[1]) << 8 | u32::from(INK[2]);
        let text_pixels: Vec<u32> = (2 * 7..2 * 51)
            .flat_map(|y| (2 * 112..2 * 222).map(move |x| (x, y)))
            .map(|(x, y)| buffer[(y * w + x) as usize])
            .filter(|p| *p != cool)
            .collect();
        assert!(text_pixels.contains(&ink));
        assert!(text_pixels.iter().any(|p| *p != ink && *p != cool));
    }

    #[test]
    fn hover_changes_glyph_colour_not_button_background() {
        for (action, left, base, hover_color) in [
            (ActionBarHit::Capture, CAPTURE_LEFT, ACCENT, ACCENT_HOVER),
            (ActionBarHit::Record, RECORD_LEFT, DANGER, DANGER_HOVER),
            (ActionBarHit::Cancel, CANCEL_LEFT, QUIET, QUIET_HOVER),
        ] {
            let (idle, w, h) = render(2.0, ButtonStates::default(), None);
            let (hovered, _, _) = render(2.0, hover(action), None);
            let button = (2 * left..2 * (left + BUTTON_SIZE), 2 * BUTTON_TOP..2 * (BUTTON_TOP + BUTTON_SIZE));
            let mut changed = 0;
            for y in 0..h as i32 {
                for x in 0..w as i32 {
                    let i = (y as u32 * w + x as u32) as usize;
                    if idle[i] != hovered[i] {
                        assert!(button.0.contains(&x) && button.1.contains(&y), "{action:?} hover changed pixels outside its button");
                        changed += 1;
                    }
                }
            }
            assert!(changed > 0, "{action:?} hover has no visible effect");
            // Button corner (no glyph there) stays the bar surface: no hover fill.
            let corner = ((2 * BUTTON_TOP + 3) as u32 * w + (2 * left + 3) as u32) as usize;
            assert_eq!(idle[corner], rgb(SURFACE));
            assert_eq!(hovered[corner], rgb(SURFACE));
            assert!(idle.contains(&rgb(base)), "{action:?} idle glyph colour missing");
            assert!(hovered.contains(&rgb(hover_color)), "{action:?} hover glyph colour missing");
            // Colour only: the hovered glyph covers exactly the same pixels.
            let surface = rgb(SURFACE);
            let footprint = |frame: &[u32]| frame.iter().filter(|p| **p != surface).count();
            assert_eq!(footprint(&idle), footprint(&hovered), "{action:?} hover changed glyph size");
        }
    }

    #[test]
    fn pressed_glyph_dims_and_shrinks_inside_its_button() {
        for (action, left) in [
            (ActionBarHit::Capture, CAPTURE_LEFT),
            (ActionBarHit::Record, RECORD_LEFT),
            (ActionBarHit::Cancel, CANCEL_LEFT),
        ] {
            let (hovered, w, h) = render(2.0, hover(action), None);
            let pressed_state = ButtonStates { hovered: Some(action), pressed: Some(action) };
            let (pressed, _, _) = render(2.0, pressed_state, None);
            let button = (2 * left..2 * (left + BUTTON_SIZE), 2 * BUTTON_TOP..2 * (BUTTON_TOP + BUTTON_SIZE));
            let surface = rgb(SURFACE);
            let luminance = |p: u32| ((p >> 16) & 0xff) + ((p >> 8) & 0xff) + (p & 0xff);
            let (mut ink_hovered, mut ink_pressed, mut glyph_hovered, mut glyph_pressed) = (0u64, 0u64, 0, 0);
            for y in 0..h as i32 {
                for x in 0..w as i32 {
                    let i = (y as u32 * w + x as u32) as usize;
                    if hovered[i] != pressed[i] {
                        assert!(button.0.contains(&x) && button.1.contains(&y), "{action:?} press changed pixels outside its button");
                    }
                    if button.0.contains(&x) && button.1.contains(&y) {
                        ink_hovered += u64::from(luminance(hovered[i]));
                        ink_pressed += u64::from(luminance(pressed[i]));
                        glyph_hovered += usize::from(hovered[i] != surface);
                        glyph_pressed += usize::from(pressed[i] != surface);
                    }
                }
            }
            assert!(ink_pressed < ink_hovered, "{action:?} press does not dim the glyph");
            assert!(glyph_pressed < glyph_hovered, "{action:?} press does not shrink the glyph");
        }
    }

    /// Writes a 2x preview when WONDERSHOT_ACTION_BAR_PREVIEW names a PNG path.
    #[test]
    fn writes_preview_png_when_requested() {
        let Ok(path) = std::env::var("WONDERSHOT_ACTION_BAR_PREVIEW") else { return };
        let capture = ActionBarHit::Capture;
        for (suffix, state) in [
            ("", ButtonStates::default()),
            ("-hover-capture", hover(capture)),
            ("-hover-record", hover(ActionBarHit::Record)),
            ("-hover-cancel", hover(ActionBarHit::Cancel)),
            ("-pressed-capture", ButtonStates { hovered: Some(capture), pressed: Some(capture) }),
        ] {
            let (buffer, w, h) = render(2.0, state, Some((1280, 720)));
            let bytes: Vec<u8> = buffer
                .iter()
                .flat_map(|p| [(p >> 16) as u8, (p >> 8) as u8, *p as u8])
                .collect();
            let out = path.replace(".png", &format!("{suffix}.png"));
            image::RgbImage::from_raw(w, h, bytes).unwrap().save(out).unwrap();
        }
    }
}
