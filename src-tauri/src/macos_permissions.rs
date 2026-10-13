//! Request camera/microphone access from the app before spawning media helpers.
use objc2::{msg_send, runtime::{AnyClass, Bool}};
use objc2_foundation::NSString;
use std::{sync::mpsc, time::Duration};

#[link(name = "AVFoundation", kind = "framework")]
unsafe extern "C" {}

pub fn ensure(kind: &str) -> Result<(), String> {
    let media = match kind { "microphone" => "soun", "camera" => "vide", _ => return Err("unknown media permission".into()) };
    let class = AnyClass::get(c"AVCaptureDevice").ok_or("AVFoundation capture is unavailable")?;
    let media = NSString::from_str(media);
    let status: isize = unsafe { msg_send![class, authorizationStatusForMediaType: &*media] };
    match status {
        3 => return Ok(()),
        1 | 2 => return Err(format!("Enable Wondershot {kind} access in System Settings → Privacy & Security, or disable it in Wondershot Settings.")),
        _ => {}
    }
    let (tx, rx) = mpsc::channel();
    let completion = block2::RcBlock::new(move |granted: Bool| { let _ = tx.send(granted.as_bool()); });
    unsafe { let _: () = msg_send![class, requestAccessForMediaType: &*media, completionHandler: &*completion]; }
    match rx.recv_timeout(Duration::from_secs(120)) {
        Ok(true) => Ok(()),
        Ok(false) => Err(format!("{kind} access was declined; disable it in Wondershot Settings to continue without it")),
        Err(_) => Err(format!("waiting for macOS {kind} permission timed out")),
    }
}
