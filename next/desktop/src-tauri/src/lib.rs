//! TOOLBOX desktop shell: a thin Tauri 2 wrapper that owns the window, the
//! tray icon and the lifecycle of the Python backend.
//!
//! * [`backend`]: GUI-free supervisor (spawn, handshake, restart, shutdown).
//! * [`updater`]: GUI-free in-app update state machine and `tauri-plugin-updater` adapter.
//! * [`window_layout`]: pure first-launch window sizing and restored-position checks.
//! * [`app`]: Tauri wiring (commands, tray, window and exit handling).

pub mod app;
pub mod backend;
pub mod updater;
pub mod window_layout;

pub use app::run;
