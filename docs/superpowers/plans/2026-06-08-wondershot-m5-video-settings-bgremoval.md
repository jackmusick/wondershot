# Wondershot M5 — Video + Settings + BG-Removal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Port three independent subsystems: (A) the video player with range-blur redaction + GIF export + frame grab (ffmpeg arg builders in Rust, HTML5 `<video>` UI in Svelte); (B) the Settings dialog (complete the Rust settings struct + a tabbed Svelte modal wired to get/set); (C) AI background removal (`ort` + u2net ONNX, wired into the editor's "Remove BG" as a base-image push).

**Architecture:** `wondershot-core` gains a `video` module (PURE ffmpeg arg/filter builders, unit-tested) and a `bgremove` module (`ort` ONNX inference). `src-tauri` adds commands that spawn the bundled `ffmpeg` for blur/gif/frame/trim and call bgremove. The frontend adds a `VideoPlayer.svelte` (HTML5 video + timeline redaction overlay + GIF dialog), a `Settings.svelte` tabbed modal, and an editor "Remove BG" action. Settings persist via `set_settings` writing the same `wondershot.conf`.

**Out of scope (not in the rewrite roadmap):** cloud sharing (S3/Azure/OneDrive) and the AI-chat endpoint settings — those Python features were never part of the 7-milestone parity plan; their settings keys are omitted here.

**Parity oracle:** Python `wondershot/video.py`, `bgremove.py`, `settings.py` + tests `tests/test_video_filter.py`, `tests/test_bgremove.py`, `tests/test_settings_*.py`, `tests/test_video_pane.py`.

---

## Behavioral contract (from video.py / bgremove.py — preserve)

- **build_blur_filter(redactions, blur=14, video_w, video_h) -> (graph, out_label):** `[0:v]split={n+1}[base][c0][c1]…`; per redaction `[ci]crop={w}:{h}:{x}:{y},boxblur={blur}[bi]` then `[{cur}][bi]overlay={x}:{y}:enable='between(t,{start:.3f},{end:.3f})'[v{i}]`, chaining cur=v{i}. Even-align: `w=max(4,w-w%2)`, `x=x-x%2` (same y/h). Clamp to frame when video_w/h given (`x=min(x,video_w-4)` etc.). Semicolon-joined.
- **Render:** `ffmpeg -y -i {src} -filter_complex {graph} -map [{out}] -map 0:a? {audio} -c:v libx264 -crf 20 -preset veryfast -movflags +faststart {out_file}`; audio `-c:a copy` unless container changes then `-c:a aac -b:a 160k`. Output `<stem>-redacted.<ext>` (mp4 unless src webm). Temp in `.rendering/`.
- **build_gif_args(src,out,fps=12,max_width=720,start?,end?):** `["-y", (start/end? "-ss {start:.3f} -to {end:.3f}"), "-i", src, "-vf", "fps={fps},scale='min({max_width},iw)':-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse", out]`. Output `<stem>.gif`.
- **build_frame_grab_args(src,position_s,out):** `["-y","-ss","{position_s:.3f}","-i",src,"-frames:v","1",out]`. Output `<stem>-frame.png`.
- **build_trim_args(src,start,end,out,reencode,encoder):** input-stage `-ss`/`-to`; `-c copy` when not reencode else `-c:v {encoder} -crf 20 -preset veryfast` + audio aac; container constraint (mp4 unless src is mp4/m4v/mov). Output `<stem>-trimmed.<ext>`.
- **bgremove:** u2net.onnx; input (1,3,320,320), ImageNet normalize (mean .485/.456/.406, std .229/.224/.225), resize 320×320; output (1,1,320,320) mask ch0; normalize to [0,1]→alpha, resize to original (lanczos), composite as the image's alpha → ARGB. In the editor: "Remove BG" pushes the old base (M3 base stack) then SetBaseImage (keeps annotations).
- **Settings keys to ADD** (beyond existing): `hotkey_capture`(str, "Ctrl+Shift+Print"), `copy_after_capture`(bool true), `show_gallery_after_capture`(bool true), `pin_on_top`(bool false), `quick_bar_enabled`(bool true), `quick_bar_timeout`(int 8), `stroke_width`(int 10), `font_size`(int 24), `tool_color`(str "#e3242b"), `video_blur_strength`(int 14), `gif_fps`(int 12), `gif_max_width`(int 720). (effect_* already planned in M3; ensure present.)

---

## File Structure

```
crates/wondershot-core/src/video.rs       # PURE ffmpeg arg/filter builders + output names
crates/wondershot-core/src/bgremove.rs     # ort u2net inference (preprocess/infer/composite)
crates/wondershot-core/src/settings.rs     # +the M5 keys
src-tauri/src/commands.rs                   # apply_blur/export_gif/grab_frame/trim_video/remove_background/set_settings
src/lib/video/VideoPlayer.svelte            # HTML5 video + timeline + redaction overlay + GIF dialog
src/lib/components/Settings.svelte          # tabbed settings modal
src/lib/editor/EditorToolbar.svelte         # +Remove BG action
src/lib/components/ContentView.svelte       # mount VideoPlayer when activeItem.kind==='video'
```

