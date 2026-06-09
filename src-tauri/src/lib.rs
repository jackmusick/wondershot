mod commands;

use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            use tauri::Manager;
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .manage(commands::RecState::default())
        .setup(|app| {
            // Tray "Record / Stop" item. Tray menu -> command wiring is awkward
            // (the menu handler has no access to the recorder's async start
            // path), so the item emits a `tray://record-toggle` event the
            // frontend listens for and dispatches the start/stop command.
            let record_item = MenuItemBuilder::with_id("record-toggle", "Record / Stop")
                .build(app)?;
            let menu = MenuBuilder::new(app).item(&record_item).build()?;
            TrayIconBuilder::new()
                .tooltip("Wondershot")
                .menu(&menu)
                .on_menu_event(|app, event| {
                    use tauri::Emitter;
                    if event.id() == "record-toggle" {
                        let _ = app.emit("tray://record-toggle", ());
                    }
                })
                .build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::health,
            commands::get_settings,
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
            commands::flatten_save,
            commands::write_base,
            commands::read_base,
            commands::start_recording,
            commands::stop_recording,
            commands::pause_recording,
            commands::resume_recording,
        ])
        .run(tauri::generate_context!())
        .expect("error while running wondershot");
}
