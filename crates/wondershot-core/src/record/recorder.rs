//! GStreamer recorder runtime — owns a real `gst::Pipeline`.
//!
//! Ports the runtime behaviour of `wondershot/record.py`:
//!   - pause/resume via a BUFFER pad probe on `identity name=pause`
//!     (record.py:251-285): drop buffers while paused, then rewrite PTS/DTS
//!     of resumed buffers so mp4mux sees a gap-free stream.
//!   - the EOS escalation ladder on stop (record.py:653-680 `_poll_exit`):
//!     send EOS, wait GRACE_MS for the bus EOS, force NULL, wait KILL_MS,
//!     force again.
//!   - salvage-on-failure (record.py:640-651 `_salvage_partial`) using the
//!     pure `salvage_decision`.
//!   - a 1s watchdog (record.py:610-638 `_check_alive`) emitting Tick and
//!     surfacing a bus ERROR while recording as Failed.
//!
//! The pure decisions (clock math, salvage choice) live in the sibling
//! modules; only the GStreamer + filesystem side-effects live here.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use gstreamer as gst;
use gst::prelude::*;

use super::clock::{elapsed_seconds, format_elapsed, GRACE_MS, KILL_MS};
use super::files::{salvage_decision, Salvage};

/// Lifecycle events the runtime emits. `src-tauri` forwards these to the
/// webview. Mirrors the Qt signals on `ScreenRecorder` (record.py:298-303).
#[derive(Debug, Clone)]
pub enum RecEvent {
    Started,
    Stopping,
    Finished(PathBuf),
    Failed(String),
    Tick(String), // format_elapsed
    PausedChanged(bool),
}

/// Bus state latched by the single bus-draining thread. Both the watchdog
/// logic and `stop()` read these flags instead of popping the bus directly
/// (a filtered pop discards non-matching messages, so only ONE consumer may
/// own the bus — this struct is that shared latch).
struct BusState {
    eos: AtomicBool,
    error: Mutex<Option<String>>,
}

/// Shared state read/written by the pause probe and the control methods.
struct PauseState {
    /// While true the probe drops every buffer (record.py:275-276).
    dropping: AtomicBool,
    /// Accumulated paused duration in ns, subtracted from buffer PTS/DTS on
    /// resume so the stream stays gap-free (record.py:270, 278-284).
    paused_offset_ns: AtomicI64,
    /// Clock time captured when the current pause began (record.py:258-259).
    pause_started_ns: AtomicI64,
}

pub struct Recorder {
    pipeline: gst::Pipeline,
    pause: Arc<PauseState>,
    tmp: PathBuf,
    out: PathBuf,
    on_event: Arc<dyn Fn(RecEvent) + Send + Sync + 'static>,
    /// Set when stop() begins so the watchdog stops emitting ticks / handling
    /// errors itself and hands the exit path to stop() (record.py:624-625).
    stopping: Arc<AtomicBool>,
    /// Tells the bus-draining thread to terminate (set after finalize).
    shutdown: Arc<AtomicBool>,
    watchdog: Option<std::thread::JoinHandle<()>>,
    /// Shared bus latch (EOS + error) — the single source of truth for both
    /// the watchdog and stop().
    bus_state: Arc<BusState>,
}

impl Recorder {
    /// Build from a full pipeline DESCRIPTION string (from
    /// `build_pipeline_description`) plus the tmp/out paths. `on_event` is
    /// invoked for every lifecycle event.
    pub fn launch(
        description: &str,
        tmp: PathBuf,
        out: PathBuf,
        on_event: impl Fn(RecEvent) + Send + Sync + 'static,
    ) -> Result<Self, String> {
        gst::init().map_err(|e| format!("gst init failed: {e}"))?;

        let element = gst::parse::launch(description)
            .map_err(|e| format!("parse_launch failed: {e}"))?;
        let pipeline = element
            .downcast::<gst::Pipeline>()
            .map_err(|_| "pipeline description did not yield a gst::Pipeline".to_string())?;

        let on_event: Arc<dyn Fn(RecEvent) + Send + Sync> = Arc::new(on_event);
        let pause = Arc::new(PauseState {
            dropping: AtomicBool::new(false),
            paused_offset_ns: AtomicI64::new(0),
            pause_started_ns: AtomicI64::new(0),
        });

        // Install the pause probe on identity:src (record.py:262-264). The
        // probe is always installed (unlike the lazy install in Python) so
        // the PTS rewrite is in place the moment a resume happens.
        if let Some(elem) = pipeline.by_name("pause") {
            if let Some(pad) = elem.static_pad("src") {
                let pstate = pause.clone();
                pad.add_probe(gst::PadProbeType::BUFFER, move |_pad, info| {
                    pause_probe(&pstate, info)
                });
            }
        }

        pipeline
            .set_state(gst::State::Playing)
            .map_err(|e| format!("set PLAYING failed: {e}"))?;

        let stopping = Arc::new(AtomicBool::new(false));
        let shutdown = Arc::new(AtomicBool::new(false));
        let bus_state = Arc::new(BusState {
            eos: AtomicBool::new(false),
            error: Mutex::new(None),
        });
        let started_at = Instant::now();

        // Watchdog: 1s tick + bus ERROR/EOS draining (record.py:610-638). It
        // is the single owner of the bus and latches EOS/ERROR into bus_state.
        let watchdog = spawn_watchdog(
            pipeline.clone(),
            pause.clone(),
            stopping.clone(),
            shutdown.clone(),
            bus_state.clone(),
            tmp.clone(),
            out.clone(),
            on_event.clone(),
            started_at,
        );

        on_event(RecEvent::Started);

        Ok(Self {
            pipeline,
            pause,
            tmp,
            out,
            on_event,
            stopping,
            shutdown,
            watchdog: Some(watchdog),
            bus_state,
        })
    }

