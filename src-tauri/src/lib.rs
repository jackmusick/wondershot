mod ai;
mod commands;
mod graph;
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
/// Run it inside the Flatpak (`flatpak run io.github.jackmusick.wondershot
/// --media-check`) and every stage prints PASS/FAIL with the real error.
fn media_check() {
    use wondershot_core::record::recorder;
    use wondershot_core::settings::Settings;

    let s = Settings::load();
    println!("wondershot media check");
    println!("  settings camera_device: {:?}", s.camera_device);
    println!("  settings mic_device:    {:?}", s.mic_device);
    println!();

    // 1. Device enumeration — what the Settings dropdowns show.
    let devices = recorder::list_capture_devices();
    if devices.is_empty() {
        println!("[FAIL] device enumeration: no devices (gst DeviceMonitor returned nothing)");
    } else {
        println!("[PASS] device enumeration ({}):", devices.len());
        for (kind, label) in &devices {
            println!("         {kind:11} {label}");
        }
    }
    println!();

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
                println!("[PASS] camera: {frames} JPEG frames ({bytes} bytes total)");
            } else {
                println!("[FAIL] camera: pipeline started but produced no frames in 5s");
            }
        }
        Err(e) => println!("[FAIL] camera: {e}"),
    }
    println!();

    // 3. Mic resolution + open — what a recording will do.
    let source = recorder::resolve_mic_source(&s.mic_device);
    if s.mic_device.is_empty() {
        println!("[INFO] mic: no device selected (recordings use the default source)");
    } else if source.is_empty() {
        println!(
            "[FAIL] mic: could not resolve {:?} to a pulse/pipewire source",
            s.mic_device
        );
    } else {
        println!("[PASS] mic resolves: {:?} -> {source}", s.mic_device);
    }
    println!("       (speak into the mic now — sampling ~1s)");
    match recorder::mic_probe(&source) {
        Ok(peak) if peak >= 0.01 => {
            println!("[PASS] mic opens; peak level {:.0}% — audio is real", peak * 100.0)
        }
        Ok(peak) => println!(
            "[WARN] mic opens but is near-silent (peak {:.2}%) — wrong source selected, muted, or a monitor/loopback",
            peak * 100.0
        ),
        Err(e) => println!("[FAIL] mic open: {e}"),
    }
}

pub fn run() {
    // Headless-friendly actions short-circuit before building the GUI, matching
    // the Python CLI (`--version`, `--install-desktop` work without a window).
    let launch = parse_args(std::env::args().skip(1));
    match &launch {
        CliAction::Version => {
            println!("wondershot {}", env!("CARGO_PKG_VERSION"));
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
        .manage(commands::RecState::default())
        .manage(commands::AuthRouter::default())
        .manage(watcher::LibWatch::default())
        .manage(media_server::MediaServer(media_server::start()))
        .setup(move |app| {
            use tauri::{Listener, Manager};

            // Watch the library folders so externally created files (Spectacle
            // hotkey captures, drops from other apps) appear live — Qt parity.
            watcher::rewatch(app.handle(), app.state::<watcher::LibWatch>().inner());
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
                let menu = MenuBuilder::new(&tray_handle).item(&record_item).build()?;
                TrayIconBuilder::new()
                    .tooltip("Wondershot")
                    .menu(&menu)
                    .on_menu_event(|app, event| {
                        use tauri::Emitter;
                        if event.id() == "record-toggle" {
                            let _ = app.emit("tray://record-toggle", ());
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

            // Closing the main window must QUIT when there is no tray: the
            // hidden helper windows (bubble/countdown/capture) otherwise keep
            // the process alive as an unreachable ghost — and the
            // single-instance plugin then forwards every relaunch to a main
            // window that no longer exists ("app won't reopen", stray bwrap).
            // With a working tray, staying resident is the Python app's
            // close-to-tray behavior, so keep it.
            if !tray_ok {
                if let Some(main) = app.get_webview_window("main") {
                    let handle = app.handle().clone();
                    main.on_window_event(move |e| {
                        if matches!(e, tauri::WindowEvent::Destroyed) {
                            handle.exit(0);
                        }
                    });
                }
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
            commands::get_settings,
            commands::set_settings,
            commands::list_library,
            commands::load_sidecar,
            commands::save_sidecar,
            commands::copy_image,
            commands::capture_region,
            commands::capture_fullscreen,
            commands::capture_window,
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
            commands::start_recording,
            commands::stop_recording,
            commands::pause_recording,
            commands::resume_recording,
            commands::video_thumb,
            commands::graph_connect_interactive,
            commands::list_media_devices,
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
