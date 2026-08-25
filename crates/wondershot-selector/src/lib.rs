use std::collections::HashMap;
use std::num::NonZeroU32;
use std::path::Path;
use std::rc::Rc;

use serde::{Deserialize, Serialize};
use softbuffer::{Context, Surface};
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, EventLoop};
use winit::keyboard::{Key, NamedKey};
use winit::window::{CursorIcon, Fullscreen, Window, WindowAttributes, WindowId, WindowLevel};

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
    },
    Window {
        window_id: String,
    },
    Cancelled,
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
    width: u32,
    height: u32,
    cursor: (i32, i32),
    drag_start: Option<(i32, i32)>,
    selected_window_id: Option<String>,
}

impl DisplayWindow {
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
            SelectionMode::Region => self
                .drag_start
                .map(|start| normalized_drag(start, self.cursor, self.width, self.height)),
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
        self.surface
            .resize(width, height)
            .map_err(|e| e.to_string())?;
        let mut buffer = self.surface.buffer_mut().map_err(|e| e.to_string())?;
        if buffer.len() != self.base.len() {
            return Err("selector surface size does not match frozen frame".into());
        }

        for (out, source) in buffer.iter_mut().zip(&self.base) {
            *out = dim(*source);
        }

        if let Some(rect) = selection_rect {
            let rect = clamp_rect(rect, self.width, self.height);
            restore_rect(&mut buffer, &self.base, self.width, rect);
            draw_border(&mut buffer, self.width, self.height, rect, 3, 0x0028c7fa);
        }

        if mode == SelectionMode::Region {
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
    context: Option<Context<Rc<Window>>>,
    windows: HashMap<WindowId, DisplayWindow>,
    result: Option<SelectionResult>,
    modifiers: winit::keyboard::ModifiersState,
}

impl SelectorApp {
    fn new(session: SelectionSession) -> Self {
        Self {
            session,
            context: None,
            windows: HashMap::new(),
            result: None,
            modifiers: winit::keyboard::ModifiersState::empty(),
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
            let base = image
                .pixels()
                .map(|pixel| {
                    let [r, g, b, _] = pixel.0;
                    ((r as u32) << 16) | ((g as u32) << 8) | b as u32
                })
                .collect();

            let attributes = WindowAttributes::default()
                .with_title("Wondershot selector")
                .with_decorations(false)
                .with_resizable(false)
                .with_window_level(WindowLevel::AlwaysOnTop)
                .with_fullscreen(Some(Fullscreen::Borderless(Some(monitor))));
            let Ok(window) = event_loop.create_window(attributes) else {
                continue;
            };
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
                    base,
                    width: size.width,
                    height: size.height,
                    cursor: (0, 0),
                    drag_start: None,
                    selected_window_id: None,
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
                    if self.session.mode == SelectionMode::Window {
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
                if let Some(state) = self.windows.get_mut(&window_id) {
                    match self.session.mode {
                        SelectionMode::Region => state.drag_start = Some(state.cursor),
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
            } if self.session.mode == SelectionMode::Region => {
                let result = if let Some(state) = self.windows.get_mut(&window_id) {
                    let rect = state.drag_start.take().map(|start| {
                        normalized_drag(start, state.cursor, state.width, state.height)
                    });
                    if let Some(rect) = rect.filter(|rect| rect.width >= 2 && rect.height >= 2) {
                        let rect = state.view_to_source_rect(rect);
                        Some(SelectionResult::Region {
                            display_id: state.display.id.clone(),
                            x: rect.x as u32,
                            y: rect.y as u32,
                            width: rect.width,
                            height: rect.height,
                        })
                    } else {
                        state.window.request_redraw();
                        None
                    }
                } else {
                    None
                };
                if let Some(result) = result {
                    self.finish(event_loop, result);
                }
            }
            WindowEvent::RedrawRequested => {
                if let Some(state) = self.windows.get_mut(&window_id) {
                    let _ = state.redraw(self.session.mode);
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

pub fn run(session_path: impl AsRef<Path>) -> Result<SelectionResult, String> {
    let bytes = std::fs::read(session_path.as_ref()).map_err(|e| e.to_string())?;
    let session: SelectionSession = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    if session.displays.is_empty() {
        return Err("selection session has no frozen displays".into());
    }
    let event_loop = EventLoop::new().map_err(|e| e.to_string())?;
    let mut app = SelectorApp::new(session);
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
        };
        let json = serde_json::to_string(&session).unwrap();
        assert_eq!(
            serde_json::from_str::<SelectionSession>(&json).unwrap(),
            session
        );
    }
}
