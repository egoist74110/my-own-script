//! TOOLBOX desktop shell: a thin Tauri 2 wrapper that owns the window, the
//! tray icon and the lifecycle of the Python backend.
//!
//! * [`backend`]: GUI-free supervisor (spawn, handshake, restart, shutdown).
//! * [`updater`]: GUI-free in-app update state machine and `tauri-plugin-updater` adapter.
//! * [`app`]: Tauri wiring (commands, tray, window and exit handling).

pub mod app;
pub mod backend;
pub mod updater;

pub use app::run;
