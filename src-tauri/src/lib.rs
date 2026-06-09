mod commands;

use tauri::tray::TrayIconBuilder;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            use tauri::Manager;
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .setup(|app| {
            TrayIconBuilder::new()
                .tooltip("Wondershot")
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running wondershot");
}
