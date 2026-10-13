use wondershot_core::capture::native::{MonitorRect, WindowRect};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PickerAction {
    Capture,
    Record,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PickerChoice {
    pub action: PickerAction,
    pub rect: (u32, u32, u32, u32),
    pub window_id: Option<isize>,
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
    window_id: Option<isize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PickerButtonAction {
    Capture,
    Record,
    Cancel,
}

#[derive(Debug, Clone)]
struct PickerModel {
    virtual_rect: PickerRect,
    monitors: Vec<PickerRect>,
    windows: Vec<PickerTarget>,
    drag_start: Option<(i32, i32)>,
    drag_now: Option<(i32, i32)>,
    hover: Option<PickerTarget>,
    selected: Option<PickerTarget>,
}

impl PickerModel {
    fn new(virtual_rect: PickerRect, monitors: Vec<MonitorRect>, windows: Vec<WindowRect>) -> Self {
        Self {
            virtual_rect: PickerRect { x: 0, y: 0, ..virtual_rect },
            monitors: monitors
                .into_iter()
                .map(|m| PickerRect {
                    x: m.x - virtual_rect.x,
                    y: m.y - virtual_rect.y,
                    width: m.width,
                    height: m.height,
                })
                .collect(),
            windows: windows
                .into_iter()
                .map(|w| PickerTarget {
                    rect: PickerRect {
                        x: w.x - virtual_rect.x,
                        y: w.y - virtual_rect.y,
                        width: w.width,
                        height: w.height,
                    },
                    window_id: Some(w.hwnd),
                })
                .collect(),
            drag_start: None,
            drag_now: None,
            hover: None,
            selected: None,
        }
    }

    fn action_screen(&self, selected: PickerRect) -> PickerRect {
        // Place controls on the display containing most of the selection,
        // rather than in the empty area of a multi-display bounding box.
        self.monitors.iter().copied().max_by_key(|m| {
            let w = (m.x + m.width as i32).min(selected.x + selected.width as i32)
                - m.x.max(selected.x);
            let h = (m.y + m.height as i32).min(selected.y + selected.height as i32)
                - m.y.max(selected.y);
            i64::from(w.max(0)) * i64::from(h.max(0))
        }).unwrap_or(self.virtual_rect)
    }

    fn begin_drag(&mut self, p: (i32, i32)) {
        self.selected = None;
        self.drag_start = Some(p);
        self.drag_now = Some(p);
    }

    fn update_drag(&mut self, p: (i32, i32)) {
        self.drag_now = Some(p);
    }

    fn finish_drag(&mut self, p: (i32, i32)) {
        self.drag_now = Some(p);
        self.selected = self.selection_target().or(self.hover);
        self.drag_start = None;
        self.drag_now = None;
        self.hover = None;
    }

    fn update_hover(&mut self, p: (i32, i32)) {
        self.hover = self.target_at(p);
    }

    fn active_target(&self) -> Option<PickerTarget> {
        self.selected
            .or_else(|| self.selection_target())
            .or(self.hover)
    }

    fn selection_target(&self) -> Option<PickerTarget> {
        let (Some(a), Some(b)) = (self.drag_start, self.drag_now) else {
            return None;
        };
        let x = a.0.min(b.0);
        let y = a.1.min(b.1);
        let width = a.0.abs_diff(b.0);
        let height = a.1.abs_diff(b.1);
        (width >= 4 && height >= 4).then_some(PickerTarget {
            rect: PickerRect {
                x,
                y,
                width,
                height,
            },
            window_id: None,
        })
    }

    fn target_at(&self, p: (i32, i32)) -> Option<PickerTarget> {
        self.edge_fullscreen_hover(p)
            .or_else(|| self.window_at(p))
            .or_else(|| {
                self.monitor_at(p).map(|rect| PickerTarget {
                    rect,
                    window_id: None,
                })
            })
    }

    fn window_at(&self, p: (i32, i32)) -> Option<PickerTarget> {
        self.windows.iter().copied().find(|target| {
            let r = target.rect;
            p.0 >= r.x && p.0 <= r.x + r.width as i32 && p.1 >= r.y && p.1 <= r.y + r.height as i32
        })
    }

    fn monitor_at(&self, p: (i32, i32)) -> Option<PickerRect> {
        self.monitors.iter().copied().find(|r| {
            p.0 >= r.x && p.0 <= r.x + r.width as i32 && p.1 >= r.y && p.1 <= r.y + r.height as i32
        })
    }

    fn edge_fullscreen_hover(&self, p: (i32, i32)) -> Option<PickerTarget> {
        let edge = 10;
        let r = self.monitor_at(p).unwrap_or(self.virtual_rect);
        let right = r.x + r.width as i32;
        let bottom = r.y + r.height as i32;
        (p.0 <= r.x + edge || p.1 <= r.y + edge || p.0 >= right - edge || p.1 >= bottom - edge)
            .then_some(PickerTarget {
                rect: r,
                window_id: None,
            })
    }
}

fn action_bar_rect(screen: PickerRect, selected: PickerRect) -> PickerRect {
    let width = 296.min((screen.width as i32 - 28).max(120));
    let height = 58;
    let margin = 14;
    let mut left = selected.x + (selected.width as i32 - width) / 2;
    left = left
        .max(screen.x + margin)
        .min(screen.x + screen.width as i32 - width - margin);
    let below = selected.y + selected.height as i32 + margin;
    let top = if below + height <= screen.y + screen.height as i32 - margin {
        below
    } else {
        (selected.y - height - margin).max(screen.y + margin)
    };
    PickerRect {
        x: left,
        y: top,
        width: width.max(1) as u32,
        height: height as u32,
    }
}

fn action_buttons(
    screen: PickerRect,
    selected: PickerRect,
) -> Vec<(PickerRect, PickerButtonAction)> {
    let bar = action_bar_rect(screen, selected);
    let top = bar.y + 8;
    let mut left = bar.x + 8;
    let specs = [
        (82, PickerButtonAction::Capture),
        (76, PickerButtonAction::Record),
        (82, PickerButtonAction::Cancel),
    ];
    specs
        .into_iter()
        .map(|(width, action)| {
            let rect = PickerRect {
                x: left,
                y: top,
                width,
                height: 38,
            };
            left += width as i32 + 8;
            (rect, action)
        })
        .collect()
}

fn contains(rect: PickerRect, p: (i32, i32)) -> bool {
    p.0 >= rect.x
        && p.0 <= rect.x + rect.width as i32
        && p.1 >= rect.y
        && p.1 <= rect.y + rect.height as i32
}

fn appkit_event_to_model_point(
    offset: (i32, i32),
    view_size: (u32, u32),
    window_point: (f64, f64),
) -> (i32, i32) {
    (
        offset.0 + window_point.0.round() as i32,
        offset.1 + (view_size.1 as f64 - window_point.1).round() as i32,
    )
}

fn action_at(
    screen: PickerRect,
    selected: PickerRect,
    p: (i32, i32),
) -> Option<PickerButtonAction> {
    action_buttons(screen, selected)
        .into_iter()
        .find(|(rect, _)| contains(*rect, p))
        .map(|(_, action)| action)
}

#[cfg(target_os = "macos")]
mod appkit {
    use super::*;
    use objc2::rc::Retained;
    use objc2::{define_class, msg_send, DefinedClass, MainThreadOnly};
    use objc2_app_kit::{
        NSBackingStoreType, NSBezierPath, NSColor, NSCursor, NSEvent, NSPanel, NSView,
        NSWindowCollectionBehavior, NSWindowStyleMask,
    };
    use objc2_foundation::{MainThreadMarker, NSObjectProtocol, NSPoint, NSRect, NSSize};
    use std::cell::RefCell;
    use std::sync::mpsc;

    thread_local! {
        // Own each session on AppKit's thread; release it after the final event.
        static SESSION: RefCell<Option<Box<PickerRuntime>>> = const { RefCell::new(None) };
    }

    struct PickerRuntime {
        model: RefCell<PickerModel>,
        done_tx: RefCell<Option<mpsc::Sender<Option<PickerChoice>>>>,
        windows: RefCell<Vec<Retained<NSPanel>>>,
    }

    struct PickerViewIvars {
        runtime: *mut PickerRuntime,
        offset_x: i32,
        offset_y: i32,
    }

    define_class!(
        #[unsafe(super = NSView)]
        #[thread_kind = MainThreadOnly]
        #[ivars = PickerViewIvars]
        struct WondershotMacPickerView;

        unsafe impl NSObjectProtocol for WondershotMacPickerView {}

        impl WondershotMacPickerView {
            #[unsafe(method(acceptsFirstResponder))]
            fn accepts_first_responder(&self) -> bool {
                true
            }

            #[unsafe(method(isFlipped))]
            fn is_flipped(&self) -> bool {
                true
            }

            #[unsafe(method(mouseDown:))]
            fn mouse_down(&self, event: &NSEvent) {
                let p = self.event_point(event);
                self.update_cursor(p);
                if let Some(action) = self.hit_action_bar(p) {
                    self.complete_action(action);
                    return;
                }
                self.runtime().model.borrow_mut().begin_drag(p);
                self.runtime().redraw();
            }

            #[unsafe(method(mouseDragged:))]
            fn mouse_dragged(&self, event: &NSEvent) {
                let p = self.event_point(event);
                self.update_cursor(p);
                self.runtime().model.borrow_mut().update_drag(p);
                self.runtime().redraw();
            }

            #[unsafe(method(mouseMoved:))]
            fn mouse_moved(&self, event: &NSEvent) {
                let p = self.event_point(event);
                self.update_cursor(p);
                self.runtime().model.borrow_mut().update_hover(p);
                self.runtime().redraw();
            }

            #[unsafe(method(mouseUp:))]
            fn mouse_up(&self, event: &NSEvent) {
                let p = self.event_point(event);
                self.update_cursor(p);
                {
                    let runtime = self.runtime();
                    runtime.model.borrow_mut().finish_drag(p);
                    let selected = runtime.model.borrow().selected;
                    if let Some(selected) = selected {
                        let _ = selected;
                    }
                }
                self.runtime().redraw();
            }

            #[unsafe(method(keyDown:))]
            fn key_down(&self, event: &NSEvent) {
                if event.keyCode() == 53 {
                    self.runtime().complete(None);
                }
            }

            #[unsafe(method(cancelOperation:))]
            fn cancel_operation(&self, _sender: Option<&objc2::runtime::AnyObject>) {
                self.runtime().complete(None);
            }

            #[unsafe(method(drawRect:))]
            fn draw_rect(&self, _dirty: NSRect) {
                let runtime = self.runtime();
                let model = runtime.model.borrow();
                let bounds = self.bounds();

                NSColor::colorWithSRGBRed_green_blue_alpha(0.0, 0.0, 0.0, 0.54).setFill();
                NSBezierPath::fillRect(bounds);

                let Some(target) = model.active_target() else {
                    return;
                };
                let rect = self.local_rect(target.rect);
                NSColor::colorWithSRGBRed_green_blue_alpha(0.20, 0.56, 1.0, 0.18).setFill();
                NSBezierPath::fillRect(rect);
                let path = NSBezierPath::bezierPathWithRoundedRect_xRadius_yRadius(rect, 2.0, 2.0);
                path.setLineWidth(2.0);
                NSColor::colorWithSRGBRed_green_blue_alpha(0.30, 0.72, 1.0, 1.0).setStroke();
                path.stroke();
                if let Some(selected) = model.selected {
                    self.draw_action_bar(model.action_screen(selected.rect), selected.rect);
                }
            }
        }
    );

    impl WondershotMacPickerView {
        fn new(
            mtm: MainThreadMarker,
            frame: NSRect,
            runtime: *mut PickerRuntime,
            offset_x: i32,
            offset_y: i32,
        ) -> Retained<Self> {
            let this = Self::alloc(mtm).set_ivars(PickerViewIvars {
                runtime,
                offset_x,
                offset_y,
            });
            unsafe { msg_send![super(this), initWithFrame: frame] }
        }

        fn runtime(&self) -> &PickerRuntime {
            unsafe { &*self.ivars().runtime }
        }

        fn event_point(&self, event: &NSEvent) -> (i32, i32) {
            let p = event.locationInWindow();
            let bounds = self.bounds();
            appkit_event_to_model_point(
                (self.ivars().offset_x, self.ivars().offset_y),
                (
                    bounds.size.width.round() as u32,
                    bounds.size.height.round() as u32,
                ),
                (p.x, p.y),
            )
        }

        fn local_rect(&self, r: PickerRect) -> NSRect {
            NSRect::new(
                NSPoint::new(
                    (r.x - self.ivars().offset_x) as f64,
                    (r.y - self.ivars().offset_y) as f64,
                ),
                NSSize::new(r.width as f64, r.height as f64),
            )
        }

        fn hit_action_bar(&self, p: (i32, i32)) -> Option<PickerButtonAction> {
            let runtime = self.runtime();
            let model = runtime.model.borrow();
            let selected = model.selected?.rect;
            action_at(model.action_screen(selected), selected, p)
        }

        fn update_cursor(&self, p: (i32, i32)) {
            if self.hit_action_bar(p).is_some() {
                NSCursor::pointingHandCursor().set();
            } else {
                NSCursor::crosshairCursor().set();
            }
        }

        fn complete_action(&self, action: PickerButtonAction) {
            let runtime = self.runtime();
            let Some(selected) = runtime.model.borrow().selected else {
                return;
            };
            match action {
                PickerButtonAction::Capture => runtime.complete(Some(PickerChoice {
                    action: PickerAction::Capture,
                    rect: choice_rect(selected.rect),
                    window_id: selected.window_id,
                })),
                PickerButtonAction::Record => runtime.complete(Some(PickerChoice {
                    action: PickerAction::Record,
                    rect: choice_rect(selected.rect),
                    window_id: selected.window_id,
                })),
                PickerButtonAction::Cancel => runtime.complete(None),
            }
        }

        fn draw_action_bar(&self, screen: PickerRect, selected: PickerRect) {
            let bar = self.local_rect(action_bar_rect(screen, selected));
            NSColor::colorWithSRGBRed_green_blue_alpha(0.08, 0.08, 0.09, 0.96).setFill();
            let bg = NSBezierPath::bezierPathWithRoundedRect_xRadius_yRadius(bar, 8.0, 8.0);
            bg.fill();
            for (rect, action) in action_buttons(screen, selected) {
                let color = match action {
                    PickerButtonAction::Capture => (0.15, 0.46, 0.96),
                    PickerButtonAction::Record => (0.82, 0.20, 0.20),
                    PickerButtonAction::Cancel => (0.22, 0.22, 0.24),
                };
                NSColor::colorWithSRGBRed_green_blue_alpha(color.0, color.1, color.2, 1.0)
                    .setFill();
                let path = NSBezierPath::bezierPathWithRoundedRect_xRadius_yRadius(
                    self.local_rect(rect),
                    6.0,
                    6.0,
                );
                path.fill();
                self.draw_button_icon(rect, action);
            }
        }

        fn draw_button_icon(&self, rect: PickerRect, action: PickerButtonAction) {
            let local = self.local_rect(rect);
            NSColor::whiteColor().setStroke();
            NSColor::whiteColor().setFill();
            match action {
                PickerButtonAction::Capture => {
                    let body = NSRect::new(
                        NSPoint::new(local.origin.x + 29.0, local.origin.y + 13.0),
                        NSSize::new(24.0, 16.0),
                    );
                    let lens = NSRect::new(
                        NSPoint::new(local.origin.x + 36.0, local.origin.y + 16.0),
                        NSSize::new(10.0, 10.0),
                    );
                    let body_path =
                        NSBezierPath::bezierPathWithRoundedRect_xRadius_yRadius(body, 3.0, 3.0);
                    body_path.setLineWidth(2.0);
                    body_path.stroke();
                    NSBezierPath::bezierPathWithOvalInRect(lens).fill();
                }
                PickerButtonAction::Record => {
                    let dot = NSRect::new(
                        NSPoint::new(local.origin.x + 30.0, local.origin.y + 11.0),
                        NSSize::new(16.0, 16.0),
                    );
                    NSBezierPath::bezierPathWithOvalInRect(dot).fill();
                }
                PickerButtonAction::Cancel => {
                    let x1 = local.origin.x + 34.0;
                    let x2 = local.origin.x + local.size.width - 34.0;
                    let y1 = local.origin.y + 13.0;
                    let y2 = local.origin.y + local.size.height - 13.0;
                    NSBezierPath::strokeLineFromPoint_toPoint(
                        NSPoint::new(x1, y1),
                        NSPoint::new(x2, y2),
                    );
                    NSBezierPath::strokeLineFromPoint_toPoint(
                        NSPoint::new(x2, y1),
                        NSPoint::new(x1, y2),
                    );
                }
            }
        }
    }

    impl PickerRuntime {
        fn redraw(&self) {
            for window in self.windows.borrow().iter() {
                if let Some(view) = window.contentView() {
                    view.setNeedsDisplay(true);
                }
            }
        }

        fn complete(&self, choice: Option<PickerChoice>) {
            for window in self.windows.borrow().iter() {
                window.orderOut(None);
            }
            if let Some(tx) = self.done_tx.borrow_mut().take() {
                let _ = tx.send(choice);
            }
        }
    }

    pub fn pick_action() -> Result<Option<PickerChoice>, String> {
        // A second hotkey must not replace the owner of the views' raw pointers.
        static PICKING: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _exclusive = PICKING.try_lock().map_err(|_| "capture picker is already open")?;
        let monitors = wondershot_core::capture::native::monitor_rects();
        if monitors.is_empty() { return Err("no active displays found".into()); }
        let windows = wondershot_core::capture::native::window_rects();
        let (x, y, width, height) = wondershot_core::capture::native::virtual_bounds();
        let virtual_rect = PickerRect {
            x,
            y,
            width,
            height,
        };
        let model = PickerModel::new(virtual_rect, monitors.clone(), windows);
        let (tx, rx) = mpsc::channel();
        dispatch2::run_on_main(move |mtm| {
            start_picker(mtm, model, monitors, virtual_rect, tx);
        });
        let choice = rx.recv().map_err(|e| e.to_string());
        dispatch2::run_on_main(|_| {
            SESSION.with(|session| {
                if let Some(runtime) = session.borrow_mut().take() {
                    for window in runtime.windows.borrow().iter() {
                        window.orderOut(None);
                        window.setContentView(None);
                        window.close();
                    }
                }
            });
        });
        choice
    }

    fn start_picker(
        mtm: MainThreadMarker,
        model: PickerModel,
        monitors: Vec<MonitorRect>,
        virtual_rect: PickerRect,
        tx: mpsc::Sender<Option<PickerChoice>>,
    ) {
        let mut runtime = Box::new(PickerRuntime {
            model: RefCell::new(model),
            done_tx: RefCell::new(Some(tx)),
            windows: RefCell::new(Vec::new()),
        });
        let runtime_ptr = runtime.as_mut() as *mut PickerRuntime;

        let main_height = monitors.iter().find(|m| m.x == 0 && m.y == 0)
            .map(|m| m.height).unwrap_or(virtual_rect.height);
        for monitor in monitors {
            let frame = NSRect::new(
                NSPoint::new(monitor.x as f64, main_height as f64 - monitor.y as f64 - monitor.height as f64),
                NSSize::new(monitor.width as f64, monitor.height as f64),
            );
            let window = NSPanel::initWithContentRect_styleMask_backing_defer(
                NSPanel::alloc(mtm),
                frame,
                NSWindowStyleMask::Borderless | NSWindowStyleMask::NonactivatingPanel,
                NSBackingStoreType::Buffered,
                false,
            );
            unsafe { window.setReleasedWhenClosed(false) };
            window.setOpaque(false);
            window.setBackgroundColor(Some(&NSColor::clearColor()));
            window.setLevel(25);
            window.setCollectionBehavior(
                NSWindowCollectionBehavior::CanJoinAllSpaces
                    | NSWindowCollectionBehavior::FullScreenAuxiliary,
            );
            window.setIgnoresMouseEvents(false);
            window.setAcceptsMouseMovedEvents(true);
            let view = WondershotMacPickerView::new(
                mtm,
                NSRect::new(
                    NSPoint::new(0.0, 0.0),
                    NSSize::new(monitor.width as f64, monitor.height as f64),
                ),
                runtime_ptr,
                monitor.x - virtual_rect.x,
                monitor.y - virtual_rect.y,
            );
            window.setContentView(Some(&view));
            window.setInitialFirstResponder(Some(&view));
            window.makeKeyAndOrderFront(None);
            window.makeFirstResponder(Some(&view));
            runtime.windows.borrow_mut().push(window);
        }

        SESSION.with(|session| *session.borrow_mut() = Some(runtime));
    }
}

#[cfg(target_os = "macos")]
pub use appkit::pick_action;

#[cfg(not(target_os = "macos"))]
pub fn pick_action() -> Result<Option<PickerChoice>, String> {
    Err("macOS native picker is not available on this platform".into())
}

fn choice_rect(rect: PickerRect) -> (u32, u32, u32, u32) {
    (
        rect.x.max(0) as u32,
        rect.y.max(0) as u32,
        rect.width,
        rect.height,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn model() -> PickerModel {
        PickerModel::new(
            PickerRect {
                x: -100,
                y: 0,
                width: 2020,
                height: 1080,
            },
            vec![
                MonitorRect {
                    x: -100,
                    y: 0,
                    width: 100,
                    height: 100,
                },
                MonitorRect {
                    x: 0,
                    y: 0,
                    width: 1920,
                    height: 1080,
                },
            ],
            vec![WindowRect {
                hwnd: 42,
                title: "Notes".into(),
                x: 50,
                y: 80,
                width: 400,
                height: 300,
            }],
        )
    }

    #[test]
    fn hover_prefers_window_before_monitor() {
        let mut model = model();
        model.update_hover((160, 120));
        let target = model.active_target().unwrap();
        assert_eq!(target.window_id, Some(42));
        assert_eq!(
            target.rect,
            PickerRect {
                x: 150,
                y: 80,
                width: 400,
                height: 300
            }
        );
    }

    #[test]
    fn edge_hover_selects_current_monitor_for_fullscreen() {
        let mut model = model();
        model.update_hover((1918, 5));
        let target = model.active_target().unwrap();
        assert_eq!(target.window_id, None);
        assert_eq!(target.rect.width, 1920);
        assert_eq!(target.rect.height, 1080);
    }

    #[test]
    fn drag_selection_overrides_hover() {
        let mut model = model();
        model.update_hover((160, 120));
        model.begin_drag((10, 20));
        model.update_drag((110, 70));
        let target = model.active_target().unwrap();
        assert_eq!(target.window_id, None);
        assert_eq!(
            target.rect,
            PickerRect {
                x: 10,
                y: 20,
                width: 100,
                height: 50
            }
        );
    }

    #[test]
    fn action_bar_stays_inside_virtual_screen() {
        let bar = action_bar_rect(
            PickerRect {
                x: 0,
                y: 0,
                width: 300,
                height: 200,
            },
            PickerRect {
                x: 240,
                y: 170,
                width: 50,
                height: 20,
            },
        );
        assert!(bar.x >= 0);
        assert!(bar.y < 170);
        assert!(bar.x + bar.width as i32 <= 300);
    }

    #[test]
    fn toolbar_uses_normalized_display_bounds_when_primary_has_left_neighbor() {
        let model = model();
        assert_eq!(model.virtual_rect.x, 0);
        let selection = PickerRect { x: 1900, y: 900, width: 100, height: 100 };
        let screen = model.action_screen(selection);
        assert_eq!(screen.x, 100);
        let bar = action_bar_rect(screen, selection);
        assert!(bar.x >= screen.x);
        assert!(bar.x + bar.width as i32 <= screen.x + screen.width as i32);
        assert!(bar.y + bar.height as i32 <= screen.y + screen.height as i32);
    }

    #[test]
    fn appkit_event_y_is_converted_to_top_left_model_space() {
        assert_eq!(
            appkit_event_to_model_point((10, 20), (400, 300), (25.0, 290.0)),
            (35, 30)
        );
        assert_eq!(
            appkit_event_to_model_point((10, 20), (400, 300), (25.0, 10.0)),
            (35, 310)
        );
    }

    #[test]
    fn action_buttons_can_be_hit_in_model_space() {
        let screen = PickerRect {
            x: 0,
            y: 0,
            width: 800,
            height: 600,
        };
        let selected = PickerRect {
            x: 200,
            y: 200,
            width: 240,
            height: 120,
        };
        let buttons = action_buttons(screen, selected);

        assert_eq!(
            action_at(screen, selected, (buttons[0].0.x + 10, buttons[0].0.y + 10)),
            Some(PickerButtonAction::Capture)
        );
        assert_eq!(
            action_at(screen, selected, (buttons[1].0.x + 10, buttons[1].0.y + 10)),
            Some(PickerButtonAction::Record)
        );
        assert_eq!(
            action_at(screen, selected, (buttons[2].0.x + 10, buttons[2].0.y + 10)),
            Some(PickerButtonAction::Cancel)
        );
    }

    #[test]
    fn macos_action_bar_exposes_capture_record_and_cancel() {
        let buttons = action_buttons(
            PickerRect {
                x: 0,
                y: 0,
                width: 800,
                height: 600,
            },
            PickerRect {
                x: 100,
                y: 100,
                width: 200,
                height: 100,
            },
        );
        let actions: Vec<_> = buttons.into_iter().map(|(_, action)| action).collect();
        assert_eq!(
            actions,
            vec![
                PickerButtonAction::Capture,
                PickerButtonAction::Record,
                PickerButtonAction::Cancel
            ]
        );
    }
}
