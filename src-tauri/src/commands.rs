#[tauri::command]
pub fn health() -> String {
    "ok".to_string()
}
