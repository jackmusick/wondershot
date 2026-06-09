# Wondershot M4 — Native Recorder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).
> **HIGHEST-RISK MILESTONE.** The GStreamer-in-process pipeline + portal ScreenCast can't be headlessly verified end-to-end (they need a real Wayland session + the portal source picker). Strategy: port and exhaustively TEST the pure logic (pipeline-string builder, PTS/clock math, escalation, salvage, filename), and integration-VERIFY the GStreamer/portal pieces by construction (the crate builds, elements link, the pipeline reaches PLAYING against a test source). The actual live screen recording is a human-present check, flagged at exit.

**Goal:** Port Wondershot's Linux screen recorder from Python (xdg-desktop-portal ScreenCast + PipeWire + GStreamer via PyGObject) to native Rust (`ashpd` + `gstreamer-rs`), preserving the exact pipeline, pause/resume PTS handling, EOS-finalize escalation, and partial-salvage behavior; plus the countdown overlay and camera bubble as frameless Svelte windows. Wire `start_recording`/`stop`/`pause`/`resume` Tauri commands + `recording://` events into the shell's Record control.

**Architecture:** `wondershot-core` gains a `record` module: a PURE `build_pipeline_description()` (the `gst::parse::launch` string, ported verbatim from `record.py:build_pipeline_description`) + PURE clock/PTS/escalation helpers, both unit-tested as the parity oracle. A `recorder` runtime (gstreamer-rs) parses that description, runs the pipeline, installs the pause pad-probe, drives the EOS escalation ladder + watchdog, and manages the `.rendering` tmp + finalize/salvage. A `portal` module (ashpd) does the ScreenCast session and yields the PipeWire fd + node id. Tauri commands orchestrate; countdown + bubble are separate Tauri WebviewWindows.

**Tech Stack:** Rust, `gstreamer` (gstreamer-rs) + `gstreamer-base`, `ashpd` (ScreenCast), `pipewire` fd (from ashpd), `tokio`. Frontend: Svelte frameless windows.

**Parity oracle:** Python `wondershot/record.py`, `countdown.py`, `bubble.py` + tests `tests/test_record_pure.py`, `tests/test_record.py`, `tests/test_countdown.py`.

---

## Exact behavioral contract (from record.py — preserve verbatim)

- **Pipeline string** (`build_pipeline_description`, record.py:99-146): video branch
  `pipewiresrc fd={fd} path={node} do-timestamp=true ! queue ! videoconvert ! videorate ! video/x-raw,format=I420,framerate=30/1 ! identity name=pause ! x264enc speed-preset=veryfast tune=zerolatency bitrate=8000 key-int-max=120 ! h264parse ! queue ! mux. mp4mux name=mux ! filesink location={tmp}`.
  The `videorate ! ...,framerate=30/1` is the **no-PTS-fix** (pipewiresrc emits PTS-less damage frames). `identity name=pause` is the pause tap and MUST precede `x264enc` (drop/retime raw frames, never H.264 NALs).
