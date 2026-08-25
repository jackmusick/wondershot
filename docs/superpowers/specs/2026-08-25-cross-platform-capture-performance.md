# Cross-platform capture performance

**Status:** implementation contract  
**Platforms:** Linux (Wayland/X11), Windows 11, macOS 14+

## Problem

The Tauri rewrite retained Linux's portal/Spectacle capture path but did not
replace the legacy Windows implementation and has no macOS implementation.
The shared completion path also does redundant work: a successful capture can
trigger two immediate library scans plus a watcher scan, editor images cross
IPC as base64, and every autosave serializes and rewrites a full-resolution
PNG on the webview thread.

Rust is not itself a performance guarantee. Wondershot must keep a resident
process, use each OS's GPU-backed capture API, keep selection feedback local,
and avoid encoding or scanning work on the interaction path.

## Latency budgets

All budgets are warm-process p95 values, measured from Wondershot's monotonic
instrumentation rather than wall-clock log timestamps.

| Interaction | Budget | Measurement boundary |
|---|---:|---|
| Hotkey to selector visible | 100 ms | native hotkey receipt to first overlay frame |
| Window hover response | 16.7 ms/frame; no frame over 33 ms | pointer event to highlighted frame |
| Selection commit to pixels acquired | 100 ms | pointer release/click to GPU frame available |
| Pixels acquired to library item available | 150 ms at 1080p, 300 ms at 4K | frame available to atomic file completion |
| Capture complete to preview usable | 300 ms at 1080p, 500 ms at 4K | selection commit to decoded editor image |
| Annotation input | no synchronous full-image encode | pointer/keyboard handlers must not call canvas export |

Cold launch and first OS permission prompts are reported separately and are
not mixed into warm-process percentiles.

## Platform architecture

### Shared selector model

- Every interactive capture begins by acquiring one immutable frame for each
  participating display. The selector renders those frozen frames; it never
  shows the live desktop underneath a transparent tint.
- Pointer hover, drag, resize, keyboard nudging, magnification, and dimension
  labels operate entirely on cached pixels and cached target geometry. They do
  not call a capture API, enumerate windows, or cross IPC during interaction.
- Selection commit crops the already-acquired frame. It does not perform a
  second desktop capture, so the selected pixels are exactly the pixels the
  user saw while selecting.
- A capture session owns its temporary frames and deletes them after commit or
  cancellation. Only the committed crop enters the library.
- Mixed-DPI conversion is resolved once when each frame is acquired. Overlay
  geometry remains in logical coordinates; crop rectangles are converted to
  physical pixels at the session boundary.

### Linux

- Preserve the XDG screenshot portal as the default because the compositor
  owns secure access to desktop pixels.
- Use the non-interactive Screenshot portal to acquire one immutable compositor
  frame, split its virtual-desktop image into per-monitor frames from Tauri's
  physical monitor geometry, and perform region selection in the shared native
  overlay. A persistent ScreenCast/PipeWire session is reserved for recording
  or for a future measured latency regression; still capture does not keep an
  unnecessary stream alive.
- Portable Wayland does not expose other clients' window bounds. Window snap
  targets therefore come from a compositor adapter where available (KWin and
  wlroots); desktops without one use the portal's compositor-owned window
  picker while retaining the same completion pipeline.
- Keep Spectacle as an explicit configured backend, not a probe performed for
  every capture.
- Keep the resident-process hotkey route; launching a new Flatpak process is a
  compatibility entry point, not the primary shortcut path.

### Windows

- Use Windows Graphics Capture with a D3D11 frame pool for monitor and HWND
  capture. Do not route pixels through `mss`, GDI `BitBlt`, Qt `QImage`, or a
  Python child process.
- Freeze one frame per monitor before showing the shared selector. The overlay
  displays those frames rather than the live desktop.
- Enumerate visible top-level windows once when selection starts. Cache HWND,
  title, process, and extended-frame bounds. Hit testing and highlight changes
  perform no capture and no enumeration.
- Window selection uses cached HWND bounds over the frozen frames. Commit crops
  the frozen monitor image for region mode and captures the selected HWND
  directly for window mode, preserving shadows and transparent borders.
- The selector is a resident transparent, per-monitor overlay and remains
  responsive at mixed DPI and negative virtual-desktop coordinates.

### macOS

