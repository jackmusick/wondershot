#[cfg(any(target_os = "windows", target_os = "macos"))]
use std::sync::Mutex;

#[derive(Default)]
pub struct HotkeyState {
    #[cfg(target_os = "windows")]
    sender: Mutex<Option<std::sync::mpsc::Sender<String>>>,
    #[cfg(target_os = "macos")]
    macos: Mutex<MacHotkeyState>,
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

    #[cfg(target_os = "macos")]
    {
        use tauri::Emitter;

        set_macos_app_handle(app.clone());
        let initial = wondershot_core::settings::Settings::load().hotkey_capture;
        match state.macos.lock() {
            Ok(mut state) => {
                if let Err(e) = state.ensure_handler() {
                    crate::logging::log(format!("hotkey: macOS handler install failed: {e}"));
                } else {
                    register_macos_hotkey(&initial, &mut state);
                }
            }
            Err(e) => crate::logging::log(format!("hotkey: macOS state lock failed: {e}")),
        }
        let _ = app.emit("hotkey://ready", ());
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
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

    #[cfg(target_os = "macos")]
    {
        use tauri::Manager;

        let hotkey = wondershot_core::settings::Settings::load().hotkey_capture;
        match app.state::<HotkeyState>().macos.lock() {
            Ok(mut state) => register_macos_hotkey(&hotkey, &mut state),
            Err(e) => crate::logging::log(format!("hotkey: macOS update lock failed: {e}")),
        }
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = app;
    }
}

#[cfg(target_os = "macos")]
#[derive(Default)]
struct MacHotkeyState {
    hotkey_ref: usize,
    handler_ref: usize,
}

#[cfg(target_os = "macos")]
impl MacHotkeyState {
    fn ensure_handler(&mut self) -> Result<(), String> {
        if self.handler_ref != 0 {
            return Ok(());
        }

        let spec = EventTypeSpec {
            eventClass: K_EVENT_CLASS_KEYBOARD,
            eventKind: K_EVENT_HOT_KEY_PRESSED,
        };
        let mut handler = std::ptr::null_mut();
        let status = unsafe {
            InstallEventHandler(
                GetApplicationEventTarget(),
                Some(macos_hotkey_handler),
                1,
                &spec,
                std::ptr::null_mut(),
                &mut handler,
            )
        };
        if status != 0 {
            return Err(format!("InstallApplicationEventHandler returned {status}"));
        }
        self.handler_ref = handler as usize;
        Ok(())
    }
}

#[cfg(target_os = "macos")]
fn register_macos_hotkey(value: &str, state: &mut MacHotkeyState) {
    if state.hotkey_ref != 0 {
        unsafe {
            UnregisterEventHotKey(state.hotkey_ref as EventHotKeyRef);
        }
        state.hotkey_ref = 0;
    }

    let Some((mods, key)) = parse_macos_hotkey(value) else {
        crate::logging::log(format!("hotkey: invalid macOS shortcut {value:?}"));
        return;
    };

    let id = EventHotKeyID {
        signature: fourcc(*b"WOSH"),
        id: 1,
    };
    let mut hotkey = std::ptr::null_mut();
    let status =
        unsafe { RegisterEventHotKey(key, mods, id, GetApplicationEventTarget(), 0, &mut hotkey) };
    if status == 0 {
        state.hotkey_ref = hotkey as usize;
        crate::logging::log(format!("hotkey: registered macOS {value}"));
    } else {
        crate::logging::log(format!(
            "hotkey: macOS registration failed for {value} ({status})"
        ));
    }
}

#[cfg(target_os = "macos")]
fn set_macos_app_handle(app: tauri::AppHandle) {
    match MACOS_APP_HANDLE.get_or_init(|| Mutex::new(None)).lock() {
        Ok(mut slot) => *slot = Some(app),
        Err(e) => crate::logging::log(format!("hotkey: macOS app handle lock failed: {e}")),
    }
}

#[cfg(target_os = "macos")]
unsafe extern "C" fn macos_hotkey_handler(
    _next: EventHandlerCallRef,
    event: EventRef,
    _user_data: *mut std::ffi::c_void,
) -> OSStatus {
    if GetEventClass(event) == K_EVENT_CLASS_KEYBOARD
        && GetEventKind(event) == K_EVENT_HOT_KEY_PRESSED
    {
        use tauri::Emitter;

        if let Some(lock) = MACOS_APP_HANDLE.get() {
            if let Ok(slot) = lock.lock() {
                if let Some(app) = slot.as_ref() {
                    crate::logging::log("hotkey: macOS capture triggered");
                    let _ = app.emit("cli://capture", ());
                }
            }
        }
    }
    0
}

#[cfg(target_os = "macos")]
fn parse_macos_hotkey(value: &str) -> Option<(u32, u32)> {
    let mut mods = 0u32;
    let mut key = None;
    for raw in value.split('+') {
        let part = raw.trim().to_ascii_lowercase();
        match part.as_str() {
            "cmd" | "command" | "meta" | "super" | "win" | "windows" => mods |= CMD_KEY,
            "shift" => mods |= SHIFT_KEY,
            "alt" | "option" => mods |= OPTION_KEY,
            "ctrl" | "control" => mods |= CONTROL_KEY,
            "print" | "prtsc" | "prtscr" | "printscreen" => {}
            s if s.len() == 1 => {
                let ch = s.as_bytes()[0];
                if ch.is_ascii_alphanumeric() {
                    key = macos_key_code(ch.to_ascii_uppercase() as char);
                }
            }
            s if s.starts_with('f') => {
                if let Ok(n) = s[1..].parse::<u32>() {
                    key = macos_function_key_code(n);
                }
            }
            _ => {}
        }
    }
    if mods == 0 {
        return None;
    }
    key.map(|k| (mods, k))
}

#[cfg(target_os = "macos")]
fn macos_key_code(ch: char) -> Option<u32> {
    Some(match ch {
        'A' => 0x00,
        'S' => 0x01,
        'D' => 0x02,
        'F' => 0x03,
        'H' => 0x04,
        'G' => 0x05,
        'Z' => 0x06,
        'X' => 0x07,
        'C' => 0x08,
        'V' => 0x09,
        'B' => 0x0B,
        'Q' => 0x0C,
        'W' => 0x0D,
        'E' => 0x0E,
        'R' => 0x0F,
        'Y' => 0x10,
        'T' => 0x11,
        '1' => 0x12,
        '2' => 0x13,
        '3' => 0x14,
        '4' => 0x15,
        '6' => 0x16,
        '5' => 0x17,
        '9' => 0x19,
        '7' => 0x1A,
        '8' => 0x1C,
        '0' => 0x1D,
        'O' => 0x1F,
        'U' => 0x20,
        'I' => 0x22,
        'P' => 0x23,
        'L' => 0x25,
        'J' => 0x26,
        'K' => 0x28,
        'N' => 0x2D,
        'M' => 0x2E,
        _ => return None,
    })
}

#[cfg(target_os = "macos")]
fn macos_function_key_code(n: u32) -> Option<u32> {
    Some(match n {
        1 => 0x7A,
        2 => 0x78,
        3 => 0x63,
        4 => 0x76,
        5 => 0x60,
        6 => 0x61,
        7 => 0x62,
        8 => 0x64,
        9 => 0x65,
        10 => 0x6D,
        11 => 0x67,
        12 => 0x6F,
        _ => return None,
    })
}

#[cfg(target_os = "macos")]
const fn fourcc(bytes: [u8; 4]) -> u32 {
    u32::from_be_bytes(bytes)
}

#[cfg(target_os = "macos")]
static MACOS_APP_HANDLE: std::sync::OnceLock<Mutex<Option<tauri::AppHandle>>> =
    std::sync::OnceLock::new();

#[cfg(target_os = "macos")]
const CMD_KEY: u32 = 1 << 8;
#[cfg(target_os = "macos")]
const SHIFT_KEY: u32 = 1 << 9;
#[cfg(target_os = "macos")]
const OPTION_KEY: u32 = 1 << 11;
#[cfg(target_os = "macos")]
const CONTROL_KEY: u32 = 1 << 12;
#[cfg(target_os = "macos")]
const K_EVENT_CLASS_KEYBOARD: u32 = fourcc(*b"keyb");
#[cfg(target_os = "macos")]
const K_EVENT_HOT_KEY_PRESSED: u32 = 5;

#[cfg(target_os = "macos")]
type OSStatus = i32;
#[cfg(target_os = "macos")]
type EventHandlerCallRef = *mut std::ffi::c_void;
#[cfg(target_os = "macos")]
type EventRef = *mut std::ffi::c_void;
#[cfg(target_os = "macos")]
type EventTargetRef = *mut std::ffi::c_void;
#[cfg(target_os = "macos")]
type EventHandlerRef = *mut std::ffi::c_void;
#[cfg(target_os = "macos")]
type EventHotKeyRef = *mut std::ffi::c_void;

#[cfg(target_os = "macos")]
#[repr(C)]
#[allow(non_snake_case)]
struct EventHotKeyID {
    signature: u32,
    id: u32,
}

#[cfg(target_os = "macos")]
#[repr(C)]
#[allow(non_snake_case)]
struct EventTypeSpec {
    eventClass: u32,
    eventKind: u32,
}

#[cfg(target_os = "macos")]
#[link(name = "Carbon", kind = "framework")]
unsafe extern "C" {
    fn GetApplicationEventTarget() -> EventTargetRef;
    fn InstallEventHandler(
        target: EventTargetRef,
        handler: Option<
            unsafe extern "C" fn(EventHandlerCallRef, EventRef, *mut std::ffi::c_void) -> OSStatus,
        >,
        num_types: u32,
        type_list: *const EventTypeSpec,
        user_data: *mut std::ffi::c_void,
        out_handler: *mut EventHandlerRef,
    ) -> OSStatus;
    fn RegisterEventHotKey(
        hot_key_code: u32,
        hot_key_modifiers: u32,
        hot_key_id: EventHotKeyID,
        target: EventTargetRef,
        options: u32,
        out_ref: *mut EventHotKeyRef,
    ) -> OSStatus;
    fn UnregisterEventHotKey(hot_key: EventHotKeyRef) -> OSStatus;
    fn GetEventClass(event: EventRef) -> u32;
    fn GetEventKind(event: EventRef) -> u32;
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
