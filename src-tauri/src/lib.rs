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
        .invoke_handler(tauri::generate_handler![commands::health])
        .run(tauri::generate_context!())
        .expect("error while running wondershot");
}