    /// Gate the pause identity: drop buffers and remember when
    /// (record.py:251-264).
    pub fn pause(&self) {
        if !self.pause.dropping.load(Ordering::SeqCst) {
            let now = self.clock_now_ns();
            self.pause.pause_started_ns.store(now, Ordering::SeqCst);
            self.pause.dropping.store(true, Ordering::SeqCst);
            (self.on_event)(RecEvent::PausedChanged(true));
        }
    }

    /// Accumulate the paused span and re-open the gate (record.py:266-271).
    pub fn resume(&self) {
        if self.pause.dropping.load(Ordering::SeqCst) {
            let now = self.clock_now_ns();
            let started = self.pause.pause_started_ns.load(Ordering::SeqCst);
            let delta = (now - started).max(0);
            self.pause
                .paused_offset_ns
                .fetch_add(delta, Ordering::SeqCst);
            self.pause.dropping.store(false, Ordering::SeqCst);
            (self.on_event)(RecEvent::PausedChanged(false));
        }
    }

    /// Send EOS, run the escalation ladder, finalize or salvage
    /// (record.py:370-380 stop + 653-680 _poll_exit).
    pub fn stop(mut self) {
        // Hand the exit path to stop(): the watchdog stops emitting ticks and
        // stops auto-handling errors, but keeps draining the bus into
        // bus_state so we can observe EOS/ERROR here (record.py:624-625).
        self.stopping.store(true, Ordering::SeqCst);
        (self.on_event)(RecEvent::Stopping);

        self.pipeline.send_event(gst::event::Eos::new());

        // Escalation ladder. `forced` mirrors record.py's `_forced`: once we
        // set NULL the pipeline posts neither EOS nor ERROR, so a wedged
        // pipeline must be treated as a non-clean give-up rather than waited
        // on forever.
        let mut reached_eos = false;
        let mut error_msg: Option<String> = None;
        let mut forced = false;
        let start = Instant::now();

        loop {
            if self.bus_state.eos.load(Ordering::SeqCst) {
                reached_eos = true;
                break;
            }
            if let Some(text) = self.bus_state.error.lock().unwrap().clone() {
                error_msg = Some(text);
                break;
            }

            let elapsed = start.elapsed().as_millis() as u64;
            if elapsed >= KILL_MS {
                // hard give-up (record.py:658-659)
                let _ = self.pipeline.set_state(gst::State::Null);
                forced = true;
                break;
            } else if elapsed >= GRACE_MS && !forced {
                // abandon the wedged EOS wait (record.py:660-662)
                let _ = self.pipeline.set_state(gst::State::Null);
                forced = true;
            }
            std::thread::sleep(Duration::from_millis(50));
        }

        // Stop the bus-draining thread and join it.
        self.shutdown.store(true, Ordering::SeqCst);
        if let Some(h) = self.watchdog.take() {
            let _ = h.join();
        }

        // If we forced and never saw a real error, that is the non-clean
        // give-up message (record.py:243-244).
        if forced && error_msg.is_none() && !reached_eos {
            error_msg = Some("force-stopped (EOS wait abandoned)".to_string());
        }
        if error_msg.is_none() {
            error_msg = self.bus_state.error.lock().unwrap().clone();
        }

        self.finalize(reached_eos, error_msg);
    }

    pub fn supports_pause() -> bool {
        true
    }