- **Audio branch** (when `mic_enabled`): `pulsesrc device={dev} do-timestamp=true ! queue ! audioconvert ! audioresample ! [webrtcdsp ...] audioconvert ! avenc_aac bitrate=160000 ! aacparse ! queue ! mux.` — webrtcdsp only when `noise_suppression && have_webrtcdsp` with `echo-cancel=false noise-suppression=true noise-suppression-level=very-high gain-control=false high-pass-filter=true`, caps `audio/x-raw,rate=48000,channels=1`.
- **Portal ScreenCast** (record.py:363-512): CreateSession → SelectSources(`types=3` monitor|window, `multiple=false`, `cursor_mode=2` EMBEDDED, `persist_mode=0`) → Start → OpenPipeWireRemote → (fd, node). **persist_mode=0: always show the picker; never replay a saved token.** cursor_mode stays EMBEDDED (2), not METADATA (4).
- **Pause/resume** (record.py:251-285): pad probe on `identity.src`. While `dropping`, return DROP. On resume, accumulate `paused_offset_ns += clock.now - pause_started`; the probe subtracts the offset from each buffer's `pts`/`dts` (`max(0, pts - offset)`). Pure: `pts_offset_ns(s) = round(s * 1e9)`; `elapsed_seconds(started, now, paused_total, paused_at)` excludes paused spans.
- **Stop/finalize** (record.py:370-680): `send_eos()`; poll; escalation `GRACE_MS=5000` → `force_stop()` (set pipeline NULL) → `KILL_MS=10000` → force again. Success = EOS && tmp exists && size>0 → move `.rendering/<name>` → `library_dir/<name>`. Else **salvage**: keep non-zero tmp (move to out, report "partial recording kept"), delete zero-byte. `sweep_stale_tmp(dir, 3600)` on start removes orphan tmps older than 1h.
- **Filename:** `Recording_%Y%m%d_%H%M%S.mp4` (timestamp_name → .mp4). Tmp under `library_dir/.rendering/`.
- **Signals → events:** started, stopping, finished(path), failed(msg), tick(elapsed str), paused_changed(bool). Watchdog 1s tick (no tick while paused). `supports_pause=true`.
- **Countdown** (countdown.py): `record_countdown` secs (default 0=off); full-screen number counting down; Esc/click cancels (don't start); pressing Record during countdown cancels. 0 → start immediately.
- **Camera bubble** (bubble.py): frameless circular always-on-top webcam window (220px, scroll-resize 160–400, drag-move), shown during recording when a camera is configured; composites into the capture as an on-screen window.

---

## File Structure

```
crates/wondershot-core/src/record/
  mod.rs            # re-exports
  pipeline.rs       # PURE build_pipeline_description() + crop/halo prop helpers
  clock.rs          # PURE elapsed_seconds, pts_offset_ns, format_elapsed, escalation consts
  files.rs          # PURE recording_name, rendering tmp path, salvage decision, sweep decision
  recorder.rs       # gstreamer-rs runtime: pipeline, pause probe, EOS ladder, watchdog
  portal.rs         # ashpd ScreenCast session → (fd, node)
src-tauri/src/commands.rs   # start_recording/stop/pause/resume + recording:// events
src/lib/recorder/    # frontend: Record control state, countdown window, bubble window
src/routes/countdown/+page.svelte   # frameless countdown overlay window
src/routes/bubble/+page.svelte      # frameless camera bubble window
```

---

## Task 1: PURE pipeline-description builder (TDD)

**Files:** `crates/wondershot-core/src/record/pipeline.rs` (+ `pub mod record;` → `pub mod pipeline;`). Oracle: `tests/test_record_pure.py`.

- [ ] **Step 1: failing tests** porting test_record_pure.py assertions:
```rust
#[cfg(test)]
mod tests {
    use super::*;
    fn opts() -> PipelineOpts { PipelineOpts::default() }
    #[test] fn has_verbatim_no_pts_fix() {
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &opts());
        assert!(d.contains("videorate ! video/x-raw,format=I420,framerate=30/1"));
    }
    #[test] fn pause_tap_precedes_encoder() {
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &opts());
        let pause = d.find("identity name=pause").unwrap();
        let enc = d.find("x264enc").unwrap();
        assert!(pause < enc);
    }
    #[test] fn x264_settings_verbatim() {
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &opts());
        assert!(d.contains("x264enc speed-preset=veryfast tune=zerolatency bitrate=8000 key-int-max=120"));
        assert!(d.contains("mp4mux name=mux"));
        assert!(d.contains("filesink location=/tmp/x.mp4"));
        assert!(d.contains("pipewiresrc fd=7 path=42 do-timestamp=true"));
    }
    #[test] fn audio_included_when_mic_enabled() {
        let o = PipelineOpts { mic_enabled: true, mic_device: "alsa_input.x".into(), ..opts() };
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &o);
        assert!(d.contains("pulsesrc device=alsa_input.x do-timestamp=true"));
        assert!(d.contains("avenc_aac bitrate=160000"));
    }
    #[test] fn no_audio_when_mic_disabled() {
        let d = build_pipeline_description(7, 42, "/tmp/x.mp4", &opts());
        assert!(!d.contains("pulsesrc"));
    }
    #[test] fn webrtcdsp_only_when_available_and_enabled() {
        let on = PipelineOpts { mic_enabled:true, noise_suppression:true, have_webrtcdsp:true, ..opts() };
        assert!(build_pipeline_description(7,42,"/t.mp4",&on).contains("webrtcdsp"));
        let off = PipelineOpts { mic_enabled:true, noise_suppression:true, have_webrtcdsp:false, ..opts() };
        assert!(!build_pipeline_description(7,42,"/t.mp4",&off).contains("webrtcdsp"));
    }
}
```
- [ ] **Step 2-4:** implement `PipelineOpts { mic_enabled, mic_device, noise_suppression, have_webrtcdsp, crop: Option<(u32,u32,u32,u32)>, halo: bool }` (Default = all-off, video-only) and `build_pipeline_description(fd, node, tmp, opts) -> String` porting record.py:99-146 VERBATIM (same element order, properties, the videocrop branch when crop is set, the identity pause tap). Run to green.
- [ ] **Step 5: commit** — `M4: pure GStreamer pipeline-description builder (parity with record.py)`

---

## Task 2: PURE clock / PTS / escalation (TDD)

**Files:** `crates/wondershot-core/src/record/clock.rs`. Oracle: test_record_pure.py clock/PTS tests.

- [ ] **Step 1: failing tests**:
```rust
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn pts_offset_ns_converts_seconds() { assert_eq!(pts_offset_ns(1.5), 1_500_000_000); }
    #[test] fn elapsed_excludes_paused_total() {
        assert!((elapsed_seconds(Some(100.0), 110.0, 3.0, None) - 7.0).abs() < 1e-9);
    }
    #[test] fn elapsed_excludes_in_flight_pause() {
        assert!((elapsed_seconds(Some(100.0), 110.0, 0.0, Some(106.0)) - 6.0).abs() < 1e-9);
    }
    #[test] fn elapsed_none_start_is_zero() { assert_eq!(elapsed_seconds(None, 110.0, 0.0, None), 0.0); }
    #[test] fn format_elapsed_mmss() { assert_eq!(format_elapsed(65.0), "1:05"); assert_eq!(format_elapsed(5.0), "0:05"); }
    #[test] fn escalation_constants() { assert_eq!(GRACE_MS, 5000); assert_eq!(KILL_MS, 10000); }
}
```
- [ ] **Step 2-4:** implement `pts_offset_ns(f64)->i64`, `elapsed_seconds(Option<f64>, f64, f64, Option<f64>)->f64` (porting record.py:149-167), `format_elapsed(f64)->String` (`{m}:{ss:02}`), `pub const GRACE_MS: u64 = 5000; pub const KILL_MS: u64 = 10000;`. Green.
- [ ] **Step 5: commit** — `M4: pure clock/PTS/escalation helpers (parity)`

---

## Task 3: PURE files — name / tmp / salvage / sweep (TDD)

**Files:** `crates/wondershot-core/src/record/files.rs`.

- [ ] Port (with tests): `recording_name()` → `Recording_%Y%m%d_%H%M%S.mp4`; `rendering_dir(library_dir)` → `<lib>/.rendering`; a PURE `salvage_decision(tmp_exists, tmp_size) -> Salvage` enum (`MoveToOut` when exists&&size>0, `Delete` when exists&&size==0, `Nothing`); a PURE `is_stale(mtime_age_s, max_age=3600) -> bool`. Tests assert each. (The actual fs move/unlink lives in recorder.rs; these decide.)
- [ ] **commit** — `M4: pure recording filename + salvage/sweep decisions`

---

## Task 4: GStreamer recorder runtime (integration)

**Files:** `crates/wondershot-core/src/record/recorder.rs`. Add `gstreamer`, `gstreamer-base` deps. REQUIRES system GStreamer dev libs.

- [ ] **Step 1: toolchain check** — confirm `pkg-config --exists gstreamer-1.0` (the Python app uses system gstreamer; on Fedora install `gstreamer1-devel gstreamer1-plugins-base-devel` if missing). If absent and uninstallable, mark the gstreamer-dependent steps BLOCKED and report — the pure Tasks 1-3 still stand.
- [ ] **Step 2:** add to `crates/wondershot-core/Cargo.toml`: `gstreamer = "0.23"`, `gstreamer-base = "0.23"` (or current). `cargo build -p wondershot-core` must link.
- [ ] **Step 3:** implement a `Recorder` that: `gst::init()`; `gst::parse::launch(&build_pipeline_description(fd,node,tmp,opts))`; set PLAYING; install a BUFFER pad probe on the `identity name=pause` src pad implementing the drop/PTS-offset logic from clock.rs (`pts_offset_ns`); `pause()`/`resume()` toggle the dropping flag + accumulate the clock offset; `stop()` sends EOS then runs the escalation ladder (poll bus for EOS/ERROR, at GRACE_MS set state NULL, at KILL_MS again); on success move tmp→out, else apply `salvage_decision`. A watchdog (std thread or tokio interval) emits a tick (elapsed via clock.rs) each second unless paused, and detects pipeline ERROR → salvage. Expose a callback/channel for the lifecycle events (started/stopping/finished/failed/tick/paused_changed) that src-tauri forwards.
- [ ] **Step 4:** a smoke test that does NOT need the portal: build a description with `videotestsrc` substituted (add a test-only `build_test_description(tmp)` using `videotestsrc num-buffers=30 ! videoconvert ! x264enc ! mp4mux ! filesink`), run it to EOS, assert the output mp4 exists and is non-empty. This validates the gstreamer-rs runtime + EOS finalize WITHOUT a real screen. Gate behind `#[ignore]` or a feature if CI lacks gstreamer plugins; run it locally.
- [ ] **Step 5: commit** — `M4: gstreamer-rs recorder runtime — pipeline, pause probe, EOS ladder, salvage`

---

## Task 5: Portal ScreenCast session (integration)

**Files:** `crates/wondershot-core/src/record/portal.rs` (ashpd).

- [ ] Implement `async fn open_screencast() -> Result<(RawFd, u32), Error>` using `ashpd::desktop::screencast`: create session, `select_sources` with `SourceType::Monitor | Window`, `CursorMode::Embedded`, `PersistMode::DoNot` (never persist/replay), `start`, then `open_pipe_wire_remote` → fd; take the first stream's node id. Match the Python options exactly (types=monitor|window, multiple=false, cursor embedded, persist none).
- [ ] No unit test (interactive); document the interface. Confirm it compiles against ashpd.
- [ ] **commit** — `M4: ashpd ScreenCast session → (pipewire fd, node)`

---

## Task 6: Tauri commands + events + tray

**Files:** `src-tauri/src/commands.rs`, `lib.rs`.

- [ ] `start_recording(app)`: load Settings; `sweep_stale_tmp`; open portal → (fd,node); build opts from settings (mic, device, noise, crop); create Recorder with tmp under `.rendering`; wire its lifecycle callbacks to emit `recording://state` (a struct {status:'idle'|'recording'|'stopping', paused, elapsed}) and `recording://tick`/`recording://done`(path)/`recording://failed`. `stop_recording`/`pause_recording`/`resume_recording`. Hold the Recorder in Tauri managed state (Mutex). Register; build clean.
- [ ] Tray: the existing tray gets a "Record / Stop" toggle that invokes the same path.
- [ ] **commit** — `M4: recording Tauri commands + events + tray toggle`

---

## Task 7: Countdown overlay window (frontend)

**Files:** `src/routes/countdown/+page.svelte`, window creation in the Record flow.

- [ ] A frameless, always-on-top, transparent Tauri `WebviewWindow` showing a large countdown number (from `record_countdown`), counting down each second; Esc or click cancels (emit cancel → don't start); on reaching 0, signal start + close. Pressing Record again during countdown cancels. 0 → skip. Mirror countdown.py semantics. A small Vitest for the pure countdown tick (seconds→display, reaches zero→fire) if logic is extractable.
- [ ] **commit** — `M4: countdown overlay window`

---

## Task 8: Camera bubble window (frontend)

**Files:** `src/routes/bubble/+page.svelte`.

- [ ] A frameless, always-on-top, transparent circular webcam window using `getUserMedia` (no Rust webcam plumbing); 220px, scroll-resize 160–400, drag-move; circular clip + white border. Shown during recording when a camera is configured (a setting). It's an on-screen window the screen recorder captures naturally. Mirror bubble.py look.
- [ ] **commit** — `M4: camera bubble window (getUserMedia, frameless)`

---

## Task 9: Frontend Record control wiring

**Files:** `src/lib/components/CaptureHeader.svelte` (Record button), `src/lib/stores.ts` (`recording` store), mock.

- [ ] Wire the Record button: start → (countdown if set) → `start_recording`; while recording show elapsed (drive from `recording://tick`/`state`) + Pause/Stop controls; Pause→`pause_recording`. Update the `recording` store from `recording://state`. Mock handlers so browser dev shows a simulated recording state (tick via a JS interval in mock mode). UI-review the recording state of the header.
- [ ] **commit** — `M4: wire Record control (start/pause/stop, live timer); mock parity`

---

## Task 10: M4 exit verification

- [ ] `cargo test --workspace` (pure record tests green) + `cargo build --workspace` (incl. gstreamer/ashpd) clean; `npm run test` + `npm run build` green; UI-review the recording header state.
- [ ] **Human-present check (documented, not automated):** on a real Wayland session, Record → portal picker → record 5s → Pause → Resume → Stop → a valid `Recording_*.mp4` lands in the library and plays; pause produces no gap; Ctrl-C mid-record leaves a salvageable partial. Document the outcome / leave as the one manual gate.
- [ ] Tag — `git tag m4-recorder && git commit --allow-empty -m "M4 complete: native recorder green (live capture pending human-present check)"`.

---

## Self-Review notes (author)

- **Spec coverage:** pipeline string ✓ T1; PTS/clock/escalation ✓ T2; filename/salvage/sweep ✓ T3; gstreamer runtime + pause probe + EOS ladder ✓ T4; portal session ✓ T5; commands/events/tray ✓ T6; countdown ✓ T7; bubble ✓ T8; frontend ✓ T9; oracle tests ported ✓ T1-T3 (+ T4 videotestsrc smoke).
- **Risk concentration (honest):** T4 (gstreamer-rs runtime) and T5 (ashpd portal) are the hard, least-headlessly-testable pieces. T4's videotestsrc smoke test validates the pipeline/EOS machinery without a screen; the real pipewiresrc capture is only exercisable on a live Wayland session (the documented exit gate). The pure builders (T1-T3) lock the parity-critical strings/math with full unit tests.
- **Toolchain dependency:** T4 needs system `gstreamer-1.0` + plugins (base, good, bad for x264enc/webrtcdsp). If missing locally, T1-T3 still complete; T4+ gate on installing them.
- **Type consistency:** `PipelineOpts` (T1) is the single options struct used by the recorder (T4) and command (T6); `GRACE_MS/KILL_MS/pts_offset_ns/elapsed_seconds` (T2) used by the runtime (T4); `salvage_decision` (T3) used by finalize (T4).
```
