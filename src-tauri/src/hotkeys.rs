use std::sync::Mutex;

#[derive(Default)]
pub struct HotkeyState {
    #[cfg(target_os = "windows")]
    sender: Mutex<Option<std::sync::mpsc::Sender<String>>>,
}

pub fn start(app: tauri::AppHandle, state: &HotkeyState) {
    #[cfg(target_os = "windows")]
    {
        use tauri::Emitter;

        let (tx, rx) = std::sync::mpsc::channel::<String>();
        if let Ok(mut slot) = state.sender.lock() {
            *slot = Some(tx);
        }

        let initial = wondershot_core::settings::Settings::load().hotkey_capture;
        let app_for_thread = app.clone();
        std::thread::Builder::new()
            .name("wondershot-hotkey".into())
            .spawn(move || windows_hotkey_loop(app_for_thread, rx, initial))
            .map_err(|e| crate::logging::log(format!("hotkey: could not start thread: {e}")))
            .ok();

        let _ = app.emit("hotkey://ready", ());
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = (app, state);
    }
}

pub fn update_from_settings(app: &tauri::AppHandle) {
    #[cfg(target_os = "windows")]
    {
        use tauri::Manager;

        let hotkey = wondershot_core::settings::Settings::load().hotkey_capture;
        match app.state::<HotkeyState>().sender.lock() {
            Ok(slot) => {
                if let Some(tx) = slot.as_ref() {
                    if tx.send(hotkey).is_err() {
                        crate::logging::log("hotkey: update failed; thread is not running");
                    }
                }
            }
            Err(e) => crate::logging::log(format!("hotkey: update lock failed: {e}")),
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = app;
    }
}

#[cfg(target_os = "windows")]
fn windows_hotkey_loop(
    app: tauri::AppHandle,
    rx: std::sync::mpsc::Receiver<String>,
    initial: String,
) {
    use tauri::Emitter;
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::UnregisterHotKey;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        DispatchMessageW, PeekMessageW, TranslateMessage, MSG, PM_REMOVE, WM_HOTKEY,
    };

    const HOTKEY_ID: i32 = 0x5753; // "WS"
    let mut registered = false;
    register_hotkey(&initial, HOTKEY_ID, &mut registered);

    loop {
        match rx.recv_timeout(std::time::Duration::from_millis(80)) {
            Ok(next) => register_hotkey(&next, HOTKEY_ID, &mut registered),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }

        unsafe {
            let mut msg: MSG = std::mem::zeroed();
            while PeekMessageW(&mut msg, std::ptr::null_mut(), 0, 0, PM_REMOVE) != 0 {
                if msg.message == WM_HOTKEY && msg.wParam == HOTKEY_ID as usize {
                    crate::logging::log("hotkey: capture triggered");
                    let _ = app.emit("cli://capture", ());
                } else {
                    TranslateMessage(&msg);
                    DispatchMessageW(&msg);
                }
            }
        }
    }

    if registered {
        unsafe {
            UnregisterHotKey(std::ptr::null_mut(), HOTKEY_ID);
        }
    }
}

#[cfg(target_os = "windows")]
fn register_hotkey(value: &str, id: i32, registered: &mut bool) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        RegisterHotKey, UnregisterHotKey, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN,
        VK_SNAPSHOT,
    };

    if *registered {
        unsafe {
            UnregisterHotKey(std::ptr::null_mut(), id);
        }
        *registered = false;
    }

    let Some((mods, key)) = parse_hotkey(value) else {
        crate::logging::log(format!("hotkey: invalid shortcut {value:?}"));
        return;
    };

    let ok = unsafe { RegisterHotKey(std::ptr::null_mut(), id, mods | MOD_NOREPEAT, key) } != 0;
    if ok {
        *registered = true;
        crate::logging::log(format!("hotkey: registered {value}"));
    } else {
        crate::logging::log(format!("hotkey: registration failed for {value}"));
    }

    fn parse_hotkey(value: &str) -> Option<(u32, u32)> {
        let mut mods = 0u32;
        let mut key = None;
        for raw in value.split('+') {
            let part = raw.trim().to_ascii_lowercase();
            match part.as_str() {
                "ctrl" | "control" => mods |= MOD_CONTROL,
                "shift" => mods |= MOD_SHIFT,
                "alt" | "option" => mods |= MOD_ALT,
                "win" | "windows" | "meta" | "super" | "cmd" | "command" => mods |= MOD_WIN,
                "print" | "prtsc" | "prtscr" | "printscreen" => key = Some(VK_SNAPSHOT as u32),
                s if s.len() == 1 => {
                    let ch = s.as_bytes()[0];
                    if ch.is_ascii_alphanumeric() {
                        key = Some(ch.to_ascii_uppercase() as u32);
                    }
                }
                s if s.starts_with('f') => {
                    if let Ok(n) = s[1..].parse::<u32>() {
                        if (1..=24).contains(&n) {
                            key = Some(0x70 + n - 1);
                        }
                    }
                }
                _ => {}
            }
        }
        key.map(|k| (mods, k))
    }
}