- Use ScreenCaptureKit to freeze one frame per display before showing the
  shared selector. Region selection crops that immutable frame.
- Cache `SCWindow` frames before the overlay appears. Window hover uses those
  cached bounds; commit captures the chosen `SCWindow` directly so shadows and
  transparency are preserved.
- Cache window/display frames for hit testing. The overlay performs no capture
  and no shareable-content query while the pointer moves.
- Request Screen Recording permission before entering selection and provide a
  direct route to System Settings when denied.
- Use point/pixel conversion derived from the selected display so Retina and
  mixed-scale displays remain aligned.

## Shared completion architecture

1. A capture request returns one structured result containing path, media
   metadata, source, and stage timings.
2. The frontend inserts that item into its library store directly. It does not
   rescan the library after its own capture.
3. Capture events are reserved for captures initiated outside the current
   webview (CLI/global shortcut) and carry an operation ID. The store dedupes
   operation IDs and paths.
4. The directory watcher coalesces external changes and ignores paths already
   acknowledged by the capture coordinator.
5. The image server streams original files over loopback with an allow-list,
   correct MIME types, and CORS. Editor images no longer cross IPC as base64.
6. Annotation autosave writes the small sidecar only. An idle/background
   render updates the flattened preview; export/copy/navigation flushes it.
   The immutable editable base is written once, not on every annotation.
7. Capture-panel preferences are persisted only when changed. Watchers are
   rebound only when library directories change.

## Feature parity matrix

| Capability | Linux | Windows 11 | macOS 14+ | Acceptance evidence |
|---|---|---|---|---|
| Region capture | Screenshot portal frozen frames + overlay crop | WGC frozen frames + overlay crop | ScreenCaptureKit frozen frames + overlay crop | real two-monitor capture at both scale factors |
| Window capture | cached compositor adapter bounds; portal picker otherwise | cached HWND bounds + direct HWND commit | cached `SCWindow` bounds + direct `SCWindow` commit | hover follows 20 windows without capture calls |
| Fullscreen/display | Portal | direct monitor | direct `SCDisplay` | correct monitor and pixel dimensions |
| Smooth hover highlight | compositor-owned | cached bounds | cached bounds | pointer trace meets frame budget |
| Cursor inclusion | portal preference where supported | WGC session flag | stream/screenshot configuration | on/off pixel evidence |
| Delay | shared async timer | shared async timer | shared async timer | UI remains responsive during delay |
| Copy after capture | native clipboard | native clipboard | native clipboard | paste into native target |
| Preview preference | shared coordinator | shared coordinator | shared coordinator | disabled stays in gallery; enabled opens editor |
| Mixed-DPI coordinates | compositor-owned | per-monitor DPI aware | display point/pixel scale | selection edges within 1 physical pixel |
| Permission denial | portal result | OS capture result | actionable Screen Recording state | denial/recovery test |

## Instrumentation

Every request has an operation ID and emits one structured timing record with:

- `hotkey_received_ms`
- `selector_visible_ms`
- `selection_committed_ms`
- `frame_acquired_ms`
- `file_committed_ms`
- `frontend_inserted_ms`
- `preview_ready_ms`
- platform, mode, dimensions, output bytes, cold/warm, success/error

Raw paths, window titles, application names, and clipboard contents are never
included. Debug builds log records; release builds retain an in-memory rolling
window exposed by the diagnostics UI.

## Acceptance gates

- Unit tests cover capture-result dedupe, incremental library insertion,
  settings no-op behavior, coordinate conversion, and timing calculations.
- Component tests prove one direct capture causes no full library reload and
  preview/copy preferences are honored once.
- Linux is exercised through the portal on Wayland.
- Windows is exercised on the Windows 11 VM with two scale factors and a real
  WGC frame; fake-grab tests do not establish this gate.
- macOS is compiled in CI and exercised on macOS 14+ hardware. Compilation
  alone does not establish runtime or interaction performance.
- Measurements include at least 30 warm samples per mode and report p50, p95,
  max, dimensions, and hardware/display configuration.

## Non-goals

- Supporting the legacy Python/Qt capture path.
- Claiming cold permission prompts meet warm capture budgets.
- Keeping an alternate GDI/CGWindow fallback without an explicit product
  decision and its own tested contract.
- Rebuilding recording in this refactor; recording may reuse platform capture
  primitives later.
