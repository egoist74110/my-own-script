//! Tauri wiring. Everything here is glue; behavior worth testing lives in
//! [`crate::backend`].

use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, RunEvent, State as TauriState, WindowEvent, Wry,
};

use crate::{
    backend::{
        BackendCommand, Connection, State, Status, Supervisor, SupervisorConfig, STATUS_EVENT,
    },
    updater::{
        has_updater_plugin_config, resolve_disabled_reason, TauriUpdateSource, UpdateCoordinator,
        UpdateStatus, UPDATE_STATUS_EVENT,
    },
    window_layout::{initial_size, is_reachable, Rect},
};
use tauri_plugin_window_state::StateFlags;

const MAIN_WINDOW: &str = "main";
const TRAY_ID: &str = "main";
const MENU_SHOW: &str = "show";
const MENU_QUIT: &str = "quit";

struct AppState {
    supervisor: Arc<Supervisor>,
    updater: UpdateCoordinator,
    /// Set by the first quit/restart request; later requests are no-ops.
    quitting: AtomicBool,
}

/// Page-facing command: the `{port, token}` pair, waiting (<= 20 s) for the
/// backend if it is still starting or restarting.
#[tauri::command]
async fn backend_connection(state: TauriState<'_, AppState>) -> Result<Connection, String> {
    let supervisor = state.supervisor.clone();
    supervisor
        .connection(supervisor.connection_wait())
        .await
        .map_err(|e| e.to_string())
}

/// Current status snapshot (the page may miss events emitted before it listened).
#[tauri::command]
fn backend_status(state: TauriState<'_, AppState>) -> Status {
    state.supervisor.status()
}

/// Read-only in-app updater status snapshot.
#[tauri::command]
fn update_status(state: TauriState<'_, AppState>) -> UpdateStatus {
    state.updater.status()
}

/// Trigger an update check (`idle/up_to_date/error -> checking`).
#[tauri::command]
async fn update_check(state: TauriState<'_, AppState>) -> Result<UpdateStatus, String> {
    let updater = state.updater.clone();
    updater.check().await
}

/// Download, verify signature, and install an available update (`available -> downloading -> ready`).
#[tauri::command]
async fn update_install(state: TauriState<'_, AppState>) -> Result<UpdateStatus, String> {
    let updater = state.updater.clone();
    updater.install().await
}

/// Cancel an in-flight update check or download (`checking/downloading -> update_cancelled`).
#[tauri::command]
fn update_cancel(state: TauriState<'_, AppState>) -> UpdateStatus {
    state.updater.cancel()
}

/// Coordinate backend shutdown and restart into the newly installed version (`ready` only).
#[tauri::command]
async fn update_restart(state: TauriState<'_, AppState>) -> Result<(), String> {
    let updater = state.updater.clone();
    updater.restart().await
}

fn status_label(s: &Status) -> String {
    match s.state {
        State::Starting => "后端：启动中".to_owned(),
        State::Ready => match s.pid {
            Some(pid) => format!("后端：运行中 (pid {pid})"),
            None => "后端：运行中".to_owned(),
        },
        State::Restarting => format!("后端：重启中 (第 {} 次)", s.restarts),
        State::Stopping => "后端：正在停止".to_owned(),
        State::Stopped => "后端：已停止".to_owned(),
    }
}

fn show_main_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window(MAIN_WINDOW) {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

/// Start the one-and-only coordinated shutdown, then exit the process.
/// Callers: tray "退出", Cmd+Q / system logout (`ExitRequested`), SIGTERM/SIGINT.
fn begin_quit(app: &AppHandle) {
    let state = app.state::<AppState>();
    if state.quitting.swap(true, Ordering::SeqCst) {
        return;
    }
    let supervisor = state.supervisor.clone();
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        supervisor.shutdown().await;
        app.exit(0);
    });
}

/// Coordinated shutdown followed by `app.restart()`, sharing the `quitting` guard with `begin_quit`
/// so backend supervision is always cleanly stopped before the new process replaces this one.
async fn coordinated_restart(app: AppHandle) {
    let state = app.state::<AppState>();
    let _ = state.quitting.swap(true, Ordering::SeqCst);
    let supervisor = state.supervisor.clone();
    supervisor.shutdown().await;
    app.restart();
}

/// Window geometry is remembered by `tauri-plugin-window-state`; visibility and
/// decorations are deliberately not part of it (the window is hidden on close and
/// the tray may quit while hidden, which would otherwise start hidden next time).
fn window_state_flags() -> StateFlags {
    StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED
}

fn monitor_rect(m: &tauri::Monitor) -> Rect {
    let a = m.work_area();
    Rect {
        x: a.position.x,
        y: a.position.y,
        w: a.size.width,
        h: a.size.height,
    }
}

