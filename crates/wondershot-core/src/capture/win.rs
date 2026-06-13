use std::path::Path;
use std::sync::{Arc, Mutex};

use image::{ImageBuffer, Rgba, RgbaImage};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, CreateSolidBrush, DeleteDC,
    DeleteObject, EndPaint, EnumDisplayMonitors, FillRect, FrameRect, GetDC, GetDIBits,
    GetMonitorInfoW, InvalidateRect, PAINTSTRUCT, ReleaseDC, SelectObject, SetBkMode,
    SetTextColor, TextOutW, UpdateWindow,
    BITMAPINFO, BITMAPINFOHEADER, BI_RGB, DIB_RGB_COLORS, HBITMAP, HDC, HGDIOBJ, HMONITOR,
    MONITORINFO, CAPTUREBLT, SRCCOPY,
};
use windows_sys::Win32::Storage::Xps::PrintWindow;
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture, SetFocus};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, DrawIconEx, EnumWindows,
    GetAncestor, GetCursorInfo, GetIconInfo, GetMessageW, GetShellWindow, GetSystemMetrics,
    GetWindow, GetWindowLongPtrW, GetWindowLongW, GetWindowRect, GetWindowTextLengthW,
    GetWindowTextW, IsIconic, IsWindowVisible, LoadCursorW, RegisterClassW,
    SetCursor, SetLayeredWindowAttributes, SetWindowLongPtrW, ShowWindow, TranslateMessage, CS_HREDRAW,
    CS_VREDRAW, CURSORINFO, CURSOR_SHOWING, DI_NORMAL, GA_ROOT, GWLP_USERDATA, GW_OWNER,
    GWL_EXSTYLE, IDC_CROSS, LWA_ALPHA, MSG, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN,
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SW_SHOW, WM_DESTROY, WM_KEYDOWN, WM_LBUTTONDOWN,
    WM_LBUTTONUP, WM_MOUSEMOVE, WM_NCDESTROY, WM_PAINT, WNDCLASSW, WS_EX_LAYERED,
    WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP, WS_VISIBLE, IDC_HAND,
};
use windows_sys::Win32::UI::WindowsAndMessaging::ICONINFO;

struct ScreenDc {
    hwnd: HWND,
    dc: HDC,
}
impl Drop for ScreenDc {
    fn drop(&mut self) {
        unsafe {
            ReleaseDC(self.hwnd, self.dc);
        }
    }
}

struct MemoryDc(HDC);
impl Drop for MemoryDc {
    fn drop(&mut self) {
        unsafe {
            DeleteDC(self.0);
        }
    }
}

