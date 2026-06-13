# Platform Support

This file is the source of truth for platform-specific Wondershot behavior.
The goal is to make OS differences intentional, reviewable, and easy to keep
in sync as Windows, Linux, and macOS converge.

## Status Legend

- `Implemented`: expected to work in normal use.
- `Fallback`: works through an external/system picker or reduced path.
- `Planned`: desired behavior, not implemented yet.
- `Intentional omission`: deliberately not offered on that platform.
- `Needs review`: behavior exists but the product decision is not settled.

## Rules

- Shared UI should ask backend capability APIs what is available instead of
  branching on OS names wherever possible.
- OS-specific behavior should live in platform modules, such as
  `capture/win.rs`, `capture/macos.rs`, `record/recorder_win.rs`, and related
  native bridge files.
- Any visible UI difference between platforms must have a row in this document.
- If a fallback is kept for one platform, note whether it is temporary or an
  intentional product choice.

## Feature Matrix

| Feature | Windows | Linux | macOS | Notes / Decision |
| --- | --- | --- | --- | --- |
| Main app shell | Implemented | Implemented | Planned | Tauri/Svelte is the shared shell. |
| Capture entry button | Implemented | Fallback / needs review | Planned | Windows opens the unified native selector. Linux currently keeps the mini `/capture` window path, which delegates to Spectacle/portal behavior. Removing it should be a deliberate decision, not incidental cleanup. |
| Capture action bar | Implemented | Fallback | Planned | Windows uses a Svelte action bar after selecting a monitor/window/region. Linux gets the Spectacle action flow when Spectacle is available, mostly validated on Fedora/KDE; non-KDE behavior needs review. |
| Region screenshot | Implemented | Fallback | Planned | Windows uses native Rust overlay. Linux uses Spectacle when available, then portal fallback. macOS should use native capture APIs. |
| Window screenshot | Implemented | Fallback | Planned | Windows hover-selects windows and attempts native window capture. Linux relies on Spectacle/portal. macOS needs native window enumeration/capture. |
| Fullscreen screenshot | Implemented | Fallback | Planned | Windows selects one monitor, including desktop/edge hover. Linux uses Spectacle/portal. |
| Multi-monitor targeting | Implemented | Fallback | Planned | Windows selector works per monitor. Linux behavior depends on Spectacle/portal. |
| Region recording | Implemented | Fallback / needs review | Planned | Windows records the selected rect from the unified selector. Linux recording currently goes through the Linux recording path and should be reviewed for region parity. |
| Window recording | Implemented | Fallback / needs review | Planned | Windows records the selected window bounds as a region. It does not follow the window if it moves after recording starts, which is acceptable for current parity. |
| Fullscreen recording | Implemented | Implemented | Planned | Windows uses FFmpeg gdigrab. Linux uses the GStreamer/portal path. |
| Pause/resume recording | Implemented | Implemented | Planned | Windows sends FFmpeg pause/resume input. Linux uses the GStreamer pause probe. |
| Microphone recording | Implemented | Implemented | Planned | Windows uses DirectShow device resolution. Linux uses GStreamer/Pulse/PipeWire resolution. |
| System audio recording | Planned | Planned | Planned | Windows should use WASAPI loopback. Linux should use Pulse/PipeWire monitor sources. macOS likely needs ScreenCaptureKit system audio or a documented virtual-device fallback. |
| Camera bubble | Implemented | Implemented | Planned | Windows uses native FFmpeg camera streaming. Linux uses the existing native camera path. macOS camera module is a stub. |
| Browser media fallback | Implemented | Implemented | Implemented / fallback | Kept as a fallback, but native capture/recording should be preferred in the desktop app to avoid permission popups and browser-feeling UX. |
| Capture/record crash logging | Implemented | Implemented | Implemented | `src-tauri/src/logging.rs` writes to the Wondershot config directory. Use it for native picker and recording diagnostics. |
| Installer | Implemented | Implemented | Planned | Windows uses NSIS. Linux install script is validated. macOS packaging is not done. |
| Global capture hotkey | Implemented | Fallback | Planned | Windows registers the shortcut directly from Settings while the app is running. Linux uses the installed app command path in desktop shortcut settings. macOS native registration is planned. |
| Open containing folder | Implemented | Implemented | Planned | Shared opener abstraction exists; Linux still accounts for Flatpak host opening. |

## Current Intentional Differences

### Linux Mini Capture Window

Linux currently still opens the small `/capture` window from `show_capture_window`
instead of the Windows unified selector. This is preserved because the Linux
path was already working and used Spectacle/portal behavior that users expect.

The action bar on Linux is effectively Spectacle's native action flow when
Spectacle is present. That has mostly been validated on Fedora/KDE; GNOME,
non-KDE desktops, and portal-only behavior need explicit review.

Decision: keep it until Linux has a unified native/Svelte selector with equal or
better behavior. Removing the mini window is reasonable later, but should happen
as an explicit UI decision.

### Windows Unified Selector

Windows uses a native Rust overlay for monitor, window, and region selection.
After a selection, a Svelte action bar lets the user capture, record, or cancel.

Decision: this is the target interaction model for Windows and likely the
shared target for macOS. Linux may converge later if a native overlay can match
or beat Spectacle without losing reliability.

### Browser Permission Prompts

Browser media APIs are acceptable as fallback plumbing, but they should not be
the primary desktop UX for mic, camera, or screen capture when native APIs are
available.

Decision: prefer native OS capture/recording paths for the desktop app.

## Planned Capability Flags

The frontend should eventually consume a single structured capability payload
for UI decisions. Suggested shape:

```ts
type PlatformFeatureStatus = 'implemented' | 'fallback' | 'planned' | 'omitted';

interface PlatformCapabilities {
  platform: 'windows' | 'linux' | 'macos';
  capture: {
    unifiedSelector: PlatformFeatureStatus;
    actionBar: PlatformFeatureStatus;
    fullscreen: PlatformFeatureStatus;
    region: PlatformFeatureStatus;
    window: PlatformFeatureStatus;
    perMonitor: PlatformFeatureStatus;
  };
  recording: {
    fullscreen: PlatformFeatureStatus;
    region: PlatformFeatureStatus;
    window: PlatformFeatureStatus;
    microphone: PlatformFeatureStatus;
    systemAudio: PlatformFeatureStatus;
    pauseResume: PlatformFeatureStatus;
  };
  devices: {
    camera: PlatformFeatureStatus;
    microphone: PlatformFeatureStatus;
  };
}
```

The matrix above should be updated whenever these capabilities change.
