//! PURE clock / PTS helpers ported from `record.py` (no GStreamer).

/// Grace period before escalating a stuck stop. (record.py:313)
pub const GRACE_MS: u64 = 5000;
/// Hard-kill threshold for a stuck stop. (record.py:314)
pub const KILL_MS: u64 = 10000;

/// Nanoseconds to subtract from buffer PTS/DTS so a resumed segment is
/// gap-free for mp4mux. (record.py:164-167)
pub fn pts_offset_ns(paused_total_s: f64) -> i64 {
    (paused_total_s * 1_000_000_000.0).round() as i64
}

/// Wall seconds recorded, excluding paused spans. (record.py:149-156)
pub fn elapsed_seconds(
    started_at: Option<f64>,
    now: f64,
    paused_total: f64,
    paused_at: Option<f64>,
) -> f64 {
    let Some(start) = started_at else { return 0.0 };
    let mut live = now - start - paused_total;
    if let Some(p) = paused_at {
        live -= now - p;
    }
    live.max(0.0)
}

/// "M:SS" — minutes:zero-padded-seconds. (record.py:159-161)
pub fn format_elapsed(seconds: f64) -> String {
    let s = seconds.max(0.0) as u64;
    format!("{}:{:02}", s / 60, s % 60)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn pts_offset_ns_converts_seconds() { assert_eq!(pts_offset_ns(1.5), 1_500_000_000); }
    #[test] fn elapsed_excludes_paused_total() {
        assert!((elapsed_seconds(Some(100.0), 110.0, 3.0, None) - 7.0).abs() < 1e-9);
    }
    #[test] fn elapsed_excludes_in_flight_pause() {
        assert!((elapsed_seconds(Some(100.0), 110.0, 0.0, Some(106.0)) - 6.0).abs() < 1e-9);
    }
    #[test] fn elapsed_none_start_is_zero() { assert_eq!(elapsed_seconds(None, 110.0, 0.0, None), 0.0); }
    #[test] fn elapsed_never_negative() { assert_eq!(elapsed_seconds(Some(100.0), 100.0, 50.0, None), 0.0); }
    #[test] fn format_elapsed_mmss() {
        assert_eq!(format_elapsed(65.0), "1:05");
        assert_eq!(format_elapsed(5.0), "0:05");
        assert_eq!(format_elapsed(600.0), "10:00");
    }
    #[test] fn escalation_constants() { assert_eq!(GRACE_MS, 5000); assert_eq!(KILL_MS, 10000); }
}