struct Bitmap(HBITMAP);
impl Drop for Bitmap {
    fn drop(&mut self) {
        unsafe {
            DeleteObject(self.0 as HGDIOBJ);
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VirtualScreen {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MonitorRect {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowRect {
    pub hwnd: isize,
    pub title: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct PickerRect {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct PickerTarget {
    rect: PickerRect,
    hwnd: Option<isize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PickerAction {
    Capture,
    Record,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PickerChoice {
    pub action: PickerAction,
    pub rect: (u32, u32, u32, u32),
    pub hwnd: Option<isize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PickerToolbar {
    pub rect: (u32, u32, u32, u32),
    pub toolbar: (i32, i32, u32, u32),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PickerToolbarResult {
    Capture,
    Record,
    Cancel,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PickerButtonAction {
    Capture,
    Record,
    Cancel,
}

struct PickerState {
    origin: (i32, i32),
    virtual_rect: PickerRect,
    monitors: Vec<PickerRect>,
    windows: Vec<PickerTarget>,
    drag_start: Option<(i32, i32)>,
    drag_now: Option<(i32, i32)>,
    hover: Option<PickerTarget>,
    selected: Option<PickerTarget>,
    result: Option<(PickerAction, PickerTarget)>,
    action_bar: Option<Box<dyn FnMut(PickerToolbar, Arc<Mutex<Option<PickerToolbarResult>>>)>>,
    action_bar_signal: Option<Arc<Mutex<Option<PickerToolbarResult>>>>,
    action_bar_open: bool,
    cancelled: bool,
    done: bool,
}

pub fn virtual_screen() -> Result<VirtualScreen, String> {
    unsafe {
        let x = GetSystemMetrics(SM_XVIRTUALSCREEN);
        let y = GetSystemMetrics(SM_YVIRTUALSCREEN);
        let width = GetSystemMetrics(SM_CXVIRTUALSCREEN);
        let height = GetSystemMetrics(SM_CYVIRTUALSCREEN);
        if width <= 0 || height <= 0 {
            return Err("Windows reported an empty virtual screen".into());
        }
        Ok(VirtualScreen { x, y, width: width as u32, height: height as u32 })
    }
}

pub fn list_monitors() -> Vec<MonitorRect> {
    unsafe extern "system" fn enum_monitor(
        monitor: HMONITOR,
        _dc: HDC,
        _rect: *mut RECT,
        data: LPARAM,
    ) -> i32 {
        let monitors = &mut *(data as *mut Vec<MonitorRect>);
        let mut info = MONITORINFO {
            cbSize: std::mem::size_of::<MONITORINFO>() as u32,
            rcMonitor: RECT { left: 0, top: 0, right: 0, bottom: 0 },
            rcWork: RECT { left: 0, top: 0, right: 0, bottom: 0 },
            dwFlags: 0,
        };
        if GetMonitorInfoW(monitor, &mut info) != 0 {
            let r = info.rcMonitor;
            let width = (r.right - r.left).max(0) as u32;
            let height = (r.bottom - r.top).max(0) as u32;
            if width > 0 && height > 0 {
                monitors.push(MonitorRect { x: r.left, y: r.top, width, height });
            }
        }
        1
    }

    let mut monitors = Vec::new();
    unsafe {
        EnumDisplayMonitors(
            std::ptr::null_mut(),
            std::ptr::null(),
            Some(enum_monitor),
            &mut monitors as *mut Vec<MonitorRect> as LPARAM,
        );
    }
    monitors
}

pub fn list_windows() -> Vec<WindowRect> {
    unsafe extern "system" fn enum_window(hwnd: HWND, data: LPARAM) -> i32 {
        let windows = &mut *(data as *mut Vec<WindowRect>);
        if !is_capture_target_window(hwnd) {
            return 1;
        }

        let len = GetWindowTextLengthW(hwnd);
        if len <= 0 {
            return 1;
        }
        let mut title = vec![0u16; len as usize + 1];
        let copied = GetWindowTextW(hwnd, title.as_mut_ptr(), title.len() as i32);
        if copied <= 0 {
            return 1;
        }
        title.truncate(copied as usize);
        let title = String::from_utf16_lossy(&title).trim().to_string();
        if title.is_empty() || is_ignored_window_title(&title) {
            return 1;
        }

        let rect = window_frame_rect(hwnd);
        if rect.right <= rect.left || rect.bottom <= rect.top {
            return 1;
        }
        let width = (rect.right - rect.left).max(0) as u32;
        let height = (rect.bottom - rect.top).max(0) as u32;
        if width < 32 || height < 32 {
            return 1;
        }

        windows.push(WindowRect { hwnd: hwnd as isize, title, x: rect.left, y: rect.top, width, height });
        1
    }

    let mut windows = Vec::new();
    unsafe {
        EnumWindows(Some(enum_window), &mut windows as *mut Vec<WindowRect> as LPARAM);
    }
    windows
}

unsafe fn is_capture_target_window(hwnd: HWND) -> bool {
    if hwnd.is_null()
        || hwnd == GetShellWindow()
        || IsWindowVisible(hwnd) == 0
        || IsIconic(hwnd) != 0
        || GetAncestor(hwnd, GA_ROOT) != hwnd
        || !GetWindow(hwnd, GW_OWNER).is_null()
    {
        return false;
    }
    let ex = GetWindowLongW(hwnd, GWL_EXSTYLE) as u32;
    if ex & ((WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT) as u32) != 0 {
        return false;
    }
    let mut cloaked: u32 = 0;
    let hr = DwmGetWindowAttribute(
        hwnd,
        DWMWA_CLOAKED as u32,
        (&mut cloaked as *mut u32).cast(),
        std::mem::size_of::<u32>() as u32,
    );
    if hr >= 0 && cloaked != 0 {
        return false;
    }
    true
}

unsafe fn window_frame_rect(hwnd: HWND) -> RECT {
    let mut rect = RECT { left: 0, top: 0, right: 0, bottom: 0 };
    let hr = DwmGetWindowAttribute(
        hwnd,
        DWMWA_EXTENDED_FRAME_BOUNDS as u32,
        (&mut rect as *mut RECT).cast(),
        std::mem::size_of::<RECT>() as u32,
    );
    if hr < 0 || rect.right <= rect.left || rect.bottom <= rect.top {
        let _ = GetWindowRect(hwnd, &mut rect);
    }
    rect
}

pub fn pick_rect() -> Result<Option<(u32, u32, u32, u32)>, String> {
    Ok(pick_action()?.map(|choice| choice.rect))
}

pub fn pick_action() -> Result<Option<PickerChoice>, String> {
    pick_action_inner(None)
}

pub fn pick_action_with_toolbar<F>(toolbar: F) -> Result<Option<PickerChoice>, String>
where
    F: FnMut(PickerToolbar, Arc<Mutex<Option<PickerToolbarResult>>>) + 'static,
{
    pick_action_inner(Some(Box::new(toolbar)))
}

fn pick_action_inner(
    action_bar: Option<Box<dyn FnMut(PickerToolbar, Arc<Mutex<Option<PickerToolbarResult>>>)>>,
) -> Result<Option<PickerChoice>, String> {
    let vs = virtual_screen()?;
    let monitors = list_monitors()
        .into_iter()
        .map(|m| PickerRect {
            x: m.x - vs.x,
            y: m.y - vs.y,
            width: m.width,
            height: m.height,
        })
        .collect();
    let windows = list_windows()
        .into_iter()
        .map(|w| PickerTarget {
            rect: PickerRect {
                x: w.x - vs.x,
                y: w.y - vs.y,
                width: w.width,
                height: w.height,
            },
            hwnd: Some(w.hwnd),
        })
        .collect();
    let virtual_rect = PickerRect { x: 0, y: 0, width: vs.width, height: vs.height };
    let mut state = Box::new(PickerState {
        origin: (vs.x, vs.y),
        virtual_rect,
        monitors,
        windows,
        drag_start: None,
        drag_now: None,
        hover: None,
        selected: None,
        result: None,
        action_bar,
        action_bar_signal: None,
        action_bar_open: false,
        cancelled: false,
        done: false,
    });

    unsafe {
        let class_name = wide_null("WondershotNativeCapturePicker");
        let hinstance = GetModuleHandleW(std::ptr::null());
        let wc = WNDCLASSW {
            style: CS_HREDRAW | CS_VREDRAW,
            lpfnWndProc: Some(picker_wndproc),
            hInstance: hinstance,
            hCursor: LoadCursorW(std::ptr::null_mut(), IDC_CROSS),
            hbrBackground: std::ptr::null_mut(),
            lpszClassName: class_name.as_ptr(),
            ..std::mem::zeroed()
        };
        RegisterClassW(&wc);

        let hwnd = CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED,
            class_name.as_ptr(),
            class_name.as_ptr(),
            WS_POPUP | WS_VISIBLE,
            vs.x,
            vs.y,
            vs.width as i32,
            vs.height as i32,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            hinstance,
            std::ptr::null_mut(),
        );
        if hwnd.is_null() {
            return Err("CreateWindowExW failed".into());
        }

        let state_ptr = state.as_mut() as *mut PickerState;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, state_ptr as isize);
        // Native dimming: let the real desktop show through a translucent black
        // popup, then draw selection outlines on top.
        SetLayeredWindowAttributes(hwnd, 0, 178, LWA_ALPHA);
        ShowWindow(hwnd, SW_SHOW);
        SetFocus(hwnd);
        UpdateWindow(hwnd);

        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
            if let Some(action) = take_toolbar_result(state.as_mut()) {
                match action {
                    PickerToolbarResult::Capture => {
                        if let Some(selected) = state.selected {
                            state.result = Some((PickerAction::Capture, selected));
                        }
                    }
                    PickerToolbarResult::Record => {
                        if let Some(selected) = state.selected {
                            state.result = Some((PickerAction::Record, selected));
                        }
                    }
                    PickerToolbarResult::Cancel => {
                        state.cancelled = true;
                    }
                }
                DestroyWindow(hwnd);
            }
            if state.done || state.result.is_some() || state.cancelled {
                break;
            }
        }

        if !hwnd.is_null() {
            DestroyWindow(hwnd);
        }
    }

    Ok(state.result.map(|(action, target)| PickerChoice {
        action,
        hwnd: target.hwnd,
        rect: {
            let r = target.rect;
            (r.x.max(0) as u32, r.y.max(0) as u32, r.width, r.height)
        },
    }))
}

fn wide_null(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

unsafe extern "system" fn picker_wndproc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut PickerState;
    match msg {
        WM_LBUTTONDOWN => {
            if let Some(state) = ptr.as_mut() {
                let p = lparam_point(lparam);
                if state.action_bar_open {
                    return 0;
                }
                match hit_action_bar(state, p) {
                    Some(PickerButtonAction::Capture) => {
                        if let Some(selected) = state.selected {
                            state.result = Some((PickerAction::Capture, selected));
                            DestroyWindow(hwnd);
                        }
                        return 0;
                    }
                    Some(PickerButtonAction::Record) => {
                        if let Some(selected) = state.selected {
                            state.result = Some((PickerAction::Record, selected));
                            DestroyWindow(hwnd);
                        }
                        return 0;
                    }
                    Some(PickerButtonAction::Cancel) => {
                        state.cancelled = true;
                        DestroyWindow(hwnd);
                        return 0;
                    }
                    None => {}
                }

                let old = active_rect(state);
                state.selected = None;
                state.drag_start = Some(p);
                state.drag_now = Some(p);
                state.hover = target_at(state, p);
                let _ = SetCapture(hwnd);
                if old.is_some() {
                    invalidate_all(hwnd);
                } else {
                    invalidate_picker(hwnd, old, active_rect(state));
                }
            }
            0
        }
        WM_MOUSEMOVE => {
            if let Some(state) = ptr.as_mut() {
                if state.selected.is_some() && state.drag_start.is_none() {
                    update_picker_cursor(state, lparam_point(lparam));
                    return 0;
                }
                let old = active_rect(state);
                let p = lparam_point(lparam);
                if state.drag_start.is_some() {
                    state.drag_now = Some(p);
                } else {
                    state.hover = target_at(state, p);
                }
                let new = active_rect(state);
                if old != new {
                    invalidate_picker(hwnd, old, new);
                }
                update_picker_cursor(state, p);
            }
            0
        }
        WM_LBUTTONUP => {
            if let Some(state) = ptr.as_mut() {
                ReleaseCapture();
                let p = lparam_point(lparam);
                state.drag_now = Some(p);
                let old = active_rect(state);
                state.selected = selection_target(state).or(state.hover);
                state.drag_start = None;
                state.drag_now = None;
                state.hover = None;
                if state.selected.is_some() {
                    invalidate_all(hwnd);
                    UpdateWindow(hwnd);
                    if state.action_bar.is_some() {
                        show_external_action_bar(state);
                    }
                } else {
                    invalidate_picker(hwnd, old, active_rect(state));
                }
            }
            0
        }
        WM_KEYDOWN => {
            if wparam == 0x1b {
                if let Some(state) = ptr.as_mut() {
                    state.cancelled = true;
                }
                DestroyWindow(hwnd);
                return 0;
            }
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        WM_PAINT => {
            let mut ps: PAINTSTRUCT = std::mem::zeroed();
            let dc = BeginPaint(hwnd, &mut ps);
            if let Some(state) = ptr.as_ref() {
                paint_picker(dc, &ps, state);
            }
            EndPaint(hwnd, &ps);
            0
        }
        WM_DESTROY | WM_NCDESTROY => {
            if let Some(state) = ptr.as_mut() {
                state.done = true;
            }
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

fn lparam_point(lparam: LPARAM) -> (i32, i32) {
    let x = (lparam as i16) as i32;
    let y = ((lparam >> 16) as i16) as i32;
    (x, y)
}

fn selection_rect(state: &PickerState) -> Option<PickerRect> {
    let (Some(a), Some(b)) = (state.drag_start, state.drag_now) else { return None };
    let x = a.0.min(b.0);
    let y = a.1.min(b.1);
    let width = a.0.abs_diff(b.0);
    let height = a.1.abs_diff(b.1);
    (width >= 4 && height >= 4).then_some(PickerRect { x, y, width, height })
}

fn selection_target(state: &PickerState) -> Option<PickerTarget> {
    selection_rect(state).map(|rect| PickerTarget { rect, hwnd: None })
}

fn active_target(state: &PickerState) -> Option<PickerTarget> {
    state.selected.or_else(|| selection_target(state)).or(state.hover)
}

fn active_rect(state: &PickerState) -> Option<PickerRect> {
    active_target(state).map(|t| t.rect)
}

fn window_at(state: &PickerState, p: (i32, i32)) -> Option<PickerTarget> {
    state.windows.iter().copied().find(|r| {
        let rect = r.rect;
        p.0 >= rect.x
            && p.0 <= rect.x + rect.width as i32
            && p.1 >= rect.y
            && p.1 <= rect.y + rect.height as i32
    })
}

fn target_at(state: &PickerState, p: (i32, i32)) -> Option<PickerTarget> {
    edge_fullscreen_hover(state, p)
        .or_else(|| window_at(state, p))
        .or_else(|| monitor_at(state, p).map(|rect| PickerTarget { rect, hwnd: None }))
}

fn monitor_at(state: &PickerState, p: (i32, i32)) -> Option<PickerRect> {
    state.monitors.iter().copied().find(|r| {
        p.0 >= r.x
            && p.0 <= r.x + r.width as i32
            && p.1 >= r.y
            && p.1 <= r.y + r.height as i32
    })
}

fn edge_fullscreen_hover(state: &PickerState, p: (i32, i32)) -> Option<PickerTarget> {
    let edge = 10;
    let r = monitor_at(state, p).unwrap_or(state.virtual_rect);
    let right = r.x + r.width as i32;
    let bottom = r.y + r.height as i32;
    (p.0 <= r.x + edge || p.1 <= r.y + edge || p.0 >= right - edge || p.1 >= bottom - edge)
        .then_some(PickerTarget { rect: r, hwnd: None })
}

fn paint_picker(dc: HDC, ps: &PAINTSTRUCT, state: &PickerState) {
    unsafe {
        let dim = CreateSolidBrush(0x000000);
        FillRect(dc, &ps.rcPaint, dim);
        DeleteObject(dim as HGDIOBJ);

        let highlight = CreateSolidBrush(0x00606060);
        let outline = CreateSolidBrush(0x004db8ff);
        if let Some(r) = active_rect(state) {
            let rect = RECT {
                left: r.x,
                top: r.y,
                right: r.x + r.width as i32,
                bottom: r.y + r.height as i32,
            };
            FillRect(dc, &rect, highlight);
            FrameRect(dc, &rect, outline);
            if state.selected.is_some() && state.action_bar.is_none() {
                paint_action_bar(dc, state, r);
            }
        }
        DeleteObject(highlight as HGDIOBJ);
        DeleteObject(outline as HGDIOBJ);
    }
}

fn paint_action_bar(dc: HDC, state: &PickerState, selected: PickerRect) {
    unsafe {
        let bar = action_bar_rect(state, selected);
        let bg = CreateSolidBrush(0x003a342e);
        FillRect(dc, &bar, bg);
        DeleteObject(bg as HGDIOBJ);

        SetBkMode(dc, 1);
        SetTextColor(dc, 0x00ffffff);
        for (rect, action, label) in action_buttons(state, selected) {
            let fill = match action {
                PickerButtonAction::Capture => 0x00c07a22,
                PickerButtonAction::Record => 0x003232d8,
                PickerButtonAction::Cancel => 0x00484440,
            };
            let brush = CreateSolidBrush(fill);
            FillRect(dc, &rect, brush);
            DeleteObject(brush as HGDIOBJ);
            let border = CreateSolidBrush(0x00635a50);
            FrameRect(dc, &rect, border);
            DeleteObject(border as HGDIOBJ);
            let text = wide(label);
            TextOutW(dc, rect.left + 12, rect.top + 9, text.as_ptr(), text.len() as i32);
        }
        let size = format!("{} x {}", selected.width, selected.height);
        let text = wide(&size);
        TextOutW(dc, bar.right - 86, bar.top + 20, text.as_ptr(), text.len() as i32);
    }
}

fn hit_action_bar(state: &PickerState, p: (i32, i32)) -> Option<PickerButtonAction> {
    if state.action_bar.is_some() {
        return None;
    }
    let selected = state.selected?.rect;
    action_buttons(state, selected)
        .into_iter()
        .find(|(r, _, _)| p.0 >= r.left && p.0 <= r.right && p.1 >= r.top && p.1 <= r.bottom)
        .map(|(_, action, _)| action)
}

fn show_external_action_bar(state: &mut PickerState) {
    let Some(selected) = state.selected else { return };
    if state.action_bar_open {
        return;
    }
    let bar = action_bar_rect(state, selected.rect);
    let payload = PickerToolbar {
        rect: (
            selected.rect.x.max(0) as u32,
            selected.rect.y.max(0) as u32,
            selected.rect.width,
            selected.rect.height,
        ),
        toolbar: (
            state.origin.0 + bar.left,
            state.origin.1 + bar.top,
            (bar.right - bar.left).max(0) as u32,
            (bar.bottom - bar.top).max(0) as u32,
        ),
    };
    let signal = Arc::new(Mutex::new(None));
    if let Some(show) = state.action_bar.as_mut() {
        show(payload, signal.clone());
        state.action_bar_signal = Some(signal);
        state.action_bar_open = true;
    }
}

fn take_toolbar_result(state: &mut PickerState) -> Option<PickerToolbarResult> {
    let signal = state.action_bar_signal.as_ref()?;
    let result = signal.lock().ok()?.take();
    if result.is_some() {
        state.action_bar_open = false;
        state.action_bar_signal = None;
    }
    result
}

fn update_picker_cursor(state: &PickerState, p: (i32, i32)) {
    unsafe {
        let cursor = if hit_action_bar(state, p).is_some() {
            LoadCursorW(std::ptr::null_mut(), IDC_HAND)
        } else {
            LoadCursorW(std::ptr::null_mut(), IDC_CROSS)
        };
        SetCursor(cursor);
    }
}

fn action_bar_rect(state: &PickerState, selected: PickerRect) -> RECT {
    let width = 296;
    let height = 58;
    let margin = 14;
    let screen = state.virtual_rect;
    let mut left = selected.x + (selected.width as i32 - width) / 2;
    left = left.max(screen.x + margin).min(screen.x + screen.width as i32 - width - margin);
    let below = selected.y + selected.height as i32 + margin;
    let top = if below + height <= screen.y + screen.height as i32 - margin {
        below
    } else {
        (selected.y - height - margin).max(screen.y + margin)
    };
    RECT { left, top, right: left + width, bottom: top + height }
}

fn action_buttons(state: &PickerState, selected: PickerRect) -> Vec<(RECT, PickerButtonAction, &'static str)> {
    let bar = action_bar_rect(state, selected);
    let top = bar.top + 8;
    let mut left = bar.left + 8;
    let specs = [
        (72, PickerButtonAction::Capture, "Shot"),
        (68, PickerButtonAction::Record, "Rec"),
        (66, PickerButtonAction::Cancel, "Cancel"),
    ];
    specs
        .into_iter()
        .map(|(width, action, label)| {
            let rect = RECT { left, top, right: left + width, bottom: top + 36 };
            left += width + 8;
            (rect, action, label)
        })
        .collect()
}

fn invalidate_picker(hwnd: HWND, old: Option<PickerRect>, new: Option<PickerRect>) {
    unsafe {
        for r in [old, new].into_iter().flatten() {
            let rect = padded_rect(r, 64);
            InvalidateRect(hwnd, &rect, 1);
        }
    }
}

fn invalidate_all(hwnd: HWND) {
    unsafe {
        InvalidateRect(hwnd, std::ptr::null(), 1);
    }
}

fn padded_rect(r: PickerRect, pad: i32) -> RECT {
    RECT {
        left: r.x - pad,
        top: r.y - pad,
        right: r.x + r.width as i32 + pad,
        bottom: r.y + r.height as i32 + pad,
    }
}

fn is_ignored_window_title(title: &str) -> bool {
    title.ends_with(" - Entry Point Not Found")
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().collect()
}

#[cfg(test)]
mod tests {
    use super::is_ignored_window_title;

    #[test]
    fn ignores_windows_loader_error_dialogs() {
        assert!(is_ignored_window_title(
            "wondershot_lib-366364c289febb3c.exe - Entry Point Not Found"
        ));
        assert!(!is_ignored_window_title("Wondershot"));
        assert!(!is_ignored_window_title("Entry Point Not Found - Notes"));
    }
}

pub fn capture_fullscreen_to(path: &Path, capture_cursor: bool) -> Result<(), String> {
    let img = capture_fullscreen_image(capture_cursor)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    img.save(path).map_err(|e| e.to_string())
}

pub fn capture_fullscreen_rgba() -> Result<RgbaImage, String> {
    capture_fullscreen_image(false)
}

pub fn capture_fullscreen_rgba_with_cursor(capture_cursor: bool) -> Result<RgbaImage, String> {
    capture_fullscreen_image(capture_cursor)
}

pub fn capture_window_rgba(hwnd: isize) -> Result<RgbaImage, String> {
    unsafe {
        let hwnd = hwnd as HWND;
        if hwnd.is_null() {
            return Err("empty window handle".into());
        }
        let rect = window_frame_rect(hwnd);
        let width = rect.right - rect.left;
        let height = rect.bottom - rect.top;
        if width <= 0 || height <= 0 {
            return Err("window has empty bounds".into());
        }

        let screen = GetDC(std::ptr::null_mut());
        if screen.is_null() {
            return Err("GetDC failed".into());
        }
        let screen = ScreenDc { hwnd: std::ptr::null_mut(), dc: screen };

        let mem = CreateCompatibleDC(screen.dc);
        if mem.is_null() {
            return Err("CreateCompatibleDC failed".into());
        }
        let mem = MemoryDc(mem);

        let bitmap = CreateCompatibleBitmap(screen.dc, width, height);
        if bitmap.is_null() {
            return Err("CreateCompatibleBitmap failed".into());
        }
        let bitmap = Bitmap(bitmap);

        let old = SelectObject(mem.0, bitmap.0 as HGDIOBJ);
        if old.is_null() {
            return Err("SelectObject failed".into());
        }

        const PW_RENDERFULLCONTENT: u32 = 0x00000002;
        if PrintWindow(hwnd, mem.0, PW_RENDERFULLCONTENT) == 0 {
            SelectObject(mem.0, old);
            return Err("PrintWindow failed".into());
        }

        let image = bitmap_to_rgba(mem.0, bitmap.0, width, height);
        SelectObject(mem.0, old);
        image
    }
}

fn capture_fullscreen_image(capture_cursor: bool) -> Result<RgbaImage, String> {
    unsafe {
        let vs = virtual_screen()?;
        let x = vs.x;
        let y = vs.y;
        let width = vs.width as i32;
        let height = vs.height as i32;

        // NULL captures the whole desktop DC. This is the conventional Windows
        // screenshot path and is more reliable than a GetDesktopWindow DC on
        // multi-monitor/DPI-mixed desktops.
        let screen = GetDC(std::ptr::null_mut());
        if screen.is_null() {
            return Err("GetDC failed".into());
        }
        let screen = ScreenDc { hwnd: std::ptr::null_mut(), dc: screen };

        let mem = CreateCompatibleDC(screen.dc);
        if mem.is_null() {
            return Err("CreateCompatibleDC failed".into());
        }
        let mem = MemoryDc(mem);

        let bitmap = CreateCompatibleBitmap(screen.dc, width, height);
        if bitmap.is_null() {
            return Err("CreateCompatibleBitmap failed".into());
        }
        let bitmap = Bitmap(bitmap);

        let old = SelectObject(mem.0, bitmap.0 as HGDIOBJ);
        if old.is_null() {
            return Err("SelectObject failed".into());
        }

        if BitBlt(mem.0, 0, 0, width, height, screen.dc, x, y, SRCCOPY | CAPTUREBLT) == 0 {
            SelectObject(mem.0, old);
            return Err("BitBlt failed".into());
        }
        if capture_cursor {
            draw_cursor(mem.0, x, y);
        }

        let mut info = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: width,
                biHeight: -height, // top-down DIB
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB,
                biSizeImage: 0,
                biXPelsPerMeter: 0,
                biYPelsPerMeter: 0,
                biClrUsed: 0,
                biClrImportant: 0,
            },
            bmiColors: [Default::default(); 1],
        };
        let mut bgra = vec![0u8; width as usize * height as usize * 4];
        let rows = GetDIBits(
            mem.0,
            bitmap.0,
            0,
            height as u32,
            bgra.as_mut_ptr().cast(),
            &mut info,
            DIB_RGB_COLORS,
        );
        SelectObject(mem.0, old);
        if rows == 0 {
            return Err("GetDIBits failed".into());
        }

        for px in bgra.chunks_exact_mut(4) {
            px.swap(0, 2); // BGRA -> RGBA
            px[3] = 255;
        }
        ImageBuffer::<Rgba<u8>, _>::from_raw(width as u32, height as u32, bgra)
            .ok_or_else(|| "could not construct captured image".to_string())
    }
}

fn draw_cursor(dc: HDC, origin_x: i32, origin_y: i32) {
    unsafe {
        let mut cursor = CURSORINFO {
            cbSize: std::mem::size_of::<CURSORINFO>() as u32,
            flags: 0,
            hCursor: std::ptr::null_mut(),
            ptScreenPos: Default::default(),
        };
        if GetCursorInfo(&mut cursor) == 0
            || cursor.flags & CURSOR_SHOWING == 0
            || cursor.hCursor.is_null()
        {
            return;
        }

        let mut icon = ICONINFO {
            fIcon: 0,
            xHotspot: 0,
            yHotspot: 0,
            hbmMask: std::ptr::null_mut(),
            hbmColor: std::ptr::null_mut(),
        };
        let (hot_x, hot_y) = if GetIconInfo(cursor.hCursor, &mut icon) != 0 {
            let hot = (icon.xHotspot as i32, icon.yHotspot as i32);
            if !icon.hbmMask.is_null() {
                DeleteObject(icon.hbmMask as HGDIOBJ);
            }
            if !icon.hbmColor.is_null() {
                DeleteObject(icon.hbmColor as HGDIOBJ);
            }
            hot
        } else {
            (0, 0)
        };

        let draw_x = cursor.ptScreenPos.x - origin_x - hot_x;
        let draw_y = cursor.ptScreenPos.y - origin_y - hot_y;
        let _ = DrawIconEx(dc, draw_x, draw_y, cursor.hCursor, 0, 0, 0, std::ptr::null_mut(), DI_NORMAL);
    }
}

fn bitmap_to_rgba(dc: HDC, bitmap: HBITMAP, width: i32, height: i32) -> Result<RgbaImage, String> {
    unsafe {
        let mut info = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: width,
                biHeight: -height,
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB,
                biSizeImage: 0,
                biXPelsPerMeter: 0,
                biYPelsPerMeter: 0,
                biClrUsed: 0,
                biClrImportant: 0,
            },
            bmiColors: [Default::default(); 1],
        };
        let mut bgra = vec![0u8; width as usize * height as usize * 4];
        let rows = GetDIBits(
            dc,
            bitmap,
            0,
            height as u32,
            bgra.as_mut_ptr().cast(),
            &mut info,
            DIB_RGB_COLORS,
        );
        if rows == 0 {
            return Err("GetDIBits failed".into());
        }

        for px in bgra.chunks_exact_mut(4) {
            px.swap(0, 2);
            px[3] = 255;
        }
        ImageBuffer::<Rgba<u8>, _>::from_raw(width as u32, height as u32, bgra)
            .ok_or_else(|| "could not construct captured image".to_string())
    }
}