---

## Task 1: PURE ffmpeg builders (TDD)

**Files:** `crates/wondershot-core/src/video.rs` (+ `pub mod video;`). Oracle: `tests/test_video_filter.py`.

- [ ] **Step 1: failing tests** porting test_video_filter.py assertions:
```rust
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn single_redaction_graph() {
        let r = vec![Redaction { x:100, y:50, w:200, h:120, start:2.0, end:6.5 }];
        let (g, out) = build_blur_filter(&r, 14, 0, 0);
        assert!(g.contains("split=2[base][c0]"));
        assert!(g.contains("[c0]crop=200:120:100:50,boxblur=14[b0]"));
        assert!(g.contains("[base][b0]overlay=100:50:enable='between(t,2.000,6.500)'[v0]"));
        assert_eq!(out, "v0");
    }
    #[test] fn odd_dims_rounded_even() {
        let r = vec![Redaction { x:11, y:7, w:101, h:51, start:0.0, end:1.0 }];
        let (g, _) = build_blur_filter(&r, 14, 0, 0);
        assert!(g.contains("crop=100:50:10:6"));
    }
    #[test] fn multiple_redactions_chain() {
        let r = vec![
            Redaction{x:0,y:0,w:10,h:10,start:0.0,end:1.0},
            Redaction{x:20,y:20,w:10,h:10,start:1.0,end:2.0}];
        let (g, out) = build_blur_filter(&r, 14, 0, 0);
        assert!(g.contains("split=3[base][c0][c1]"));
        assert!(g.contains("[v0][b1]overlay=20:20:enable='between(t,1.000,2.000)'[v1]"));
        assert_eq!(out, "v1");
    }
    #[test] fn gif_args_with_range() {
        let a = build_gif_args("/in.mp4", "/out.gif", 12, 720, Some(1.0), Some(3.0));
        assert_eq!(a, vec!["-y","-ss","1.000","-to","3.000","-i","/in.mp4","-vf",
            "fps=12,scale='min(720,iw)':-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse","/out.gif"]);
    }
    #[test] fn gif_args_no_range() {
        let a = build_gif_args("/in.mp4", "/out.gif", 12, 720, None, None);
        assert_eq!(a[0], "-y"); assert_eq!(a[1], "-i");
    }
    #[test] fn frame_grab_args() {
        assert_eq!(build_frame_grab_args("/in.mp4", 2.5, "/f.png"),
            vec!["-y","-ss","2.500","-i","/in.mp4","-frames:v","1","/f.png"]);
    }
    #[test] fn blur_strength_override() {
        let r = vec![Redaction{x:0,y:0,w:10,h:10,start:0.0,end:1.0}];
        assert!(build_blur_filter(&r, 30, 0, 0).0.contains("boxblur=30"));
    }
}
```
- [ ] **Step 2-4:** implement `Redaction { x:i64,y:i64,w:i64,h:i64,start:f64,end:f64 }`, `build_blur_filter`, `build_gif_args`, `build_frame_grab_args`, `build_trim_args`, output-name helpers (`redacted_name`/`gif_name`/`frame_name`/`trimmed_name`), porting video.py verbatim. Green.
- [ ] **Step 5: commit** — `M5: pure ffmpeg arg/filter builders (blur/gif/frame/trim) — parity`

---

## Task 2: Video commands + VideoPlayer UI

**Files:** `src-tauri/src/commands.rs`, `src/lib/video/VideoPlayer.svelte`, `ContentView.svelte`, mock.

- [ ] **Commands** (spawn bundled ffmpeg via `tokio::process`, tmp in `.rendering`, move to library on success): `grab_frame(path, pos) -> png path`; `apply_blur(path, redactions: Vec<Redaction>, blur) -> out path`; `export_gif(path, fps, max_width, start?, end?) -> out path`; `trim_video(path, start, end, reencode) -> out path`. Use `video::build_*` for the args. Find ffmpeg (bundled or PATH — reuse the M2 ffmpeg discovery if present, else `which ffmpeg`).
- [ ] **VideoPlayer.svelte:** HTML5 `<video>` (src via assetSrc), play/pause, timeline slider + time labels, frame-stepping. A **redaction overlay**: when paused, drag boxes on the video; a timeline RangeBar showing each redaction's start/end span (draggable edges/move); a blur-strength control; an "Apply blur" button → `apply_blur` → reload. A **GIF dialog**: fps/width/time-range → `export_gif`. Mount in ContentView when `activeItem.kind === 'video'`.
- [ ] Mock: `grab_frame`/`apply_blur`/`export_gif`/`trim_video` return a placeholder path so browser dev doesn't crash.
- [ ] Tests: a small TS test for the redaction→args mapping if extractable; UI-review the video player screen.
- [ ] **commit** — `M5: video commands (blur/gif/frame/trim) + VideoPlayer UI`

---

## Task 3: BG-removal (ort + u2net)

