//! AI Redact / Simplify — Rust port of the Python `aiclient.py` / `redact.py`
//! / `simplify.py` / `ocr.py` pipeline.
//!
//! Redact: tesseract word boxes + a vision LLM that names WHICH text is
//! sensitive (text spans — LLMs are bad at pixel coordinates); spans are
//! matched back to OCR boxes. Without tesseract: ask the LLM for normalized
//! bounding boxes directly (sloppier, model-dependent).
//!
//! Simplify: a vision LLM labels major UI regions (text/image/chrome); the
//! editor replaces them with clean filled rects (text → neutral gray, others
//! → the region's dominant color). Always non-destructive.

use serde_json::Value;

// ---------------------------------------------------------------------------
// OpenAI-compatible chat client (aiclient.py)
// ---------------------------------------------------------------------------

/// Normalize a user-entered base URL to `…/v1/chat/completions`.
pub fn chat_url(endpoint: &str) -> String {
    let base = endpoint.trim().trim_end_matches('/');
    if base.ends_with("/chat/completions") {
        return base.to_string();
    }
    if base.ends_with("/v1") {
        format!("{base}/chat/completions")
    } else {
        format!("{base}/v1/chat/completions")
    }
}

/// Blocking chat completion; `image_b64` (bare base64 PNG body) becomes a
/// vision `image_url` part. Returns the assistant message text.
pub fn chat(
    endpoint: &str,
    api_key: &str,
    model: &str,
    prompt: &str,
    image_b64: Option<&str>,
) -> Result<String, String> {
    let content: Value = match image_b64 {
        Some(b64) => serde_json::json!([
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": format!("data:image/png;base64,{b64}")}}
        ]),
        None => Value::String(prompt.to_string()),
    };
    let body = serde_json::json!({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1024,
    });
    let mut req = ureq::post(&chat_url(endpoint))
        .timeout(std::time::Duration::from_secs(120))
        .set("Content-Type", "application/json");
    if !api_key.trim().is_empty() {
        req = req.set("Authorization", &format!("Bearer {}", api_key.trim()));
    }
    let resp = match req.send_json(body) {
        Ok(r) => r,
        Err(ureq::Error::Status(code, r)) => {
            let detail = r
                .into_json::<Value>()
                .ok()
                .and_then(|v| {
                    v.pointer("/error/message")
                        .or_else(|| v.get("error"))
                        .and_then(|x| x.as_str().map(String::from))
                })
                .unwrap_or_default();
            return Err(format!("AI endpoint returned HTTP {code} {detail}"));
        }
        Err(e) => return Err(format!("could not reach AI endpoint: {e}")),
    };
    let v: Value = resp.into_json().map_err(|e| e.to_string())?;
    v.pointer("/choices/0/message/content")
        .and_then(|c| c.as_str())
        .map(String::from)
        .ok_or_else(|| "AI response had no message content".into())
}

// ---------------------------------------------------------------------------
// Reply JSON extraction (redact.py extract_json + helpers)
// ---------------------------------------------------------------------------

/// Balanced `[...]`/`{...}` starting at byte `start` (which must be `[`/`{`),
/// ignoring brackets inside JSON strings. None if it never closes.
fn span_from(text: &str, start: usize) -> Option<&str> {
    let bytes = text.as_bytes();
    let open = bytes[start];
    let close = if open == b'[' { b']' } else { b'}' };
    let (mut depth, mut in_str, mut esc) = (0i32, false, false);
    for (i, &ch) in bytes.iter().enumerate().skip(start) {
        if in_str {
            if esc {
                esc = false;
            } else if ch == b'\\' {
                esc = true;
            } else if ch == b'"' {
                in_str = false;
            }
            continue;
        }
        match ch {
            b'"' => in_str = true,
            c if c == open => depth += 1,
            c if c == close => {
                depth -= 1;
                if depth == 0 {
                    return Some(&text[start..=i]);
                }
            }
            _ => {}
        }
    }
    None
}

/// First balanced span that PARSES as JSON (skips prose brackets).
fn balanced_json_span(text: &str) -> Option<&str> {
    for (i, ch) in text.char_indices() {
        if ch != '[' && ch != '{' {
            continue;
        }
        if let Some(span) = span_from(text, i) {
            if serde_json::from_str::<Value>(span).is_ok() {
                return Some(span);
            }
        }
    }
    None
}

