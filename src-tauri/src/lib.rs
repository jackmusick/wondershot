mod ai;
mod commands;
mod graph;
mod hotkeys;
mod logging;
mod media_server;
mod share;
mod watcher;

use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use wondershot_core::cli::{parse_args, CliAction};

/// Map a parsed CLI action to an app effect. Used both for the launch process
/// args (deferred until the webview signals `app://ready`) and for the args a
/// second invocation forwards via single-instance — so a global shortcut bound
/// to `wondershot --capture` triggers a capture in the running instance.
fn dispatch_cli(app: &tauri::AppHandle, action: CliAction) {
    use tauri::{Emitter, Manager};
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    match action {
        CliAction::Capture => {
            let _ = app.emit("cli://capture", ());
        }
        CliAction::Fullscreen => {
            let _ = app.emit("cli://fullscreen", ());
        }
        CliAction::Edit(p) => {
            let _ = app.emit("cli://edit", p);
        }
        CliAction::Import(fs) => {
            let _ = app.emit("cli://import", fs);
        }
        CliAction::Quit => app.exit(0),
        CliAction::InstallDesktop => {
            let _ = commands::install_desktop();
        }
        // OAuth callback deep link (wondershot://auth?code=…): hand it to the
        // awaiting interactive sign-in. Other URLs just focus (above).
        CliAction::OpenUrl(url) if url.starts_with("wondershot://auth") => {
            app.state::<commands::AuthRouter>().deliver(url);
        }
        // Version/MediaCheck are handled before the GUI starts; URL/Launch just focus.
        CliAction::Version | CliAction::MediaCheck | CliAction::OpenUrl(_) | CliAction::Launch => {}
    }
}