**Files:** `crates/wondershot-core/src/bgremove.rs` (+ `ort` dep), `src-tauri/src/commands.rs`, editor wiring.

- [ ] Add `ort` (ONNX Runtime) + `ndarray` deps. Implement `remove_background(rgba: &RgbaImage, model_path: &Path) -> RgbaImage`: resize to 320×320, ImageNet-normalize to an (1,3,320,320) f32 tensor, run the u2net session, take output (1,1,320,320) ch0, normalize to [0,1], resize the mask to the original size (lanczos via `image`), set it as the image's alpha. Unit-test the PURE preprocessing (a tiny helper `normalize_input(img)->Vec<f32>` with the exact mean/std + shape) and the mask→alpha composite (`apply_mask(img, mask)`), WITHOUT needing the model. Gate the actual inference behind the model file's presence.
- [ ] **Model acquisition:** a `model_path()` → `~/.cache/wondershot/u2net.onnx`; a command `ensure_bg_model() -> Result<bool>` that downloads u2net.onnx (URL from rembg releases, verify md5 `60024c5c889badc19c04ad937298a77b`) if absent — OR document that the model is bundled in packaging (M6). For M5: download-on-first-use with the md5 check; if download infra is heavy, implement `ensure_bg_model` to check presence and return false (UI shows "not available"), and note the model must be placed manually until M6 bundles it.
- [ ] **Command** `remove_background(path) -> base64 PNG` (load image, run, return rgba PNG). Register.
- [ ] **Editor wiring:** EditorToolbar "Remove BG" button (disabled if model absent): calls `remove_background(activeItem.path)`, then sets the editor base to the result via the M3 base-push + SetBaseImage path (records old base, keeps annotations), like crop but non-destructive of annotations.
- [ ] **commit** — `M5: bg-removal (ort + u2net) + editor Remove BG action`

---

## Task 4: Settings struct + Settings modal

**Files:** `crates/wondershot-core/src/settings.rs`, `src-tauri/src/commands.rs` (`set_settings`), `src/lib/components/Settings.svelte`.

- [ ] **Rust settings:** add the M5 keys (hotkey_capture, copy_after_capture, show_gallery_after_capture, pin_on_top, quick_bar_enabled, quick_bar_timeout, stroke_width, font_size, tool_color, video_blur_strength, gif_fps, gif_max_width, effect_*) to the struct+Default+from_conf_str with Python-parity defaults; add a `to_conf_str()` serializer + `save()` (write `wondershot.conf`); a `set_settings(values: serde_json::Value)` command that updates + saves. Tests for the new keys' defaults/parse + a save→load round-trip.
- [ ] **Settings.svelte:** a tabbed modal (wonderblob `.panel` pattern) — tabs General / Capture / Recording / Output — exposing the relevant settings (library dir, extra dirs, backend, capture cursor/delay, copy-after, show-after, quick bar, mic/camera/noise/countdown/halo, effects rounded/fade, video blur strength, gif fps/width, editor stroke/font/color). Bind to `get_settings`/`set_settings`. Open from the sidebar gear (M1). Hotkey rebinding: a key-capture field that stores `hotkey_capture` (on Linux it's informational — KGlobalAccel binding is manual; show the guidance, matching Python).
- [ ] UI-review the settings modal.
- [ ] **commit** — `M5: settings struct completion + tabbed Settings modal (get/set/save)`

---

## Task 5: M5 exit verification

- [ ] `cargo test --workspace` (video + bgremove pure + settings tests green) + `cargo build --workspace` clean; `npm run test` + `npm run build` green; UI-review the video player + settings modal.
- [ ] Manual note (display run): open a recording → scrub, draw a redaction, Apply blur → a `-redacted.mp4` lands and plays; export GIF; open Settings, change a value, reopen → persisted; (if model present) Remove BG on an image → transparent base. Document outcome.
- [ ] Tag — `git tag m5-video-settings && git commit --allow-empty -m "M5 complete: video + settings + bg-removal green"`.

---

## Self-Review notes (author)

- **Spec coverage:** ffmpeg builders (blur/gif/frame/trim) ✓ T1; video commands + player UI ✓ T2; bg-removal ort+u2net + editor action ✓ T3; settings struct + modal ✓ T4; oracle tests ported ✓ T1/T3/T4.
- **Pure vs heavy:** the ffmpeg arg/filter builders (T1) and the bg-removal preprocessing/composite (T3) are pure + unit-tested; ffmpeg spawning + ONNX inference + the video UI are integration, verified by build + a display-run manual gate.
- **Model handling:** u2net.onnx (~168MB) is download-on-first-use (md5-checked) in M5; M6 packaging decides bundle-vs-download. If download is impractical in the build env, `ensure_bg_model` returns false and the UI disables Remove BG until the model is present.
- **Out of scope:** cloud sharing + AI-chat endpoint (not in the roadmap) — omitted.
- **Type consistency:** `Redaction` (T1) is the shape the `apply_blur` command (T2) and frontend overlay serialize; settings keys (T4) match the get_settings JSON the frontend reads; bgremove output feeds the M3 base-push path (T3).
```