/// First launch (no saved state): size from the current monitor's work area and centre.
/// Later launches: the plugin already restored size/position/maximized; if the saved
/// position is on no monitor any more (unplugged display), centre instead.
fn place_main_window(app: &tauri::App) {
    let Some(w) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    let has_saved = app
        .path()
        .app_config_dir()
        .map(|d| {
            d.join(tauri_plugin_window_state::DEFAULT_FILENAME)
                .is_file()
        })
        .unwrap_or(false);
    if !has_saved {
        let monitor = w
            .current_monitor()
            .ok()
            .flatten()
            .or_else(|| w.primary_monitor().ok().flatten());
        if let Some(m) = monitor {
            let area = m.work_area();
            let scale = m.scale_factor();
            let (lw, lh) = initial_size(
                area.size.width as f64 / scale,
                area.size.height as f64 / scale,
            );
            let _ = w.set_size(tauri::LogicalSize::new(lw, lh));
        }
        let _ = w.center();
        return;
    }
    if w.is_maximized().unwrap_or(false) {
        return;
    }
    let (Ok(pos), Ok(size), Ok(monitors)) =
        (w.outer_position(), w.outer_size(), w.available_monitors())
    else {
        return;
    };
    let rects: Vec<Rect> = monitors.iter().map(monitor_rect).collect();
    let win = Rect {
        x: pos.x,
        y: pos.y,
        w: size.width,
        h: size.height,
    };
    if !rects.is_empty() && !is_reachable(win, &rects) {
        let _ = w.center();
    }
}

fn repo_root() -> PathBuf {
    // Development fallback only; this path need not exist in packaged builds.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(window_state_flags())
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            backend_connection,
            backend_status,
            update_status,
            update_check,
            update_install,
            update_cancel,
            update_restart,
        ])
        .on_window_event(|window, event| {
            // Closing the window only hides it; the backend keeps running.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .setup(|app| {
            place_main_window(app);
            let status_item = MenuItem::with_id(
                app,
                "status",
                status_label(&Status {
                    state: State::Starting,
                    pid: None,
                    restarts: 0,
                }),
                false,
                None::<&str>,
            )?;
            let show = MenuItem::with_id(app, MENU_SHOW, "显示窗口", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, MENU_QUIT, "退出", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[
                    &status_item,
                    &PredefinedMenuItem::separator(app)?,
                    &show,
                    &quit,
                ],
            )?;
            let mut tray = TrayIconBuilder::<Wry>::with_id(TRAY_ID)
                .menu(&menu)
                .tooltip("代码工具箱")
                .on_menu_event(|app, event| match event.id().as_ref() {
                    MENU_SHOW => show_main_window(app),
                    MENU_QUIT => begin_quit(app),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            let current_exe = std::env::current_exe()?;
            let override_cmd = std::env::var("TOOLBOX_BACKEND_CMD").ok();
            let command =
                BackendCommand::packaged(&current_exe, &repo_root(), override_cmd.as_deref())?;
            let mut cfg = SupervisorConfig::new(command);
            let handle = app.handle().clone();
            cfg.on_status = Some(Arc::new(move |status: &Status| {
                // Payload is {state, pid, restarts}; never the token.
                let _ = handle.emit(STATUS_EVENT, status);
                let _ = status_item.set_text(status_label(status));
            }));
            cfg.log = Arc::new(|line| eprintln!("[toolbox] {line}"));
            // Supervisor::start needs a Tokio context.
            let supervisor =
                tauri::async_runtime::block_on(async move { Arc::new(Supervisor::start(cfg)) });

            // Register `tauri-plugin-updater` only when `plugins.updater` is configured:
            // `tauri_plugin_updater::Config` requires `pubkey: String` without `#[serde(default)]`,
            // so unconditionally registering the plugin panics on default builds without updater config.
            let disabled_reason = resolve_disabled_reason(
                &app.config().plugins,
                &current_exe,
                override_cmd.as_deref(),
            );
            if has_updater_plugin_config(&app.config().plugins) {
                app.handle()
                    .plugin(tauri_plugin_updater::Builder::new().build())?;
            }
            let current_version = app.package_info().version.to_string();
            let update_source = Arc::new(TauriUpdateSource::new(app.handle().clone()));
            let emit_handle = app.handle().clone();
            let restart_handle = app.handle().clone();
            let updater = UpdateCoordinator::new(
                current_version,
                disabled_reason,
                update_source,
                Arc::new(move |status: &UpdateStatus| {
                    let _ = emit_handle.emit(UPDATE_STATUS_EVENT, status);
                }),
                Arc::new(|line| eprintln!("[toolbox] {line}")),
                Arc::new(move || {
                    let h = restart_handle.clone();
                    Box::pin(async move {
                        coordinated_restart(h).await;
                    })
                }),
            );

            app.manage(AppState {
                supervisor,
                updater,
                quitting: AtomicBool::new(false),
            });

            // SIGTERM/SIGINT take the same path as the tray's quit item.
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                use tokio::signal::unix::{signal, SignalKind};
                let (Ok(mut term), Ok(mut int)) = (
                    signal(SignalKind::terminate()),
                    signal(SignalKind::interrupt()),
                ) else {
                    return;
                };
                tokio::select! {
                    _ = term.recv() => {}
                    _ = int.recv() => {}
                }
                begin_quit(&handle);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the TOOLBOX shell");

    app.run(|app, event| match event {
        RunEvent::ExitRequested { api, .. } => {
            let stopped = app
                .try_state::<AppState>()
                .is_none_or(|s| s.supervisor.is_stopped());
            if !stopped {
                // Hold the exit until the backend group is reclaimed.
                api.prevent_exit();
                begin_quit(app);
            }
        }
        // Dock icon clicked while the window is hidden.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows: false,
            ..
        } => show_main_window(app),
        RunEvent::Exit => {
            // Last line of defence if the process exits through a path that
            // skipped ExitRequested; idempotent with begin_quit.
            if let Some(state) = app.try_state::<AppState>() {
                let supervisor = state.supervisor.clone();
                tauri::async_runtime::block_on(async move { supervisor.shutdown().await });
            }
        }
        _ => {}
    });
}