/// Every balanced span that parses as JSON, in order (for models that emit
/// one object per markdown bullet instead of one array).
fn iter_json_values(text: &str) -> Vec<Value> {
    let mut out = Vec::new();
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'[' || bytes[i] == b'{' {
            if let Some(span) = span_from(text, i) {
                if let Ok(v) = serde_json::from_str::<Value>(span) {
                    out.push(v);
                    i += span.len();
                    continue;
                }
            }
        }
        i += 1;
    }
    out
}

/// Unwrap ``` fences and prose around the model's JSON payload.
pub fn extract_json(reply: &str) -> String {
    let mut text = reply.trim().to_string();
    if let Some(start) = text.find("```") {
        let after = &text[start + 3..];
        let after = after.strip_prefix("json").unwrap_or(after);
        if let Some(end) = after.find("```") {
            text = after[..end].trim().to_string();
        }
    }
    match balanced_json_span(&text) {
        Some(span) => span.to_string(),
        None => text,
    }
}

/// True if the reply has an unclosed `[`/`{` outside strings — the signature
/// of a response cut off by the model's output token limit.
fn looks_truncated(reply: &str) -> bool {
    let (mut depth, mut in_str, mut esc) = (0i32, false, false);
    for ch in reply.bytes() {
        if in_str {
            if esc {
                esc = false;
            } else if ch == b'\\' {
                esc = true;
            } else if ch == b'"' {
                in_str = false;
            }
        } else if ch == b'"' {
            in_str = true;
        } else if ch == b'[' || ch == b'{' {
            depth += 1;
        } else if ch == b']' || ch == b'}' {
            depth -= 1;
        }
    }
    depth > 0
}

// ---------------------------------------------------------------------------
// OCR via the tesseract binary (ocr.py)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub struct Word {
    pub text: String,
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

/// Word boxes out of `tesseract … tsv` output (conf ≥ 0 rows with text).
pub fn parse_tsv(tsv: &str) -> Vec<Word> {
    let mut lines = tsv.lines();
    let Some(header) = lines.next() else { return Vec::new() };
    let cols: Vec<&str> = header.split('\t').collect();
    let idx = |name: &str| cols.iter().position(|c| *c == name);
    let (Some(left), Some(top), Some(width), Some(height), Some(conf), Some(text)) = (
        idx("left"), idx("top"), idx("width"), idx("height"), idx("conf"), idx("text"),
    ) else {
        return Vec::new();
    };
    let mut words = Vec::new();
    for line in lines {
        let f: Vec<&str> = line.split('\t').collect();
        if f.len() != cols.len() {
            continue;
        }
        let t = f[text].trim();
        if t.is_empty() {
            continue;
        }
        let Ok(c) = f[conf].parse::<f64>() else { continue };
        if c < 0.0 {
            continue; // structural (non-word) rows
        }
        let (Ok(x), Ok(y), Ok(w), Ok(h)) = (
            f[left].parse(), f[top].parse(), f[width].parse(), f[height].parse(),
        ) else {
            continue;
        };
        words.push(Word { text: t.to_string(), x, y, w, h });
    }
    words
}

/// Run tesseract over PNG bytes; empty when unavailable or failing. In the
/// Flatpak the sandbox has no tesseract, so fall back to the host's via
/// flatpak-spawn (mirrors the Spectacle/host-tool pattern).
fn ocr_words(png: &[u8]) -> Vec<Word> {
    use std::io::Write;
    use std::process::{Command, Stdio};
    let attempts: Vec<Vec<&str>> = if crate::commands::in_flatpak() {
        vec![
            vec!["tesseract", "stdin", "stdout", "tsv"],
            vec!["flatpak-spawn", "--host", "tesseract", "stdin", "stdout", "tsv"],
        ]
    } else {
        vec![vec!["tesseract", "stdin", "stdout", "tsv"]]
    };
    for argv in attempts {
        let Ok(mut child) = Command::new(argv[0])
            .args(&argv[1..])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        else {
            continue;
        };
        if let Some(mut stdin) = child.stdin.take() {
            if stdin.write_all(png).is_err() {
                let _ = child.kill();
                continue;
            }
        }
        if let Ok(out) = child.wait_with_output() {
            if out.status.success() {
                return parse_tsv(&String::from_utf8_lossy(&out.stdout));
            }
        }
    }
    Vec::new()
}

