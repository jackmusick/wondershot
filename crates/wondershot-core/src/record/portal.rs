//! xdg-desktop-portal ScreenCast session (pure Rust D-Bus via `ashpd`).
//!
//! Ports the portal flow of `record.py` (CreateSession → SelectSources →
//! Start → OpenPipeWireRemote) to yield the PipeWire fd + node id the
//! gstreamer recorder's `build_pipeline_description(fd, node, ...)` needs.
//!
//! Policy (matches `record.py` exactly):
//! * sources = Monitor | Window (`types = 3`)
//! * cursor  = Embedded (baked into frames — NOT Metadata; `cursor_mode = 2`)
//! * persist = DoNot, and we NEVER replay a saved restore token. The picker
//!   is shown on EVERY recording so the user can re-pick the screen/window —
//!   `record.py` line ~472-479: persist_mode=2 + a token makes the portal
//!   skip its picker after the first recording, which is the bug we avoid.
//!
//! Interactive (the portal pops a picker), so this can't be unit-tested.

use std::os::fd::OwnedFd;

/// The live portal session for an active recording. MUST be closed when the
/// recording ends (clean stop, failure, or external termination) — an open
/// session keeps the compositor casting: KDE's "screen is being shared"
/// indicator stays up, and each new recording stacks another one.
pub type CastSession =
    ashpd::desktop::Session<'static, ashpd::desktop::screencast::Screencast<'static>>;

/// Close a cast session, best-effort (it may already be gone if the user
/// stopped the cast from the system tray).
pub async fn close_session(session: &CastSession) {
    let _ = session.close().await;
}

/// Open an xdg-desktop-portal ScreenCast session and return the PipeWire
/// fd + node id (the picker is shown every time — no token persistence),
/// plus the session handle the caller must close when recording ends.
///
/// The returned [`OwnedFd`] owns the PipeWire remote fd. Keep it alive until
/// the gstreamer pipeline is built: `pipewiresrc` dups the fd, so it can be
/// dropped after the pipeline is created. Get the raw fd for
/// `build_pipeline_description(fd, node, ...)` (which takes `fd: i32`) via
/// `fd.as_raw_fd()` (from `std::os::fd::AsRawFd`).
pub async fn open_screencast() -> Result<(OwnedFd, u32, CastSession), String> {
    use ashpd::desktop::screencast::{CursorMode, Screencast, SourceType};
    use ashpd::desktop::PersistMode;
    use ashpd::WindowIdentifier;

    let proxy = Screencast::new().await.map_err(|e| e.to_string())?;
    let session = proxy.create_session().await.map_err(|e| e.to_string())?;

    proxy
        .select_sources(
            &session,
            CursorMode::Embedded,                       // 2 = baked into frames
            SourceType::Monitor | SourceType::Window,   // 3 = monitor | window
            false,                                      // multiple
            None,                                       // restore_token: never replay
            PersistMode::DoNot,                         // 0 = do not persist
        )
        .await
        .map_err(|e| e.to_string())?;

    let streams = proxy
        .start(&session, &WindowIdentifier::default())
        .await
        .map_err(|e| e.to_string())?
        .response()
        .map_err(|e| e.to_string())?;

    let node_id = streams
        .streams()
        .first()
        .ok_or("portal returned no screencast stream")?
        .pipe_wire_node_id();

    let fd = proxy
        .open_pipe_wire_remote(&session)
        .await
        .map_err(|e| e.to_string())?;

    Ok((fd, node_id, session))
}