    fn clock_now_ns(&self) -> i64 {
        clock_time_ns(self.pipeline.clock())
    }

    /// Move tmp→out on a clean EOS, otherwise salvage. Always sets NULL.
    fn finalize(&self, reached_eos: bool, error_msg: Option<String>) {
        let tmp_meta = std::fs::metadata(&self.tmp).ok();
        let tmp_size = tmp_meta.as_ref().map(|m| m.len()).unwrap_or(0);
        let tmp_exists = tmp_meta.is_some();

        let clean = reached_eos && tmp_exists && tmp_size > 0;

        if clean {
            ensure_parent(&self.out);
            match std::fs::rename(&self.tmp, &self.out).or_else(|_| move_file(&self.tmp, &self.out))
            {
                Ok(()) => (self.on_event)(RecEvent::Finished(self.out.clone())),
                Err(e) => (self.on_event)(RecEvent::Failed(format!(
                    "recording finalize move failed: {e}"
                ))),
            }
        } else {
            let tail = error_msg.unwrap_or_else(|| "unknown".to_string());
            let partial = match salvage_decision(tmp_exists, tmp_size) {
                Salvage::MoveToOut => {
                    ensure_parent(&self.out);
                    if std::fs::rename(&self.tmp, &self.out)
                        .or_else(|_| move_file(&self.tmp, &self.out))
                        .is_ok()
                    {
                        format!(
                            "; partial recording kept: {}",
                            self.out
                                .file_name()
                                .map(|n| n.to_string_lossy().into_owned())
                                .unwrap_or_default()
                        )
                    } else {
                        String::new()
                    }
                }
                Salvage::Delete => {
                    let _ = std::fs::remove_file(&self.tmp);
                    String::new()
                }
                Salvage::Nothing => String::new(),
            };
            (self.on_event)(RecEvent::Failed(format!(
                "recording did not finalize: {tail}{partial}"
            )));
        }

        let _ = self.pipeline.set_state(gst::State::Null);
    }
}

/// The BUFFER pad probe (record.py:273-285). Drops while paused, otherwise
/// rewrites PTS/DTS by the accumulated paused offset.
fn pause_probe(pause: &PauseState, info: &mut gst::PadProbeInfo) -> gst::PadProbeReturn {
    if pause.dropping.load(Ordering::SeqCst) {
        return gst::PadProbeReturn::Drop;
    }
    let offset = pause.paused_offset_ns.load(Ordering::SeqCst);
    if offset != 0 {
        if let Some(gst::PadProbeData::Buffer(buffer)) = &mut info.data {
            let buf = buffer.make_mut();
            let off = gst::ClockTime::from_nseconds(offset as u64);
            if let Some(pts) = buf.pts() {
                buf.set_pts(Some(pts.saturating_sub(off)));
            }
            if let Some(dts) = buf.dts() {
                buf.set_dts(Some(dts.saturating_sub(off)));
            }
        }
    }
    gst::PadProbeReturn::Ok
}

/// Read the pipeline clock in ns, gracefully treating a None clock as 0
/// (record.py:258-259, 268-269).
fn clock_time_ns(clock: Option<gst::Clock>) -> i64 {
    clock
        .and_then(|c| c.time())
        .map(|t| t.nseconds() as i64)
        .unwrap_or(0)
}