// ---------------------------------------------------------------------------
// Redact (redact.py)
// ---------------------------------------------------------------------------

const SPAN_PROMPT: &str = "This is a screenshot. OCR detected the following words on it, in \
reading order:\n\n{words}\n\n\
Identify any text that should be redacted before sharing publicly: \
email addresses, names of private individuals, phone numbers, \
credit-card or account numbers, passwords, API keys/tokens, \
IP addresses, home addresses, and similar secrets or PII.\n\
Reply with ONLY a JSON array of strings. Each string must be an \
exact substring of the OCR text above (copy it verbatim, including \
several consecutive words when the sensitive value spans them). \
Reply [] if nothing is sensitive. No prose, no markdown.";

const BBOX_PROMPT: &str = "This is a screenshot. Find any text that should be redacted before \
sharing publicly: email addresses, names of private individuals, \
phone numbers, credit-card or account numbers, passwords, API \
keys/tokens, IP addresses, home addresses, and similar secrets or \
PII.\n\
Reply with ONLY a JSON array of bounding boxes, each an object \
{\"x0\": .., \"y0\": .., \"x1\": .., \"y1\": ..} with coordinates \
normalized to 0..1 relative to the image width/height (x0,y0 = \
top-left, x1,y1 = bottom-right). Reply [] if nothing is sensitive. \
No prose, no markdown.";

/// Lowercase, keep only chars that survive OCR/LLM round-trips.
fn norm(s: &str) -> String {
    let kept: String = s
        .to_lowercase()
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || "@._+-".contains(*c))
        .collect();
    kept.trim_matches(|c| ".,;:".contains(c)).to_string()
}

#[derive(Debug, Clone, Copy, PartialEq, serde::Serialize)]
pub struct RectPx {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

impl RectPx {
    fn union(self, o: RectPx) -> RectPx {
        let x = self.x.min(o.x);
        let y = self.y.min(o.y);
        let r = (self.x + self.w).max(o.x + o.w);
        let b = (self.y + self.h).max(o.y + o.h);
        RectPx { x, y, w: r - x, h: b - y }
    }

