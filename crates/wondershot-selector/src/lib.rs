mod action_bar;

use std::collections::HashMap;
use std::num::NonZeroU32;
use std::path::Path;
use std::rc::Rc;

use action_bar::{ActionBarCache, ActionBarView, ButtonStates, BUTTON_SIZE, BUTTON_TOP, CANCEL_LEFT, CAPTURE_LEFT, RECORD_LEFT};
use serde::{Deserialize, Serialize};
use softbuffer::{Context, Surface};
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, EventLoop};
use winit::keyboard::{Key, NamedKey};
use winit::window::{CursorIcon, Icon, Window, WindowAttributes, WindowId, WindowLevel};
#[cfg(not(target_os = "macos"))]
use winit::window::Fullscreen;

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum SelectionMode {
    Region,
    Window,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct WindowTarget {
    pub id: String,
    pub title: String,
    pub application: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub z_order: u32,
    pub capturable: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct FrozenDisplay {
    pub id: String,
    pub frame_path: String,
    pub x: i32,
    pub y: i32,
    pub pixel_width: u32,
    pub pixel_height: u32,
    #[serde(default)]
    pub windows: Vec<WindowTarget>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct SelectionSession {
    pub operation_id: String,
    pub mode: SelectionMode,
    pub displays: Vec<FrozenDisplay>,
    #[serde(default)]
    pub action_bar: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum SelectionResult {
    Region {
        display_id: String,
        x: u32,
        y: u32,
        width: u32,
        height: u32,
        #[serde(default)]
        action: SelectionAction,
    },
    Window {
        window_id: String,
    },
    Cancelled,
}

#[derive(Debug, Clone, Copy, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum SelectionAction {
    #[default]
    Capture,
    Record,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Rect {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

impl Rect {
    fn contains(self, x: i32, y: i32) -> bool {
        x >= self.x
            && y >= self.y
            && x < self.x.saturating_add_unsigned(self.width)
            && y < self.y.saturating_add_unsigned(self.height)
    }
}

fn normalized_drag(start: (i32, i32), end: (i32, i32), width: u32, height: u32) -> Rect {
    let max_x = width as i32;
    let max_y = height as i32;
    let x1 = start.0.min(end.0).clamp(0, max_x);
    let y1 = start.1.min(end.1).clamp(0, max_y);
    let x2 = start.0.max(end.0).clamp(0, max_x);
    let y2 = start.1.max(end.1).clamp(0, max_y);
    Rect {
        x: x1,
        y: y1,
        width: (x2 - x1) as u32,
        height: (y2 - y1) as u32,
    }
}

fn windows_at_point(display: &FrozenDisplay, x: i32, y: i32) -> Vec<&WindowTarget> {
    let global_x = display.x + x;
    let global_y = display.y + y;
    let mut matches: Vec<&WindowTarget> = display
        .windows
        .iter()
        .filter(|target| {
            target.capturable
                && Rect {
                    x: target.x,
                    y: target.y,
                    width: target.width,
                    height: target.height,
                }
                .contains(global_x, global_y)
        })
        .collect();
    matches.sort_by_key(|target| target.z_order);
    matches
}

fn cycle_window<'a>(
    display: &'a FrozenDisplay,
    point: (i32, i32),
    current: Option<&str>,
    direction: i32,
) -> Option<&'a WindowTarget> {
    let matches = windows_at_point(display, point.0, point.1);
    if matches.is_empty() {
        return None;
    }
    let current_index = current.and_then(|id| matches.iter().position(|target| target.id == id));
    let index = match current_index {
        Some(index) => (index as i32 + direction).rem_euclid(matches.len() as i32) as usize,
        None if direction < 0 => matches.len() - 1,
        None => 0,
    };
    Some(matches[index])
}

struct DisplayWindow {
    window: Rc<Window>,
    surface: Surface<Rc<Window>, Rc<Window>>,
    display: FrozenDisplay,
    base: Vec<u32>,
    dimmed: Vec<u32>,
    width: u32,
    height: u32,
    cursor: (i32, i32),
    drag_start: Option<(i32, i32)>,
    locked_region: Option<Rect>,
    selected_window_id: Option<String>,
    action_bar_cache: ActionBarCache,
    /// Action-bar button the mouse went down on; the action runs on release.
    pressed_action: Option<ActionBarHit>,
    cursor_icon: CursorIcon,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ActionBarHit {
    Capture,
    Record,
    Cancel,
}

/// Logical size of the floating action bar.
const BAR_WIDTH: u32 = 282;
const BAR_HEIGHT: u32 = 58;

fn positioned_action_bar(selected: Rect, width: u32, height: u32) -> Rect {
    const GAP: i32 = 8;
    let centered_x = selected
        .x
        .saturating_add_unsigned(selected.width / 2)
        .saturating_sub((BAR_WIDTH / 2) as i32);
    let x = centered_x.clamp(8, (width as i32 - BAR_WIDTH as i32 - 8).max(8));
    let below = selected
        .y
        .saturating_add_unsigned(selected.height)
        .saturating_add(GAP);
    let y = if below.saturating_add_unsigned(BAR_HEIGHT) <= height as i32 - 8 {
        below
    } else {
        selected.y.saturating_sub(BAR_HEIGHT as i32 + GAP).max(8)
    };
    Rect {
        x,
        y,
        width: BAR_WIDTH.min(width.saturating_sub(16)),
        height: BAR_HEIGHT,
    }
}

/// Pointer over an action-bar button, crosshair everywhere else, so the
/// overlay reads the same on macOS, Windows and Linux.
fn overlay_cursor(hit: Option<ActionBarHit>) -> CursorIcon {
    if hit.is_some() { CursorIcon::Pointer } else { CursorIcon::Crosshair }
}

/// A button click completes only when released over the button it was pressed on.
fn clicked_action(pressed: Option<ActionBarHit>, released_over: Option<ActionBarHit>) -> Option<ActionBarHit> {
    pressed.filter(|pressed| released_over == Some(*pressed))
}

fn action_bar_hit_at(bar: Rect, point: (i32, i32), scale: f64) -> Option<ActionBarHit> {
    if !bar.contains(point.0, point.1) { return None; }
    let local_x = ((point.0 - bar.x) as f64 / scale).floor() as i32;
    let local_y = ((point.1 - bar.y) as f64 / scale).floor() as i32;
    let within = |start: i32, value: i32| (start..start + BUTTON_SIZE).contains(&value);
    if !within(BUTTON_TOP, local_y) { return None; }
    [(CAPTURE_LEFT, ActionBarHit::Capture), (RECORD_LEFT, ActionBarHit::Record),
        (CANCEL_LEFT, ActionBarHit::Cancel)]
        .into_iter()
        .find(|(left, _)| within(*left, local_x))
        .map(|(_, hit)| hit)
}

impl DisplayWindow {
    fn action_bar_rect(&self) -> Option<Rect> {
        let selected = self.locked_region?;
        let scale = self.window.scale_factor();
        let logical = |v: u32| (f64::from(v) / scale).round() as u32;
        let bar = positioned_action_bar(
            Rect { x: (selected.x as f64 / scale).round() as i32,
                y: (selected.y as f64 / scale).round() as i32,
                width: logical(selected.width), height: logical(selected.height) },
            logical(self.width), logical(self.height),
        );
        Some(Rect { x: (bar.x as f64 * scale).round() as i32,
            y: (bar.y as f64 * scale).round() as i32,
            width: (bar.width as f64 * scale).round() as u32,
            height: (bar.height as f64 * scale).round() as u32 })
    }

    fn action_bar_hit(&self) -> Option<ActionBarHit> {
        let bar = self.action_bar_rect()?;
        let (x, y) = self.cursor;
        if !bar.contains(x, y) {
            return None;
        }
        action_bar_hit_at(bar, (x, y), self.window.scale_factor())
    }

    /// Applies the cursor for the current pointer position, only when it changes.
    fn sync_cursor(&mut self) {
        let icon = overlay_cursor(self.action_bar_hit());
        if icon != self.cursor_icon {
            self.cursor_icon = icon;
            self.window.set_cursor(icon);
        }
    }

    fn view_to_source_point(&self, point: (i32, i32)) -> (i32, i32) {
        (
            scale_i32(point.0, self.width, self.display.pixel_width),
            scale_i32(point.1, self.height, self.display.pixel_height),
        )
    }

    fn source_to_view_rect(&self, rect: Rect) -> Rect {
        Rect {
            x: scale_i32(rect.x, self.display.pixel_width, self.width),
            y: scale_i32(rect.y, self.display.pixel_height, self.height),
            width: scale_u32(rect.width, self.display.pixel_width, self.width),
            height: scale_u32(rect.height, self.display.pixel_height, self.height),
        }
    }

    fn view_to_source_rect(&self, rect: Rect) -> Rect {
        Rect {
            x: scale_i32(rect.x, self.width, self.display.pixel_width),
            y: scale_i32(rect.y, self.height, self.display.pixel_height),
            width: scale_u32(rect.width, self.width, self.display.pixel_width),
            height: scale_u32(rect.height, self.height, self.display.pixel_height),
        }
    }

    fn selection_rect(&self, mode: SelectionMode) -> Option<Rect> {
        match mode {
            SelectionMode::Region => self.locked_region.or_else(|| {
                self.drag_start
                    .map(|start| normalized_drag(start, self.cursor, self.width, self.height))
            }),
            SelectionMode::Window => self
                .selected_window_id
                .as_deref()
                .and_then(|id| self.display.windows.iter().find(|target| target.id == id))
                .map(|target| {
                    self.source_to_view_rect(Rect {
                        x: target.x - self.display.x,
                        y: target.y - self.display.y,
                        width: target.width,
                        height: target.height,
                    })
                }),
        }
    }

    fn update_hover(&mut self) {
        let point = self.view_to_source_point(self.cursor);
        self.selected_window_id = windows_at_point(&self.display, point.0, point.1)
            .first()
            .map(|target| target.id.clone());
    }

    fn cycle_hover(&mut self, direction: i32) {
        self.selected_window_id = cycle_window(
            &self.display,
            self.view_to_source_point(self.cursor),
            self.selected_window_id.as_deref(),
            direction,
        )
        .map(|target| target.id.clone());
    }

    fn redraw(&mut self, mode: SelectionMode) -> Result<(), String> {
        let width = NonZeroU32::new(self.width).ok_or("selector display has zero width")?;
        let height = NonZeroU32::new(self.height).ok_or("selector display has zero height")?;
        let selection_rect = self.selection_rect(mode);
        let action_bar = self.action_bar_rect();
        let action_bar_hit = self.action_bar_hit();
        let locked_region = self.locked_region.map(|r| self.view_to_source_rect(r));
        self.surface
            .resize(width, height)
            .map_err(|e| e.to_string())?;
        let mut buffer = self.surface.buffer_mut().map_err(|e| e.to_string())?;
        if buffer.len() != self.base.len() {
            return Err("selector surface size does not match frozen frame".into());
        }

        buffer.copy_from_slice(&self.dimmed);

        if let Some(rect) = selection_rect {
            let rect = clamp_rect(rect, self.width, self.height);
            restore_rect(&mut buffer, &self.base, self.width, rect);
            draw_border(&mut buffer, self.width, self.height, rect, 3, 0x002fd4d4);
        }

        if let Some(bar) = action_bar {
            self.action_bar_cache.draw(&mut buffer, self.width, self.height, ActionBarView {
                origin: (bar.x, bar.y),
                size: (bar.width, bar.height),
                scale: self.window.scale_factor() as f32,
                buttons: ButtonStates { hovered: action_bar_hit, pressed: self.pressed_action },
                label: locked_region.map(|r| (r.width, r.height)),
            });
        }

        if mode == SelectionMode::Region && self.locked_region.is_none() {
            draw_crosshair(
                &mut buffer,
                self.width,
                self.height,
                self.cursor.0,
                self.cursor.1,
            );
        }
        buffer.present().map_err(|e| e.to_string())
    }
}

struct SelectorApp {
    session: SelectionSession,
    icon: Icon,
    context: Option<Context<Rc<Window>>>,
    windows: HashMap<WindowId, DisplayWindow>,
    result: Option<SelectionResult>,
    pending_result: Option<SelectionResult>,
    modifiers: winit::keyboard::ModifiersState,
    started: std::time::Instant,
    first_frame: bool,
}

impl SelectorApp {
    fn new(session: SelectionSession, icon: Icon) -> Self {
        Self {
            session,
            icon,
            context: None,
            windows: HashMap::new(),
            result: None,
            pending_result: None,
            modifiers: winit::keyboard::ModifiersState::empty(),
            started: std::time::Instant::now(),
            first_frame: false,
        }
    }

    fn finish(&mut self, event_loop: &ActiveEventLoop, result: SelectionResult) {
        self.result = Some(result);
        event_loop.exit();
    }

}

impl ApplicationHandler for SelectorApp {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if !self.windows.is_empty() {
            return;
        }
        let monitors: Vec<_> = event_loop.available_monitors().collect();
        if monitors.is_empty() {
            self.finish(event_loop, SelectionResult::Cancelled);
            return;
        }

        for (index, display) in self.session.displays.clone().into_iter().enumerate() {
            let monitor = monitors
                .iter()
                .find(|monitor| {
                    let position = monitor.position();
                    position.x == display.x && position.y == display.y
                })
                .or_else(|| monitors.get(index))
                .cloned();
            let Some(monitor) = monitor else {
                continue;
            };

            let image = match image::open(Path::new(&display.frame_path)) {
                Ok(image) => image.to_rgba8(),
                Err(_) => continue,
            };
            let size = monitor.size();
            let image = if image.width() != size.width || image.height() != size.height {
                image::imageops::resize(
                    &image,
                    size.width,
                    size.height,
                    image::imageops::FilterType::Triangle,
                )
            } else {
                image
            };
            let base: Vec<u32> = image
                .pixels()
                .map(|pixel| {
                    let [r, g, b, _] = pixel.0;
                    ((r as u32) << 16) | ((g as u32) << 8) | b as u32
                })
                .collect();

            let attributes = WindowAttributes::default()
                .with_title("Wondershot selector")
                .with_window_icon(Some(self.icon.clone()))
                .with_decorations(false)
                .with_resizable(false)
                .with_window_level(WindowLevel::AlwaysOnTop);
            #[cfg(target_os = "linux")]
            let attributes = {
                // Winit is separate from the Tauri/GTK main window. Give both
                // Wayland and X11 the same identity as the installed launcher.
                let attributes = winit::platform::wayland::WindowAttributesExtWayland::with_name(
                    attributes,
                    "io.github.jackmusick.wondershot",
                    "wondershot",
                );
                winit::platform::x11::WindowAttributesExtX11::with_name(
                    attributes,
                    "io.github.jackmusick.wondershot",
                    "wondershot",
                )
            };
            // Native macOS fullscreen animates into a new Space. A capture
            // overlay is an ordinary borderless window covering this display.
            #[cfg(target_os = "macos")]
            let attributes = {
                use winit::platform::macos::WindowAttributesExtMacOS;
                attributes.with_position(monitor.position()).with_inner_size(size)
                    .with_visible(false).with_has_shadow(false)
                    .with_accepts_first_mouse(true)
            };
            #[cfg(not(target_os = "macos"))]
            let attributes = attributes.with_fullscreen(Some(Fullscreen::Borderless(Some(monitor))));
            let Ok(window) = event_loop.create_window(attributes) else {
                continue;
            };
            #[cfg(target_os = "macos")]
            configure_macos_overlay(&window);
            window.set_cursor(CursorIcon::Crosshair);
            let window = Rc::new(window);
            if self.context.is_none() {
                self.context = Context::new(window.clone()).ok();
            }
            let Some(context) = self.context.as_ref() else {
                continue;
            };
            let Ok(surface) = Surface::new(context, window.clone()) else {
                continue;
            };
            let id = window.id();
            self.windows.insert(
                id,
                DisplayWindow {
                    window: window.clone(),
                    surface,
                    display,
                    dimmed: base.iter().copied().map(dim).collect(),
                    base,
                    width: size.width,
                    height: size.height,
                    cursor: (0, 0),
                    drag_start: None,
                    locked_region: None,
                    selected_window_id: None,
                    action_bar_cache: ActionBarCache::default(),
                    pressed_action: None,
                    cursor_icon: CursorIcon::Crosshair,
                },
            );
            window.request_redraw();
        }

        if self.windows.is_empty() {
            self.finish(event_loop, SelectionResult::Cancelled);
        }
    }

    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        window_id: WindowId,
        event: WindowEvent,
    ) {
        match event {
            WindowEvent::CloseRequested => self.finish(event_loop, SelectionResult::Cancelled),
            WindowEvent::ModifiersChanged(modifiers) => self.modifiers = modifiers.state(),
            WindowEvent::KeyboardInput { event, .. } if event.state == ElementState::Pressed => {
                match event.logical_key {
                    Key::Named(NamedKey::Escape) => {
                        self.finish(event_loop, SelectionResult::Cancelled)
                    }
                    Key::Named(NamedKey::Tab) if self.session.mode == SelectionMode::Window => {
                        if let Some(state) = self.windows.get_mut(&window_id) {
                            state.cycle_hover(if self.modifiers.shift_key() { -1 } else { 1 });
                            state.window.request_redraw();
                        }
                    }
                    Key::Named(NamedKey::Enter) if self.session.mode == SelectionMode::Window => {
                        if let Some(id) = self
                            .windows
                            .get(&window_id)
                            .and_then(|state| state.selected_window_id.clone())
                        {
                            self.finish(event_loop, SelectionResult::Window { window_id: id });
                        }
                    }
                    _ => {}
                }
            }
            WindowEvent::CursorMoved { position, .. } => {
                if let Some(state) = self.windows.get_mut(&window_id) {
                    state.cursor = (position.x.round() as i32, position.y.round() as i32);
                    state.sync_cursor();
                    if self.pending_result.is_none() && self.session.mode == SelectionMode::Window {
                        state.update_hover();
                    }
                    state.window.request_redraw();
                }
            }
            WindowEvent::MouseWheel { delta, .. } if self.session.mode == SelectionMode::Window => {
                let direction = match delta {
                    MouseScrollDelta::LineDelta(_, y) if y < 0.0 => 1,
                    MouseScrollDelta::PixelDelta(position) if position.y < 0.0 => 1,
                    _ => -1,
                };
                if let Some(state) = self.windows.get_mut(&window_id) {
                    state.cycle_hover(direction);
                    state.window.request_redraw();
                }
            }
            WindowEvent::MouseInput {
                state: ElementState::Pressed,
                button: MouseButton::Left,
                ..
            } => {
                if self.session.mode == SelectionMode::Region && self.pending_result.is_some() {
                    // Like a toolbar button, show the pressed glyph now and act on release.
                    if let Some(state) = self.windows.get_mut(&window_id) {
                        state.pressed_action = state.action_bar_hit();
                        state.window.request_redraw();
                    }
                    return;
                }
                if let Some(state) = self.windows.get_mut(&window_id) {
                    match self.session.mode {
                        SelectionMode::Region if self.pending_result.is_none() => {
                            state.locked_region = None;
                            state.drag_start = Some(state.cursor);
                        }
                        SelectionMode::Region => {}
                        SelectionMode::Window => {
                            if let Some(id) = state.selected_window_id.clone() {
                                self.finish(event_loop, SelectionResult::Window { window_id: id });
                            }
                        }
                    }
                    if let Some(state) = self.windows.get(&window_id) {
                        state.window.request_redraw();
                    }
                }
            }
            WindowEvent::MouseInput {
                state: ElementState::Released,
                button: MouseButton::Left,
                ..
            } if self.session.mode == SelectionMode::Region && self.pending_result.is_some() => {
                let Some(state) = self.windows.get_mut(&window_id) else { return };
                let pressed = state.pressed_action.take();
                state.window.request_redraw();
                // Releasing off the pressed button cancels the click, as in the webview.
                let hit = clicked_action(pressed, state.action_bar_hit());
                match hit {
                    Some(ActionBarHit::Capture) | Some(ActionBarHit::Record) => {
                        if let Some(SelectionResult::Region { action, .. }) =
                            self.pending_result.as_mut()
                        {
                            *action = if hit == Some(ActionBarHit::Record) {
                                SelectionAction::Record
                            } else {
                                SelectionAction::Capture
                            };
                        }
                        if let Some(result) = self.pending_result.take() {
                            self.finish(event_loop, result);
                        }
                    }
                    Some(ActionBarHit::Cancel) => {
                        self.finish(event_loop, SelectionResult::Cancelled);
                    }
                    None => {}
                }
            }
            WindowEvent::MouseInput {
                state: ElementState::Released,
                button: MouseButton::Left,
                ..
            } if self.session.mode == SelectionMode::Region => {
                let result = if let Some(state) = self.windows.get_mut(&window_id) {
                    let rect = state.drag_start.map(|start| {
                        normalized_drag(start, state.cursor, state.width, state.height)
                    });
                    if let Some(rect) = rect.filter(|rect| rect.width >= 2 && rect.height >= 2) {
                        state.locked_region = Some(rect);
                        state.drag_start = None;
                        state.sync_cursor();
                        let rect = state.view_to_source_rect(rect);
                        Some(SelectionResult::Region {
                            display_id: state.display.id.clone(),
                            x: rect.x as u32,
                            y: rect.y as u32,
                            width: rect.width,
                            height: rect.height,
                            action: SelectionAction::Capture,
                        })
                    } else {
                        state.window.request_redraw();
                        None
                    }
                } else {
                    None
                };
                if let Some(result) = result {
                    if self.session.action_bar {
                        self.pending_result = Some(result);
                        if let Some(state) = self.windows.get(&window_id) {
                            state.window.request_redraw();
                        }
                    } else {
                        self.finish(event_loop, result);
                    }
                }
            }
            WindowEvent::RedrawRequested => {
                if let Some(state) = self.windows.get_mut(&window_id) {
                    if state.redraw(self.session.mode).is_ok() && !self.first_frame {
                        eprintln!("first overlay frame {}ms after selector startup", self.started.elapsed().as_millis());
                        self.first_frame = true;
                    }
                    if !state.window.is_visible().unwrap_or(true) {
                        state.window.set_visible(true);
                        state.window.focus_window();
                    }
                }
            }
            _ => {}
        }
    }
}

fn scale_i32(value: i32, from: u32, to: u32) -> i32 {
    if from == 0 {
        return 0;
    }
    (f64::from(value) * f64::from(to) / f64::from(from)).round() as i32
}

fn scale_u32(value: u32, from: u32, to: u32) -> u32 {
    if from == 0 {
        return 0;
    }
    (f64::from(value) * f64::from(to) / f64::from(from)).round() as u32
}

#[cfg(target_os = "macos")]
fn configure_macos_overlay(window: &Window) {
    use objc2_app_kit::{NSView, NSWindowCollectionBehavior};
    use winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
    if let Ok(handle) = window.window_handle() {
        if let RawWindowHandle::AppKit(handle) = handle.as_raw() {
            // Winit owns this view for the lifetime of the window. This runs
            // on the AppKit event-loop thread before the window is shown.
            let view = unsafe { handle.ns_view.cast::<NSView>().as_ref() };
            if let Some(native) = view.window() {
                native.setLevel(25); // above menu bar, same as the native picker
                native.setCollectionBehavior(NSWindowCollectionBehavior::CanJoinAllSpaces
                    | NSWindowCollectionBehavior::FullScreenAuxiliary
                    | NSWindowCollectionBehavior::Stationary);
            }
        }
    }
}

pub fn run(session_path: impl AsRef<Path>) -> Result<SelectionResult, String> {
    let bytes = std::fs::read(session_path.as_ref()).map_err(|e| e.to_string())?;
    let session: SelectionSession = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    if session.displays.is_empty() {
        return Err("selection session has no frozen displays".into());
    }
    let icon = image::load_from_memory(include_bytes!("../../../src-tauri/icons/128x128.png"))
        .map_err(|error| format!("Wondershot selector icon: {error}"))?
        .to_rgba8();
    let icon = Icon::from_rgba(icon.as_raw().clone(), icon.width(), icon.height())
        .map_err(|error| format!("Wondershot selector icon: {error}"))?;
    let mut builder = EventLoop::builder();
    #[cfg(target_os = "macos")]
    {
        use winit::platform::macos::{ActivationPolicy, EventLoopBuilderExtMacOS};
        builder.with_activation_policy(ActivationPolicy::Accessory)
            .with_activate_ignoring_other_apps(false);
    }
    let event_loop = builder.build().map_err(|e| e.to_string())?;
    let mut app = SelectorApp::new(session, icon);
    event_loop.run_app(&mut app).map_err(|e| e.to_string())?;
    Ok(app.result.unwrap_or(SelectionResult::Cancelled))
}

fn dim(pixel: u32) -> u32 {
    let r = ((pixel >> 16) & 0xff) * 11 / 20;
    let g = ((pixel >> 8) & 0xff) * 11 / 20;
    let b = (pixel & 0xff) * 11 / 20;
    (r << 16) | (g << 8) | b
}

fn clamp_rect(rect: Rect, width: u32, height: u32) -> Rect {
    let left = rect.x.clamp(0, width as i32);
    let top = rect.y.clamp(0, height as i32);
    let right = rect
        .x
        .saturating_add_unsigned(rect.width)
        .clamp(left, width as i32);
    let bottom = rect
        .y
        .saturating_add_unsigned(rect.height)
        .clamp(top, height as i32);
    Rect {
        x: left,
        y: top,
        width: (right - left) as u32,
        height: (bottom - top) as u32,
    }
}

fn restore_rect(buffer: &mut [u32], base: &[u32], stride: u32, rect: Rect) {
    for y in rect.y as u32..rect.y as u32 + rect.height {
        let start = (y * stride + rect.x as u32) as usize;
        let end = start + rect.width as usize;
        buffer[start..end].copy_from_slice(&base[start..end]);
    }
}

fn draw_border(
    buffer: &mut [u32],
    width: u32,
    height: u32,
    rect: Rect,
    thickness: u32,
    color: u32,
) {
    for offset in 0..thickness {
        let left = (rect.x - offset as i32).clamp(0, width.saturating_sub(1) as i32);
        let top = (rect.y - offset as i32).clamp(0, height.saturating_sub(1) as i32);
        let right = (rect.x + rect.width as i32 - 1 + offset as i32)
            .clamp(0, width.saturating_sub(1) as i32);
        let bottom = (rect.y + rect.height as i32 - 1 + offset as i32)
            .clamp(0, height.saturating_sub(1) as i32);
        for x in left..=right {
            buffer[(top as u32 * width + x as u32) as usize] = color;
            buffer[(bottom as u32 * width + x as u32) as usize] = color;
        }
        for y in top..=bottom {
            buffer[(y as u32 * width + left as u32) as usize] = color;
            buffer[(y as u32 * width + right as u32) as usize] = color;
        }
    }
}

fn draw_crosshair(buffer: &mut [u32], width: u32, height: u32, x: i32, y: i32) {
    const COLOR: u32 = 0x00ffffff;
    if y >= 0 && y < height as i32 {
        for px in 0..width {
            if (px as i32 - x).unsigned_abs() > 8 {
                buffer[(y as u32 * width + px) as usize] = COLOR;
            }
        }
    }
    if x >= 0 && x < width as i32 {
        for py in 0..height {
            if (py as i32 - y).unsigned_abs() > 8 {
                buffer[(py * width + x as u32) as usize] = COLOR;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn display() -> FrozenDisplay {
        FrozenDisplay {
            id: "left".into(),
            frame_path: "/tmp/left.png".into(),
            x: -1920,
            y: 0,
            pixel_width: 1920,
            pixel_height: 1080,
            windows: vec![
                WindowTarget {
                    id: "front".into(),
                    title: "Front".into(),
                    application: "One".into(),
                    x: -800,
                    y: 100,
                    width: 500,
                    height: 500,
                    z_order: 0,
                    capturable: true,
                },
                WindowTarget {
                    id: "behind".into(),
                    title: "Behind".into(),
                    application: "Two".into(),
                    x: -1000,
                    y: 0,
                    width: 800,
                    height: 800,
                    z_order: 2,
                    capturable: true,
                },
            ],
        }
    }

    #[test]
    fn action_bar_has_equal_outer_gutters() {
        let bar = positioned_action_bar(Rect { x: 300, y: 200, width: 400, height: 200 }, 1280, 800);
        let camera_left = 7;
        let cancel_right = 231 + 44;
        assert_eq!(bar.width as i32 - cancel_right, camera_left);
    }

    #[test]
    fn retina_toolbar_scales_icons_and_hit_targets_together() {
        for scale in [1.0, 1.5, 2.0] {
            let bar = Rect { x: 20, y: 20, width: (282.0 * scale) as u32, height: (58.0 * scale) as u32 };
            let mut buffer = vec![0; 1000 * 200];
            let pixmap = action_bar::render_action_bar(bar.width, bar.height, scale as f32, ButtonStates::default(), None).unwrap();
            action_bar::composite(&mut buffer, 1000, 200, (bar.x, bar.y), &pixmap);
            // Buttons have no fill: the hit target's corner shows the bar surface.
            for (x, action) in [(10.0, ActionBarHit::Capture), (62.0, ActionBarHit::Record),
                (234.0, ActionBarHit::Cancel)] {
                let point = (bar.x + (x * scale) as i32, bar.y + (10.0 * scale) as i32);
                assert_eq!(action_bar_hit_at(bar, point, scale), Some(action));
                assert_eq!(buffer[point.1 as usize * 1000 + point.0 as usize], 0x000a0c0f);
            }
            // The record glyph is centred inside its hit target at every scale.
            let record_center = (bar.x + (81.0 * scale) as i32, bar.y + (29.0 * scale) as i32);
            assert_eq!(action_bar_hit_at(bar, record_center, scale), Some(ActionBarHit::Record));
            assert_eq!(buffer[record_center.1 as usize * 1000 + record_center.0 as usize], 0x00ff727a);
            assert_eq!(action_bar_hit_at(bar, (bar.x, bar.y), scale), None);
        }
    }

    #[test]
    fn cursor_is_pointer_over_buttons_and_crosshair_elsewhere() {
        assert_eq!(overlay_cursor(None), CursorIcon::Crosshair);
        for hit in [ActionBarHit::Capture, ActionBarHit::Record, ActionBarHit::Cancel] {
            assert_eq!(overlay_cursor(Some(hit)), CursorIcon::Pointer);
        }
        // Between buttons (size read-out) the bar is not clickable.
        let bar = Rect { x: 0, y: 0, width: 564, height: 116 };
        assert_eq!(overlay_cursor(action_bar_hit_at(bar, (2 * 160, 2 * 29), 2.0)), CursorIcon::Crosshair);
        assert_eq!(overlay_cursor(action_bar_hit_at(bar, (2 * 29, 2 * 29), 2.0)), CursorIcon::Pointer);
    }

    #[test]
    fn button_click_requires_release_over_pressed_button() {
        let capture = Some(ActionBarHit::Capture);
        assert_eq!(clicked_action(capture, capture), capture);
        assert_eq!(clicked_action(capture, None), None);
        assert_eq!(clicked_action(capture, Some(ActionBarHit::Cancel)), None);
        assert_eq!(clicked_action(None, capture), None);
    }

    #[test]
    fn reverse_drag_is_normalized_and_clamped() {
        assert_eq!(
            normalized_drag((2000, 1000), (-50, 100), 1920, 1080),
            Rect {
                x: 0,
                y: 100,
                width: 1920,
                height: 900,
            }
        );
    }

    #[test]
    fn action_bar_centers_on_selection_and_clamps_to_display() {
        let centered = positioned_action_bar(
            Rect { x: 400, y: 200, width: 600, height: 300 },
            1920,
            1080,
        );
        assert_eq!(centered.x, 559);
        assert_eq!(centered.y, 508);

        let left_edge = positioned_action_bar(
            Rect { x: 0, y: 100, width: 100, height: 100 },
            1920,
            1080,
        );
        assert_eq!(left_edge.x, 8);

        let bottom_edge = positioned_action_bar(
            Rect { x: 400, y: 1000, width: 600, height: 70 },
            1920,
            1080,
        );
        assert_eq!(bottom_edge.y, 934);
    }

    #[test]
    fn overlapping_windows_cycle_in_z_order() {
        let display = display();
        let point = (1200, 200);
        assert_eq!(cycle_window(&display, point, None, 1).unwrap().id, "front");
        assert_eq!(
            cycle_window(&display, point, Some("front"), 1).unwrap().id,
            "behind"
        );
        assert_eq!(
            cycle_window(&display, point, Some("behind"), 1).unwrap().id,
            "front"
        );
    }

    #[test]
    fn dim_preserves_channels_without_alpha_bits() {
        assert_eq!(dim(0x00ff8040), 0x008c4623);
    }

    #[test]
    fn view_coordinates_scale_to_frozen_retina_pixels() {
        assert_eq!(scale_i32(350, 1440, 2880), 700);
        assert_eq!(scale_u32(500, 1440, 2880), 1000);
        assert_eq!(scale_i32(-25, 1440, 2880), -50);
    }

    #[test]
    fn session_json_round_trips() {
        let session = SelectionSession {
            operation_id: "capture-1".into(),
            mode: SelectionMode::Region,
            displays: vec![display()],
            action_bar: false,
        };
        let json = serde_json::to_string(&session).unwrap();
        assert_eq!(
            serde_json::from_str::<SelectionSession>(&json).unwrap(),
            session
        );
    }
}
