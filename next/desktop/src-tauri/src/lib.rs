//! TOOLBOX desktop shell: a thin Tauri 2 wrapper that owns the window, the
//! tray icon and the lifecycle of the Python backend.
//!
//! * [`backend`]: GUI-free supervisor (spawn, handshake, restart, shutdown).
//! * [`app`]: Tauri wiring (commands, tray, window and exit handling).

pub mod app;
pub mod backend;

pub use app::run;
