//! Pure window-placement math (no Tauri types), unit-tested in `tests/window_layout.rs`.
//!
//! All sizes are logical points unless a name says `physical`.

/// Hard floor of the window (`minWidth` / `minHeight` in `tauri.conf.json`).
pub const MIN_WIDTH: f64 = 960.0;
pub const MIN_HEIGHT: f64 = 600.0;
/// Preferred minimum for the first launch, honoured only when the screen allows it.
const PREFERRED_MIN_WIDTH: f64 = 1280.0;
const PREFERRED_MIN_HEIGHT: f64 = 800.0;

/// First-launch size for a work area of `work_w` x `work_h` logical points:
/// `min(w * 0.8, 1600)` x `min(h * 0.85, 1000)`, raised to 1280x800 when the
/// screen can hold it, and never larger than the work area itself.
pub fn initial_size(work_w: f64, work_h: f64) -> (f64, f64) {
    let w = (work_w * 0.8)
        .min(1600.0)
        .max(PREFERRED_MIN_WIDTH.min(work_w));
    let h = (work_h * 0.85)
        .min(1000.0)
        .max(PREFERRED_MIN_HEIGHT.min(work_h));
    (
        w.min(work_w).max(MIN_WIDTH.min(work_w)),
        h.min(work_h).max(MIN_HEIGHT.min(work_h)),
    )
}

/// A rectangle in physical pixels.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
}

impl Rect {
    fn contains(&self, px: i64, py: i64) -> bool {
        px >= self.x as i64
            && py >= self.y as i64
            && px < self.x as i64 + self.w as i64
            && py < self.y as i64 + self.h as i64
    }
}

/// Whether a restored window is usable: the middle of its title-bar strip
/// (top edge, horizontally centred) lies inside some monitor, so the user can
/// always grab it. Otherwise the caller should re-centre the window.
pub fn is_reachable(window: Rect, monitors: &[Rect]) -> bool {
    let px = window.x as i64 + window.w as i64 / 2;
    let py = window.y as i64 + 16;
    monitors.iter().any(|m| m.contains(px, py))
}