    fn clamp(self, width: i32, height: i32) -> Option<RectPx> {
        let x0 = self.x.max(0);
        let y0 = self.y.max(0);
        let x1 = (self.x + self.w).min(width);
        let y1 = (self.y + self.h).min(height);
        (x1 - x0 >= 4 && y1 - y0 >= 4).then_some(RectPx { x: x0, y: y0, w: x1 - x0, h: y1 - y0 })
    }
}

/// LLM text spans → OCR word boxes (union multi-word hits).
pub fn match_spans(spans: &[String], words: &[Word]) -> Vec<RectPx> {
    let norm_words: Vec<String> = words.iter().map(|w| norm(&w.text)).collect();
    let mut rects: Vec<RectPx> = Vec::new();
    for span in spans {
        let tokens: Vec<String> = span.split_whitespace().map(norm).filter(|t| !t.is_empty()).collect();
        if tokens.is_empty() {
            continue;
        }
        let n = tokens.len();
        if words.len() < n {
            continue;
        }
        for i in 0..=(words.len() - n) {
            let window = &norm_words[i..i + n];
            if tokens.iter().zip(window).all(|(t, w)| t == w || w.contains(t.as_str())) {
                let mut r = RectPx { x: words[i].x, y: words[i].y, w: words[i].w, h: words[i].h };
                for w in &words[i + 1..i + n] {
                    r = r.union(RectPx { x: w.x, y: w.y, w: w.w, h: w.h });
                }
                if !rects.contains(&r) {
                    rects.push(r);
                }
            }
        }
    }
    rects
}

fn parse_spans(reply: &str) -> Result<Vec<String>, String> {
    let data: Value = serde_json::from_str(&extract_json(reply))
        .map_err(|_| format!("AI reply was not JSON: {}", reply.chars().take(120).collect::<String>()))?;
    let arr = data.as_array().ok_or("AI reply was not a JSON array")?;
    Ok(arr
        .iter()
        .filter_map(|v| v.as_str())
        .filter(|s| !s.trim().is_empty())
        .map(String::from)
        .collect())
}

/// One normalized bbox object → pixel rect.
fn bbox_to_rect(box_: &Value, width: i32, height: i32) -> Option<RectPx> {
    let f = |k: &str| box_.get(k).and_then(|v| v.as_f64());
    let (x0, y0, x1, y1) = (f("x0")?, f("y0")?, f("x1")?, f("y1")?);
    let (w, h) = (width as f64, height as f64);
    let r = RectPx {
        x: (x0.min(x1) * w).round() as i32,
        y: (y0.min(y1) * h).round() as i32,
        w: ((x1 - x0).abs() * w).round() as i32,
        h: ((y1 - y0).abs() * h).round() as i32,
    };
    r.clamp(width, height)
}

fn parse_bboxes(reply: &str, width: i32, height: i32) -> Result<Vec<RectPx>, String> {
    let data: Value = serde_json::from_str(&extract_json(reply))
        .map_err(|_| format!("AI reply was not JSON: {}", reply.chars().take(120).collect::<String>()))?;
    let arr = data.as_array().ok_or("AI reply was not a JSON array")?;
    Ok(arr.iter().filter_map(|b| bbox_to_rect(b, width, height)).collect())
}

/// Full redact pipeline over PNG bytes (blocking; call off the main thread).
pub fn redact_regions(
    png: &[u8],
    width: i32,
    height: i32,
    endpoint: &str,
    api_key: &str,
    model: &str,
) -> Result<Vec<RectPx>, String> {
    use base64::Engine;
    let b64 = base64::engine::general_purpose::STANDARD.encode(png);
    let words = ocr_words(png);
    if !words.is_empty() {
        let joined = words.iter().map(|w| w.text.as_str()).collect::<Vec<_>>().join(" ");
        let prompt = SPAN_PROMPT.replace("{words}", &joined);
        let reply = chat(endpoint, api_key, model, &prompt, Some(&b64))?;
        let rects = match_spans(&parse_spans(&reply)?, &words);
        return Ok(rects.into_iter().filter_map(|r| r.clamp(width, height)).collect());
    }
    let reply = chat(endpoint, api_key, model, BBOX_PROMPT, Some(&b64))?;
    parse_bboxes(&reply, width, height)
}

// ---------------------------------------------------------------------------
// Simplify (simplify.py)
// ---------------------------------------------------------------------------

const REGION_PROMPT: &str = "This is a screenshot of an application or web page. Identify the \
major visual regions so the screenshot can be redrawn as a \
simplified mockup.\n\
Reply with ONLY a JSON array of objects, each \
{\"type\": \"text\"|\"image\"|\"chrome\", \"x0\": .., \"y0\": .., \
\"x1\": .., \"y1\": ..} with coordinates normalized to 0..1 relative \
to the image width/height (x0,y0 = top-left, x1,y1 = bottom-right).\n\
Use \"text\" for lines or blocks of text, \"image\" for photos, icons \
and illustrations, and \"chrome\" for window furniture: title bars, \
toolbars, menus, tabs, sidebars, buttons and input fields.\n\
Cover the visually significant regions; avoid overlapping boxes. \
Reply [] if nothing is recognizable. No prose, no markdown.";

/// Fill for "text" regions — a neutral text-placeholder gray.
const TEXT_FILL: &str = "#c8c8c8";

#[derive(Debug, Clone, serde::Serialize)]
pub struct SimplifyRegion {
    pub rect: RectPx,
    pub kind: String,
    /// `#rrggbb` fill for the replacement rect (text gray / dominant color).
    pub fill: String,
    /// `#rrggbb` stroke (slightly darker for images, == fill otherwise).
    pub stroke: String,
}

/// Most common color inside `rect`, robust to antialiasing noise: bucket to 3
/// bits/channel, return the most populous bucket's average. ≤64×64 sample grid.
pub fn dominant_color(img: &image::RgbaImage, r: RectPx) -> (u8, u8, u8) {
    let (iw, ih) = (img.width() as i32, img.height() as i32);
    let x0 = r.x.clamp(0, iw.saturating_sub(1));
    let y0 = r.y.clamp(0, ih.saturating_sub(1));
    let x1 = (r.x + r.w).clamp(x0 + 1, iw);
    let y1 = (r.y + r.h).clamp(y0 + 1, ih);
    let step_x = (((x1 - x0) / 64).max(1)) as usize;
    let step_y = (((y1 - y0) / 64).max(1)) as usize;
    use std::collections::HashMap;
    let mut counts: HashMap<(u8, u8, u8), (u64, u64, u64, u64)> = HashMap::new();
    let mut y = y0 as usize;
    while (y as i32) < y1 {
        let mut x = x0 as usize;
        while (x as i32) < x1 {
            let p = img.get_pixel(x as u32, y as u32);
            let key = (p[0] >> 5, p[1] >> 5, p[2] >> 5);
            let e = counts.entry(key).or_insert((0, 0, 0, 0));
            e.0 += 1;
            e.1 += p[0] as u64;
            e.2 += p[1] as u64;
            e.3 += p[2] as u64;
            x += step_x;
        }
        y += step_y;
    }
    match counts.values().max_by_key(|e| e.0) {
        Some(&(n, sr, sg, sb)) if n > 0 => ((sr / n) as u8, (sg / n) as u8, (sb / n) as u8),
        _ => (0x80, 0x80, 0x80),
    }
}

fn hex(c: (u8, u8, u8)) -> String {
    format!("#{:02x}{:02x}{:02x}", c.0, c.1, c.2)
}

/// Qt's `QColor::darker(115)` ≈ divide each channel by 1.15.
fn darker(c: (u8, u8, u8)) -> (u8, u8, u8) {
    (
        ((c.0 as f32) / 1.15) as u8,
        ((c.1 as f32) / 1.15) as u8,
        ((c.2 as f32) / 1.15) as u8,
    )
}

/// Recover the region-object list from the reply (clean array, wrapped
/// `{"regions": [...]}`, or scattered per-bullet objects).
fn region_dicts(reply: &str) -> Option<Vec<Value>> {
    let data = serde_json::from_str::<Value>(&extract_json(reply)).ok();
    let data = match data {
        Some(Value::Object(map)) => map.into_iter().map(|(_, v)| v).find(|v| v.is_array()),
        other => other,
    };
    if let Some(Value::Array(arr)) = data {
        return Some(arr);
    }
    let objs: Vec<Value> = iter_json_values(reply).into_iter().filter(|v| v.is_object()).collect();
    (!objs.is_empty()).then_some(objs)
}

pub fn parse_regions(reply: &str, width: i32, height: i32) -> Result<Vec<(RectPx, String)>, String> {
    let Some(data) = region_dicts(reply) else {
        if looks_truncated(reply) {
            return Err("the model's reply was cut off (it hit its output token limit \
                        before finishing). Try a model with a larger output limit, or \
                        simplify a smaller crop."
                .into());
        }
        return Err(format!("AI reply was not JSON: {}", reply.chars().take(120).collect::<String>()));
    };
    let mut out = Vec::new();
    for box_ in data {
        let kind = box_
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_lowercase();
        if !["text", "image", "chrome"].contains(&kind.as_str()) {
            continue;
        }
        if let Some(r) = bbox_to_rect(&box_, width, height) {
            out.push((r, kind));
        }
    }
    Ok(out)
}

/// Full simplify pipeline over a decoded image (blocking).
pub fn simplify_regions(
    img: &image::RgbaImage,
    png: &[u8],
    endpoint: &str,
    api_key: &str,
    model: &str,
) -> Result<Vec<SimplifyRegion>, String> {
    use base64::Engine;
    let b64 = base64::engine::general_purpose::STANDARD.encode(png);
    let reply = chat(endpoint, api_key, model, REGION_PROMPT, Some(&b64))?;
    let (w, h) = (img.width() as i32, img.height() as i32);
    let regions = parse_regions(&reply, w, h)?;
    Ok(regions
        .into_iter()
        .map(|(rect, kind)| {
            let fill = if kind == "text" {
                (0xc8, 0xc8, 0xc8)
            } else {
                dominant_color(img, rect)
            };
            let stroke = if kind == "image" { darker(fill) } else { fill };
            let _ = TEXT_FILL; // keep the named constant for greppability
            SimplifyRegion { rect, kind, fill: hex(fill), stroke: hex(stroke) }
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chat_url_normalizes() {
        assert_eq!(chat_url("https://x.ai"), "https://x.ai/v1/chat/completions");
        assert_eq!(chat_url("https://x.ai/v1/"), "https://x.ai/v1/chat/completions");
        assert_eq!(
            chat_url("https://x.ai/v1/chat/completions"),
            "https://x.ai/v1/chat/completions"
        );
    }

    #[test]
    fn extract_json_unwraps_fences_and_prose() {
        assert_eq!(extract_json("```json\n[1,2]\n```"), "[1,2]");
        assert_eq!(extract_json("Sure! here: [\"a\"] hope that helps"), "[\"a\"]");
        assert_eq!(extract_json("see [below] for {\"k\": 1}"), "{\"k\": 1}");
    }

    #[test]
    fn parse_tsv_keeps_only_word_rows() {
        let tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n\
                   1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t\n\
                   5\t1\t1\t1\t1\t1\t10\t20\t30\t12\t91.5\thello\n\
                   5\t1\t1\t1\t1\t2\t44\t20\t40\t12\t88.0\tworld";
        let words = parse_tsv(tsv);
        assert_eq!(words.len(), 2);
        assert_eq!(words[0].text, "hello");
        assert_eq!(words[1].x, 44);
    }

    #[test]
    fn match_spans_unions_multiword() {
        let words = vec![
            Word { text: "email:".into(), x: 0, y: 0, w: 50, h: 10 },
            Word { text: "jack@example.com".into(), x: 60, y: 0, w: 120, h: 10 },
        ];
        let rects = match_spans(&["jack@example.com".to_string()], &words);
        assert_eq!(rects, vec![RectPx { x: 60, y: 0, w: 120, h: 10 }]);
        let rects = match_spans(&["email: jack@example.com".to_string()], &words);
        assert_eq!(rects, vec![RectPx { x: 0, y: 0, w: 180, h: 10 }]);
    }

    #[test]
    fn parse_bboxes_clamps_and_scales() {
        let reply = r#"[{"x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.4}, {"x0": 2, "y0": 2, "x1": 3, "y1": 3}]"#;
        let rects = parse_bboxes(reply, 1000, 500).unwrap();
        assert_eq!(rects, vec![RectPx { x: 100, y: 100, w: 400, h: 100 }]);
    }

    #[test]
    fn parse_regions_accepts_wrapped_and_scattered() {
        let wrapped = r#"{"regions": [{"type": "text", "x0": 0, "y0": 0, "x1": 0.5, "y1": 0.1}]}"#;
        assert_eq!(parse_regions(wrapped, 100, 100).unwrap().len(), 1);
        let scattered = "1. {\"type\": \"chrome\", \"x0\": 0, \"y0\": 0, \"x1\": 1, \"y1\": 0.1}\n\
                         2. {\"type\": \"text\", \"x0\": 0, \"y0\": 0.2, \"x1\": 1, \"y1\": 0.3}";
        assert_eq!(parse_regions(scattered, 100, 100).unwrap().len(), 2);
    }

    #[test]
    fn truncated_reply_is_reported() {
        let err = parse_regions("[{\"type\": \"text\", \"x0\": 0", 100, 100).unwrap_err();
        assert!(err.contains("cut off"));
    }

    #[test]
    fn dominant_color_picks_majority() {
        let mut img = image::RgbaImage::from_pixel(64, 64, image::Rgba([10, 200, 30, 255]));
        for y in 0..8 {
            for x in 0..8 {
                img.put_pixel(x, y, image::Rgba([255, 0, 0, 255]));
            }
        }
        let c = dominant_color(&img, RectPx { x: 0, y: 0, w: 64, h: 64 });
        assert_eq!(c, (10, 200, 30));
    }
}