#[allow(clippy::too_many_arguments)]
fn spawn_watchdog(
    pipeline: gst::Pipeline,
    pause: Arc<PauseState>,
    stopping: Arc<AtomicBool>,
    shutdown: Arc<AtomicBool>,
    bus_state: Arc<BusState>,
    tmp: PathBuf,
    out: PathBuf,
    on_event: Arc<dyn Fn(RecEvent) + Send + Sync + 'static>,
    started_at: Instant,
) -> std::thread::JoinHandle<()> {
    // This thread is the SINGLE owner of the bus: a filtered pop discards
    // non-matching messages, so EOS and ERROR must both be drained here and
    // latched into bus_state. stop() and the tick logic read those flags.
    std::thread::spawn(move || {
        let bus = pipeline.bus();
        let mut next_tick = Instant::now() + Duration::from_secs(1);
        loop {
            if shutdown.load(Ordering::SeqCst) {
                return; // stop() finished; tear down the thread
            }

            // Drain ERROR + EOS, latching into bus_state (record.py:214-233).
            if let Some(bus) = &bus {
                while let Some(msg) =
                    bus.pop_filtered(&[gst::MessageType::Error, gst::MessageType::Eos])
                {
                    match msg.view() {
                        gst::MessageView::Eos(_) => {
                            bus_state.eos.store(true, Ordering::SeqCst);
                        }
                        gst::MessageView::Error(e) => {
                            let text = e.error().to_string();
                            *bus_state.error.lock().unwrap() = Some(text);
                        }
                        _ => {}
                    }
                }
            }

            // While stopping, stop() owns finalize/salvage — the watchdog only
            // keeps draining the bus (record.py:624-625).
            if stopping.load(Ordering::SeqCst) {
                std::thread::sleep(Duration::from_millis(20));
                continue;
            }

            // A bus ERROR while recording == watchdog death: salvage + Failed
            // then exit (record.py:626-636).
            let err = bus_state.error.lock().unwrap().clone();
            if let Some(text) = err {
                let tmp_meta = std::fs::metadata(&tmp).ok();
                let size = tmp_meta.as_ref().map(|m| m.len()).unwrap_or(0);
                let exists = tmp_meta.is_some();
                let partial = match salvage_decision(exists, size) {
                    Salvage::MoveToOut => {
                        ensure_parent(&out);
                        if std::fs::rename(&tmp, &out)
                            .or_else(|_| move_file(&tmp, &out))
                            .is_ok()
                        {
                            format!(
                                "; partial recording kept: {}",
                                out.file_name()
                                    .map(|n| n.to_string_lossy().into_owned())
                                    .unwrap_or_default()
                            )
                        } else {
                            String::new()
                        }
                    }
                    Salvage::Delete => {
                        let _ = std::fs::remove_file(&tmp);
                        String::new()
                    }
                    Salvage::Nothing => String::new(),
                };
                let _ = pipeline.set_state(gst::State::Null);
                on_event(RecEvent::Failed(format!("recorder died: {text}{partial}")));
                return;
            }

            let now = Instant::now();
            if now >= next_tick {
                next_tick = now + Duration::from_secs(1);
                if !pause.dropping.load(Ordering::SeqCst) {
                    let secs = elapsed_seconds(
                        Some(0.0),
                        started_at.elapsed().as_secs_f64(),
                        // paused_total + in-flight pause are tracked on the
                        // gst clock; for the tick we approximate using live
                        // wall time minus the accumulated paused offset.
                        pause.paused_offset_ns.load(Ordering::SeqCst) as f64 / 1e9,
                        None,
                    );
                    on_event(RecEvent::Tick(format_elapsed(secs)));
                }
            }

            std::thread::sleep(Duration::from_millis(100));
        }
    })
}

fn ensure_parent(p: &std::path::Path) {
    if let Some(parent) = p.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
}

/// Cross-device fallback for `rename` (tmp .rendering and library can be on
/// different filesystems): copy then unlink, mirroring `shutil.move`.
fn move_file(src: &std::path::Path, dst: &std::path::Path) -> std::io::Result<()> {
    std::fs::copy(src, dst)?;
    std::fs::remove_file(src)
}

/// Resolve a human-readable mic DESCRIPTION (what Settings stores — the same
/// string Qt's `QAudioDevice::description()` and the webview's device label
/// show) to the pulse/pipewire source NAME that `pulsesrc device=` expects.
/// Mirrors the Python `record.mic_pulse_device`. Empty/no-match → "" (default
/// mic). Uses a gst DeviceMonitor so it works wherever the recorder works
/// (incl. the Flatpak sandbox — no pactl dependency).
pub fn resolve_mic_source(description: &str) -> String {
    use gst::prelude::*;
    if description.is_empty() {
        return String::new();
    }
    if gst::init().is_err() {
        return String::new();
    }
    let monitor = gst::DeviceMonitor::new();
    monitor.add_filter(Some("Audio/Source"), None);
    if monitor.start().is_err() {
        return String::new();
    }
    let devices = monitor.devices();
    monitor.stop();
    for d in devices {
        let name = d.display_name();
        if name == description || name.starts_with(description) || description.starts_with(name.as_str()) {
            // The provider-configured element carries the real source name in
            // its `device` property — more reliable than guessing prop keys.
            if let Some(elem) = d.create_element(None).ok() {
                let v = elem.property_value("device");
                if let Ok(Some(s)) = v.get::<Option<String>>() {
                    return s;
                }
                if let Ok(s) = v.get::<String>() {
                    return s;
                }
            }
        }
    }
    String::new()
}

/// Self-contained pipeline for the smoke test — needs no PipeWire/portal.
/// `videotestsrc num-buffers=30` EOSes on its own.
#[cfg(test)]
pub fn build_test_description(tmp: &str) -> String {
    format!(
        "videotestsrc num-buffers=30 ! videoconvert ! videorate ! \
         video/x-raw,format=I420,framerate=30/1 ! identity name=pause ! \
         x264enc speed-preset=veryfast tune=zerolatency key-int-max=120 ! \
         h264parse ! queue ! mux. mp4mux name=mux ! filesink location={tmp}"
    )
}

