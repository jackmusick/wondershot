pub mod spectacle;
pub mod kwin;
pub mod portal;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureMode {
    Region,
    Fullscreen,
    Window,
}
