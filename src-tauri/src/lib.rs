mod commands;
mod graph;
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
        // Version is handled before the GUI starts; URL/Launch just focus.
        CliAction::Version | CliAction::OpenUrl(_) | CliAction::Launch => {}
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
        _ => {}
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            // argv includes argv0 here; parse_args expects it stripped.
            dispatch_cli(app, parse_args(argv.into_iter().skip(1)));
        }))
        .plugin(tauri_plugin_drag::init())
        .manage(commands::RecState::default())
        .manage(watcher::LibWatch::default())
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
            match tray {
                Ok(Ok(())) => {}
                Ok(Err(e)) => eprintln!("tray icon unavailable: {e}"),
                Err(_) => eprintln!(
                    "tray icon unavailable: no appindicator library at runtime — continuing without a tray"
                ),
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
            commands::remove_background,
            commands::flatten_save,
            commands::write_base,
            commands::read_base,
            commands::read_image_b64,
            commands::start_recording,
            commands::stop_recording,
            commands::pause_recording,
            commands::resume_recording,
            commands::grab_frame,
            commands::apply_blur,
            commands::export_gif,
            commands::trim_video,
            commands::install_desktop,
            commands::import_files,
            commands::toggle_camera_bubble,
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
