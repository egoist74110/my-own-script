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

use crate::backend::{
    BackendCommand, Connection, State, Status, Supervisor, SupervisorConfig, STATUS_EVENT,
};

const MAIN_WINDOW: &str = "main";
const TRAY_ID: &str = "main";
const MENU_SHOW: &str = "show";
const MENU_QUIT: &str = "quit";

struct AppState {
    supervisor: Arc<Supervisor>,
    /// Set by the first quit request; later requests are no-ops.
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

fn repo_root() -> PathBuf {
    // <repo>/next/desktop/src-tauri -> <repo>. Packaged builds are decided by
    // the S0-D spike and are not fixed here.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![backend_connection, backend_status])
        .on_window_event(|window, event| {
            // Closing the window only hides it; the backend keeps running.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .setup(|app| {
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
                .tooltip("TOOLBOX")
                .on_menu_event(|app, event| match event.id().as_ref() {
                    MENU_SHOW => show_main_window(app),
                    MENU_QUIT => begin_quit(app),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            let command = BackendCommand::dev(
                &repo_root(),
                std::env::var("TOOLBOX_BACKEND_CMD").ok().as_deref(),
            )?;
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
            app.manage(AppState {
                supervisor,
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