/// Like `build_test_description` but `is-live` with a configurable buffer
/// count, so a pause/resume test can use a source long enough to span the
/// paused window and emit buffers in real time (so `pause()` actually drops a
/// real span of frames rather than the whole burst arriving instantly).
#[cfg(test)]
pub fn build_test_description_n(tmp: &str, num_buffers: u32) -> String {
    format!(
        "videotestsrc num-buffers={num_buffers} is-live=true ! videoconvert ! videorate ! \
         video/x-raw,format=I420,framerate=30/1 ! identity name=pause ! \
         x264enc speed-preset=veryfast tune=zerolatency key-int-max=120 ! \
         h264parse ! queue ! mux. mp4mux name=mux ! filesink location={tmp}"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn videotestsrc_records_to_mp4_via_eos() {
        let dir = tempfile::tempdir().unwrap();
        let tmp = dir.path().join("t.mp4");
        let out = dir.path().join("out.mp4");
        let desc = build_test_description(tmp.to_str().unwrap());
        let done = std::sync::Arc::new(std::sync::Mutex::new(None));
        let d2 = done.clone();
        let rec = Recorder::launch(&desc, tmp.clone(), out.clone(), move |e| {
            if let RecEvent::Finished(p) = e {
                *d2.lock().unwrap() = Some(p);
            }
        })
        .expect("launch");
        // videotestsrc has num-buffers=30 so it EOSes on its own; call stop()
        // to exercise the finalize path regardless.
        std::thread::sleep(std::time::Duration::from_millis(800));
        rec.stop();
        assert!(out.exists(), "output mp4 should exist");
        assert!(std::fs::metadata(&out).unwrap().len() > 0);
        assert!(
            done.lock().unwrap().is_some(),
            "Finished event should have fired with the out path"
        );
    }

    #[test]
    fn supports_pause_is_true() {
        assert!(Recorder::supports_pause());
    }

    /// Runtime smoke test for the highest-risk, otherwise-unexercised path:
    /// the BUFFER pad probe that drops buffers while paused and rewrites
    /// PTS/DTS on resume. Drives a live videotestsrc through a full
    /// pause()->resume()->stop() cycle and asserts the pipeline survives the
    /// drop + PTS-rewrite and finalizes cleanly (EOS -> Finished, not Failed).
    #[test]
    fn pause_resume_rewrites_pts_and_finalizes() {
        let dir = tempfile::tempdir().unwrap();
        let tmp = dir.path().join("t.mp4");
        let out = dir.path().join("out.mp4");
        // 150 buffers @ 30fps live ~= 5s of source; plenty to have frames
        // before the pause, during the (dropped) pause, and after resume.
        let desc = build_test_description_n(tmp.to_str().unwrap(), 150);

        // Latch the terminal event so we can assert Finished, not Failed.
        let result: std::sync::Arc<std::sync::Mutex<Option<RecEvent>>> =
            std::sync::Arc::new(std::sync::Mutex::new(None));
        let r2 = result.clone();
        let rec = Recorder::launch(&desc, tmp.clone(), out.clone(), move |e| match e {
            RecEvent::Finished(_) | RecEvent::Failed(_) => {
                *r2.lock().unwrap() = Some(e);
            }
            _ => {}
        })
        .expect("launch");

        // Let some buffers flow, then pause (probe starts dropping), hold the
        // pause so a real span of frames is dropped, then resume (probe now
        // PTS-rewrites every buffer), let more flow, then stop().
        std::thread::sleep(std::time::Duration::from_millis(400));
        rec.pause();
        std::thread::sleep(std::time::Duration::from_millis(300));
        rec.resume();
        std::thread::sleep(std::time::Duration::from_millis(500));
        rec.stop();

        // The pipeline survived the drop + PTS-rewrite path and finalized.
        assert!(out.exists(), "output mp4 should exist after pause/resume");
        let len = std::fs::metadata(&out).unwrap().len();
        assert!(len > 0, "output mp4 should be non-empty (got {len} bytes)");

        // Terminal event must be a clean Finished, never Failed.
        let terminal = result.lock().unwrap().clone();
        match terminal {
            Some(RecEvent::Finished(p)) => {
                assert_eq!(p, out, "Finished should carry the out path");
            }
            other => panic!("expected Finished after pause/resume, got {other:?}"),
        }
    }
}