/// `wondershot --media-check` — deterministic, GUI-free verification of the
/// exact code paths the camera bubble, Settings dropdowns, and recorder use.
/// Run it from the installed app (`wondershot --media-check`) and every stage
/// prints PASS/FAIL with the real error.
fn media_check() {
    use wondershot_core::record::recorder;
    use wondershot_core::settings::Settings;

    macro_rules! line {
        ($out:expr) => {
            $out.push('\n')
        };
        ($out:expr, $($arg:tt)*) => {{
            use std::fmt::Write as _;
            let _ = writeln!($out, $($arg)*);
        }};
    }

    let mut out = String::new();
    let s = Settings::load();
    line!(out, "wondershot media check");
    line!(out, "  settings camera_device: {:?}", s.camera_device);
    line!(out, "  settings mic_device:    {:?}", s.mic_device);
    line!(out);

    // 1. Device enumeration — what the Settings dropdowns show.
    let devices = recorder::list_capture_devices();
    if devices.is_empty() {
        #[cfg(target_os = "windows")]
        line!(out, "[FAIL] device enumeration: no DirectShow devices reported by FFmpeg");
        #[cfg(not(target_os = "windows"))]
        line!(out, "[FAIL] device enumeration: no devices (gst DeviceMonitor returned nothing)");
    } else {
        line!(out, "[PASS] device enumeration ({}):", devices.len());
        for (kind, label) in &devices {
            line!(out, "         {kind:11} {label}");
        }
    }
    line!(out);

    #[cfg(target_os = "windows")]
    {
        match wondershot_core::capture::native::capture_rgba() {
            Ok(img) => {
                let (w, h) = img.dimensions();
                let mut samples = Vec::new();
                let points = [
                    (0, 0),
                    (w / 2, h / 2),
                    (w.saturating_sub(1), h.saturating_sub(1)),
                    (w / 3, h / 3),
                    ((2 * w) / 3, (2 * h) / 3),
                ];
                for (x, y) in points {
                    let p = img.get_pixel(x, y);
                    samples.push([p[0], p[1], p[2], p[3]]);
                }
                let nonblank = samples.iter().any(|p| p[0] != 0 || p[1] != 0 || p[2] != 0);
                if nonblank {
                    line!(out, "[PASS] native screenshot: {w}x{h}, sampled nonblank pixels");
                } else {
                    line!(out, "[FAIL] native screenshot: {w}x{h}, sampled pixels are all black");
                }
            }
            Err(e) => line!(out, "[FAIL] native screenshot: {e}"),
        }
        line!(out);

        let windows = wondershot_core::capture::native::window_rects();
        if windows.is_empty() {
            line!(out, "[FAIL] native window picker: no selectable top-level windows found");
        } else {
            line!(out, "[PASS] native window picker ({} selectable):", windows.len());
            for window in windows.iter().take(5) {
                line!(
                    out,
                    "         {}x{} at {},{} — {}",
                    window.width,
                    window.height,
                    window.x,
                    window.y,
                    window.title
                );
            }
        }
        line!(out);
    }

    #[cfg(target_os = "windows")]
    {
        let dir = std::env::temp_dir().join("wondershot-media-check");
        let tmp = dir.join("screen-recording.rendering.mp4");
        let final_out = dir.join("screen-recording.mp4");
        let _ = std::fs::remove_file(&tmp);
        let _ = std::fs::remove_file(&final_out);
        let desc = recorder::build_recording_args(&tmp, Some((0, 0, 640, 360)), false, false, "")
            .join("\n");
        match recorder::Recorder::launch(&desc, tmp.clone(), final_out.clone(), |_| {}) {
            Ok(rec) => {
                std::thread::sleep(std::time::Duration::from_millis(700));
                rec.pause();
                std::thread::sleep(std::time::Duration::from_millis(600));
                rec.resume();
                std::thread::sleep(std::time::Duration::from_millis(900));
                rec.stop();
                match std::fs::metadata(&final_out).map(|m| m.len()) {
                    Ok(size) if size > 4 * 1024 => {
                        line!(out, "[PASS] recording smoke + pause/resume: wrote {} bytes", size);
                    }
                    Ok(size) => {
                        line!(out, "[FAIL] recording smoke + pause/resume: output too small ({} bytes)", size);
                    }
                    Err(e) => {
                        line!(out, "[FAIL] recording smoke + pause/resume: no output file ({e})");
                    }
                }
            }
            Err(e) => line!(out, "[FAIL] recording smoke + pause/resume: {e}"),
        }
        let _ = std::fs::remove_file(&tmp);
        let _ = std::fs::remove_file(&final_out);
        line!(out);
    }

    // 2. Camera open + frames — exactly what the bubble streams.
    match wondershot_core::camera::open(&s.camera_device) {
        Ok(stream) => {
            let mut frames = 0;
            let mut bytes = 0usize;
            for _ in 0..5 {
                match stream.next_jpeg() {
                    Some(j) => {
                        frames += 1;
                        bytes += j.len();
                    }
                    None => break,
                }
            }
            if frames > 0 {
                line!(out, "[PASS] camera: {frames} JPEG frames ({bytes} bytes total)");
            } else {
                line!(out, "[FAIL] camera: pipeline started but produced no frames in 5s");
            }
        }
        Err(e) => line!(out, "[FAIL] camera: {e}"),
    }
    line!(out);

    // 3. Mic resolution + open — what a recording will do.
    #[cfg(target_os = "windows")]
    {
        if s.mic_device.is_empty() {
            let default_mic = devices
                .iter()
                .find_map(|(kind, label)| (kind == "audioinput").then_some(label.as_str()));
            if s.mic_enabled {
                match default_mic {
                    Some(label) => line!(out, "[PASS] mic default resolves: {label}"),
                    None => line!(out, "[FAIL] mic default: no DirectShow audio device reported"),
                }
            } else {
                line!(out, "[INFO] mic: disabled in settings");
            }
        } else if devices.iter().any(|(kind, label)| kind == "audioinput" && label == &s.mic_device) {
            line!(out, "[PASS] mic resolves: {:?}", s.mic_device);
        } else {
            let fallback_mic = devices
                .iter()
                .find_map(|(kind, label)| (kind == "audioinput").then_some(label.as_str()));
            match fallback_mic {
                Some(label) => line!(
                    out,
                    "[WARN] mic: selected device {:?} was not reported by DirectShow; recordings will use {label:?}",
                    s.mic_device
                ),
                None => line!(out, "[FAIL] mic: selected device {:?} was not reported and no fallback audio device is available", s.mic_device),
            }
        }
        line!(out, "[INFO] noise suppression: not available in the Windows FFmpeg backend yet");
    }
    #[cfg(not(target_os = "windows"))]
    {
    let source = recorder::resolve_mic_source(&s.mic_device);
    if s.mic_device.is_empty() {
        line!(out, "[INFO] mic: no device selected (recordings use the default source)");
    } else if source.is_empty() {
        line!(
            out,
            "[FAIL] mic: could not resolve {:?} to a pulse/pipewire source",
            s.mic_device
        );
    } else {
        line!(out, "[PASS] mic resolves: {:?} -> {source}", s.mic_device);
    }
    if recorder::have_gst_element("webrtcdsp") {
        line!(out, "[PASS] noise suppression (webrtcdsp) available");
    } else {
        line!(out, "[WARN] webrtcdsp missing — recordings get raw mic audio (no noise suppression)");
    }
    line!(out, "       (speak into the mic now — sampling ~1s)");
    match recorder::mic_probe(&source) {
        Ok(peak) if peak >= 0.01 => {
            line!(out, "[PASS] mic opens; peak level {:.0}% — audio is real", peak * 100.0)
        }
        Ok(peak) => line!(
            out,
            "[WARN] mic opens but is near-silent (peak {:.2}%) — wrong source selected, muted, or a monitor/loopback",
            peak * 100.0
        ),
        Err(e) => line!(out, "[FAIL] mic open: {e}"),
    }
    }
    let _ = std::io::Write::write_all(&mut std::io::stdout(), out.as_bytes());
    #[cfg(target_os = "windows")]
    {
        let _ = std::fs::write(std::env::temp_dir().join("wondershot-media-check.txt"), &out);
    }
}

pub fn run() {
    logging::init();
    // Headless-friendly actions short-circuit before building the GUI, matching
    // the Python CLI (`--version`, `--install-desktop` work without a window).
    let launch = parse_args(std::env::args().skip(1));
    match &launch {
        CliAction::Version => {
            let _ = std::io::Write::write_all(
                &mut std::io::stdout(),
                format!("wondershot {}\n", env!("CARGO_PKG_VERSION")).as_bytes(),
            );
            return;
        }
        CliAction::InstallDesktop => {
            if let Err(e) = commands::install_desktop() {
                eprintln!("install-desktop failed: {e}");
            }
            return;
        }
        CliAction::MediaCheck => {
            media_check();
            return;
        }
        _ => {}
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            // argv includes argv0 here; parse_args expects it stripped.
            dispatch_cli(app, parse_args(argv.into_iter().skip(1)));
        }))
        .plugin(tauri_plugin_drag::init())
        .manage(hotkeys::HotkeyState::default())
        .manage(commands::RecState::default())
        .manage(commands::AuthRouter::default())
        .manage(watcher::LibWatch::default())
        .manage(media_server::MediaServer(media_server::start()))
        .setup(move |app| {
            use tauri::{Listener, Manager};

            // Watch the library folders so externally created files (global
            // hotkey captures, drops from other apps) appear live.
            watcher::rewatch(app.handle(), app.state::<watcher::LibWatch>().inner());
            hotkeys::start(
                app.handle().clone(),
                app.state::<hotkeys::HotkeyState>().inner(),
            );
            // Tray "Record / Stop" item. Tray menu -> command wiring is awkward
            // (the menu handler has no access to the recorder's async start
            // path), so the item emits a `tray://record-toggle` event the
            // frontend listens for and dispatches the start/stop command.
            //
            // libappindicator-sys panics (not Result-errors) if neither
            // libayatana-appindicator3 nor libappindicator3 is present at
            // runtime — e.g. a GNOME-runtime Flatpak that doesn't bundle it. A
            // missing tray must not take the whole app down, so build it inside
            // catch_unwind and degrade to "no tray" on failure.
            let tray_handle = app.handle().clone();
            let tray = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let record_item =
                    MenuItemBuilder::with_id("record-toggle", "Record / Stop").build(&tray_handle)?;
                let show_item =
                    MenuItemBuilder::with_id("show", "Open Wondershot").build(&tray_handle)?;
                let quit_item =
                    MenuItemBuilder::with_id("quit", "Quit Wondershot").build(&tray_handle)?;
                let menu = MenuBuilder::new(&tray_handle)
                    .item(&record_item)
                    .separator()
                    .item(&show_item)
                    .item(&quit_item)
                    .build()?;
                let mut builder = TrayIconBuilder::new().tooltip("Wondershot").menu(&menu);
                // An explicit icon is required — without one the item registers
                // but renders blank ("the icon is there but invisible").
                if let Some(icon) = tray_handle.default_window_icon().cloned() {
                    builder = builder.icon(icon);
                }
                // Flatpak: tray-icon writes the icon PNG to a temp dir and tells
                // the SNI host (plasmashell) to load it from that path. The
                // default $TEMP is inside the sandbox, which the host can't read
                // → a blank icon. Redirect it to the app cache dir, which lives
                // under the real $HOME (host-readable via --filesystem=home).
                if let Ok(cache) = tray_handle.path().app_cache_dir() {
                    let dir = cache.join("tray-icon");
                    let _ = std::fs::create_dir_all(&dir);
                    builder = builder.temp_dir_path(dir);
                }
                builder
                    .on_menu_event(|app, event| {
                        use tauri::{Emitter, Manager};
                        match event.id().as_ref() {
                            "record-toggle" => {
                                let _ = app.emit("tray://record-toggle", ());
                            }
                            "show" => {
                                if let Some(w) = app.get_webview_window("main") {
                                    let _ = w.show();
                                    let _ = w.unminimize();
                                    let _ = w.set_focus();
                                }
                            }
                            // Hard-exit to skip the crash-prone GTK/WebKit
                            // teardown that SIGABRTs on a normal app.exit().
                            "quit" => std::process::exit(0),
                            _ => {}
                        }
                    })
                    // Left-click the tray icon → bring the main window back, so a
                    // closed-to-tray app is always recoverable without the menu.
                    .on_tray_icon_event(|tray, event| {
                        use tauri::tray::{MouseButton, TrayIconEvent};
                        use tauri::Manager;
                        if let TrayIconEvent::Click { button: MouseButton::Left, .. } = event {
                            if let Some(w) = tray.app_handle().get_webview_window("main") {
                                let _ = w.show();
                                let _ = w.unminimize();
                                let _ = w.set_focus();
                            }
                        }
                    })
                    .build(&tray_handle)?;
                Ok::<(), tauri::Error>(())
            }));
            let tray_ok = matches!(tray, Ok(Ok(())));
            match tray {
                Ok(Ok(())) => {}
                Ok(Err(e)) => eprintln!("tray icon unavailable: {e}"),
                Err(_) => eprintln!(
                    "tray icon unavailable: no appindicator library at runtime — continuing without a tray"
                ),
            }

            // Window-close behaviour:
            //  - With a tray: HIDE to tray (Python close-to-tray parity) — do
            //    NOT let the window be destroyed. Destroying it makes the tray
            //    "Open"/click unable to bring it back (the handle is gone) AND
            //    routinely aborts WebKit's web process during teardown — that's
            //    the "crash on close" notification. Hiding keeps the live
            //    window so relaunch/tray just re-shows it.
            //  - Without a tray: there's nowhere to reopen from, so quit. Use
            //    std::process::exit to terminate immediately and skip Tauri's
            //    crash-prone async GTK/WebKit teardown (the SIGABRT on exit);
            //    the OS reclaims the camera/PipeWire/portal resources cleanly.
            if let Some(main) = app.get_webview_window("main") {
                let win = main.clone();
                main.on_window_event(move |e| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = e {
                        if tray_ok {
                            api.prevent_close();
                            let _ = win.hide();
                        } else {
                            std::process::exit(0);
                        }
                    }
                });
            }

            // Act on the launch args once the webview's cli:// listeners are
            // attached (it emits app://ready), so the event isn't dropped.
            if launch != CliAction::Launch {
                let handle = app.handle().clone();
                let launch = launch.clone();
                app.listen_any("app://ready", move |_| {
                    dispatch_cli(&handle, launch.clone());
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::health,
            commands::debug_log,
            commands::log_path,
            commands::platform,
            commands::get_settings,
            commands::set_settings,
            commands::list_library,
            commands::load_sidecar,
            commands::save_sidecar,
            commands::copy_image,
            commands::capture_region,
            commands::capture_fullscreen,
            commands::capture_window,
            commands::native_capture_capabilities,
            commands::native_capture_frame_b64,
            commands::save_native_capture_crop,
            commands::pixelate_patch,
            commands::blur_patch,
            commands::crop_base,
            commands::cutout_base,
            commands::bg_model_available,
            commands::bg_model_download,
            commands::remove_background,
            commands::ai_redact,
            commands::ai_simplify,
            commands::flatten_save,
            commands::write_base,
            commands::read_base,
            commands::read_image_b64,
            commands::save_recording_b64,
            commands::start_recording,
            commands::stop_recording,
            commands::pause_recording,
            commands::resume_recording,
            commands::video_thumb,
            commands::graph_connect_interactive,
            commands::list_media_devices,
            commands::recorder_capabilities,
            commands::capture_command,
            commands::share_capture,
            media_server::media_server_port,
            commands::grab_frame,
            commands::apply_blur,
            commands::export_gif,
            commands::trim_video,
            commands::install_desktop,
            commands::import_files,
            commands::toggle_camera_bubble,
            commands::set_camera_bubble,
            commands::trash_item,
            commands::list_pinned,
            commands::set_pinned,
            commands::save_image_as,
            commands::show_in_folder,
            commands::pick_folder,
            commands::open_shortcut_settings,
            commands::test_ai_endpoint,
            commands::show_capture_window,
            commands::open_url,
            commands::graph_status,
            commands::graph_connect_start,
            commands::graph_connect_poll,
            commands::graph_disconnect,
            commands::graph_sites_search,
            commands::graph_site_drives,
        ])
        .run(tauri::generate_context!())
        .expect("error while running wondershot");
}
