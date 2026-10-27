//! In-app update state machine and `tauri-plugin-updater` adapter.
//!
//! Frozen contract (see `docs/modernization/WORK_PACKAGES.md` "S9-C 追加决定与接口冻结"):
//! * Single-flight mutex (`update_busy` when checking or downloading);
//! * `update_check`: `idle | up_to_date | error -> checking -> available | up_to_date | error`;
//! * `update_install`: only from `available -> downloading -> ready` (or on failure/cancel back
//!   to retryable `available` without installing);
//! * `update_cancel`: only active during `checking` or `downloading` (`update_cancelled`, back to
//!   `idle` or `available`); other states return snapshot unchanged;
//! * `update_restart`: only from `ready`; runs coordinated backend shutdown before restarting;
//! * `disabled`: when `plugins.updater` is not configured (`update_not_configured`) or when running
//!   in non-packaged dev mode (`update_unsupported_dev`); never touches the network;
//! * Status and logs never include full update URLs or signatures (logs record hostnames only).

use std::{
    future::Future,
    path::Path,
    pin::Pin,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{AppHandle, Runtime};
use tauri_plugin_updater::{Error as PluginError, Update, UpdaterExt};
use tokio::sync::watch;

/// Event name emitted whenever [`UpdateStatus`] changes.
pub const UPDATE_STATUS_EVENT: &str = "update://status";

/// Maximum character count for release notes (`notes` is truncated to at most 2000 chars).
pub const MAX_NOTES_CHARS: usize = 2000;

/// Minimum interval between `downloading` progress event emissions (<= 5 events/sec).
pub const PROGRESS_THROTTLE: Duration = Duration::from_millis(200);

pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;
pub type StatusSink = Arc<dyn Fn(&UpdateStatus) + Send + Sync>;
pub type LogSink = Arc<dyn Fn(&str) + Send + Sync>;
pub type RestartHook = Arc<dyn Fn() -> BoxFuture<'static, ()> + Send + Sync>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UpdateState {
    Disabled,
    Idle,
    Checking,
    UpToDate,
    Available,
    Downloading,
    Ready,
    Error,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UpdateErrorCode {
    UpdateNotConfigured,
    UpdateUnsupportedDev,
    UpdateBusy,
    UpdateCheckFailed,
    UpdateDownloadFailed,
    UpdateSignatureInvalid,
    UpdateInstallFailed,
    UpdateCancelled,
}

impl UpdateErrorCode {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::UpdateNotConfigured => "update_not_configured",
            Self::UpdateUnsupportedDev => "update_unsupported_dev",
            Self::UpdateBusy => "update_busy",
            Self::UpdateCheckFailed => "update_check_failed",
            Self::UpdateDownloadFailed => "update_download_failed",
            Self::UpdateSignatureInvalid => "update_signature_invalid",
            Self::UpdateInstallFailed => "update_install_failed",
            Self::UpdateCancelled => "update_cancelled",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UpdateProgress {
    pub downloaded: u64,
    pub total: Option<u64>,
}

/// Frozen payload for `update_status`/`update_check`/`update_install`/`update_cancel` and
/// the `update://status` event.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UpdateStatus {
    pub state: UpdateState,
    pub current_version: String,
    pub available_version: Option<String>,
    pub notes: Option<String>,
    pub progress: Option<UpdateProgress>,
    pub error_code: Option<UpdateErrorCode>,
    pub checked_at: Option<u64>,
}

/// Sanitized metadata for an available update (never exposes full URL or signature).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateInfo {
    pub version: String,
    pub notes: Option<String>,
    /// Hostname only, for sanitized logging.
    pub host: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpdateError {
    CheckFailed {
        host: Option<String>,
        reason: String,
    },
    DownloadFailed {
        host: Option<String>,
        reason: String,
    },
    SignatureInvalid,
    InstallFailed {
        reason: String,
    },
    Cancelled,
}

impl UpdateError {
    pub fn code(&self) -> UpdateErrorCode {
        match self {
            Self::CheckFailed { .. } => UpdateErrorCode::UpdateCheckFailed,
            Self::DownloadFailed { .. } => UpdateErrorCode::UpdateDownloadFailed,
            Self::SignatureInvalid => UpdateErrorCode::UpdateSignatureInvalid,
            Self::InstallFailed { .. } => UpdateErrorCode::UpdateInstallFailed,
            Self::Cancelled => UpdateErrorCode::UpdateCancelled,
        }
    }
}

/// Injectable update backend so the state machine can be unit-tested offline without network.
pub trait UpdateSource: Send + Sync {
    fn check(&self) -> BoxFuture<'_, Result<Option<UpdateInfo>, UpdateError>>;

    fn download(
        &self,
        info: &UpdateInfo,
        progress_cb: Box<dyn FnMut(usize, Option<u64>) + Send>,
        cancel: watch::Receiver<bool>,
    ) -> BoxFuture<'_, Result<Vec<u8>, UpdateError>>;

    fn install(&self, payload: Vec<u8>) -> BoxFuture<'_, Result<(), UpdateError>>;
}

/// Truncate release notes to at most [`MAX_NOTES_CHARS`] characters (Unicode scalar values).
pub fn truncate_notes(notes: Option<&str>) -> Option<String> {
    let raw = notes?;
    let mut out = String::new();
    for (idx, ch) in raw.chars().enumerate() {
        if idx >= MAX_NOTES_CHARS {
            break;
        }
        out.push(ch);
    }
    Some(out)
}

/// Same packaged-mode criterion as `BackendCommand::packaged` in S9-A:
/// returns `true` iff `TOOLBOX_BACKEND_CMD` is unset/blank and
/// `<executable>/../../Resources/backend/bin/python3.14` exists.
pub fn is_packaged_executable(executable: &Path, override_cmd: Option<&str>) -> bool {
    if override_cmd.is_some_and(|raw| !raw.trim().is_empty()) {
        return false;
    }
    executable
        .parent()
        .and_then(Path::parent)
        .map(|contents| contents.join("Resources/backend/bin/python3.14").exists())
        .unwrap_or(false)
}

/// Check whether `plugins` JSON map contains a usable `updater` configuration
/// (`pubkey` non-empty and `endpoints` non-empty array).
///
/// Why this is needed before registering `tauri-plugin-updater`:
/// `tauri_plugin_updater::Config` requires `pubkey: String` without `#[serde(default)]`.
/// When `plugins.updater` is absent, Tauri passes `JsonValue::Null` to `Plugin::initialize`,
/// causing `serde_json::from_value` to fail and `tauri::Builder::build` to panic!
pub fn has_updater_plugin_config<S: serde::Serialize>(plugins: &S) -> bool {
    let Ok(val) = serde_json::to_value(plugins) else {
        return false;
    };
    let Some(updater) = val.get("updater").and_then(|v| v.as_object()) else {
        return false;
    };
    let has_pubkey = updater
        .get("pubkey")
        .and_then(|v| v.as_str())
        .is_some_and(|s| !s.trim().is_empty());
    let has_endpoints = updater
        .get("endpoints")
        .and_then(|v| v.as_array())
        .is_some_and(|arr| {
            !arr.is_empty()
                && arr
                    .iter()
                    .all(|item| item.as_str().is_some_and(|u| !u.trim().is_empty()))
        });
    has_pubkey && has_endpoints
}

/// Determine whether the updater should be disabled and why.
/// Priority: missing `plugins.updater` config -> `UpdateNotConfigured`;
/// non-packaged dev mode -> `UpdateUnsupportedDev`.
pub fn resolve_disabled_reason<S: serde::Serialize>(
    plugins: &S,
    executable: &Path,
    override_cmd: Option<&str>,
) -> Option<UpdateErrorCode> {
    if !has_updater_plugin_config(plugins) {
        return Some(UpdateErrorCode::UpdateNotConfigured);
    }
    if !is_packaged_executable(executable, override_cmd) {
        return Some(UpdateErrorCode::UpdateUnsupportedDev);
    }
    None
}

fn now_unix_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

struct Inner {
    status: UpdateStatus,
    available_info: Option<UpdateInfo>,
    cancel_tx: Option<watch::Sender<bool>>,
}

#[derive(Clone)]
pub struct UpdateCoordinator {
    inner: Arc<Mutex<Inner>>,
    busy: Arc<AtomicBool>,
    source: Arc<dyn UpdateSource>,
    on_status: StatusSink,
    log: LogSink,
    on_restart: RestartHook,
}

struct BusyGuard(Arc<AtomicBool>);

impl Drop for BusyGuard {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

impl UpdateCoordinator {
    pub fn new(
        current_version: String,
        disabled_reason: Option<UpdateErrorCode>,
        source: Arc<dyn UpdateSource>,
        on_status: StatusSink,
        log: LogSink,
        on_restart: RestartHook,
    ) -> Self {
        let initial = match disabled_reason {
            Some(code) => UpdateStatus {
                state: UpdateState::Disabled,
                current_version,
                available_version: None,
                notes: None,
                progress: None,
                error_code: Some(code),
                checked_at: None,
            },
            None => UpdateStatus {
                state: UpdateState::Idle,
                current_version,
                available_version: None,
                notes: None,
                progress: None,
                error_code: None,
                checked_at: None,
            },
        };
        Self {
            inner: Arc::new(Mutex::new(Inner {
                status: initial,
                available_info: None,
                cancel_tx: None,
            })),
            busy: Arc::new(AtomicBool::new(false)),
            source,
            on_status,
            log,
            on_restart,
        }
    }

    fn log(&self, msg: &str) {
        (self.log)(msg);
    }

    fn publish(&self, f: impl FnOnce(&mut Inner)) -> UpdateStatus {
        let snapshot = {
            let mut guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
            f(&mut guard);
            guard.status.clone()
        };
        (self.on_status)(&snapshot);
        snapshot
    }

    /// Read-only status snapshot (`update_status`).
    pub fn status(&self) -> UpdateStatus {
        self.inner
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .status
            .clone()
    }

    /// Check for updates (`update_check`).
    pub async fn check(&self) -> Result<UpdateStatus, String> {
        {
            let guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
            if guard.status.state == UpdateState::Disabled {
                return Ok(guard.status.clone());
            }
        }

        if self
            .busy
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err(UpdateErrorCode::UpdateBusy.as_str().to_owned());
        }
        let _busy_guard = BusyGuard(self.busy.clone());

        let (cancel_tx, mut cancel_rx) = watch::channel(false);
        {
            let mut guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
            match guard.status.state {
                UpdateState::Disabled => return Ok(guard.status.clone()),
                UpdateState::Idle
                | UpdateState::UpToDate
                | UpdateState::Error
                | UpdateState::Available => {
                    guard.status.state = UpdateState::Checking;
                    guard.status.progress = None;
                    guard.status.error_code = None;
                    guard.cancel_tx = Some(cancel_tx);
                }
                UpdateState::Checking | UpdateState::Downloading => {
                    return Err(UpdateErrorCode::UpdateBusy.as_str().to_owned());
                }
                UpdateState::Ready => {
                    return Err(UpdateErrorCode::UpdateCheckFailed.as_str().to_owned());
                }
            }
            let st = guard.status.clone();
            drop(guard);
            (self.on_status)(&st);
        }

        let source = self.source.clone();
        let res = tokio::select! {
            r = source.check() => r,
            _ = cancel_rx.wait_for(|c| *c) => Err(UpdateError::Cancelled),
        };

        let checked_at = now_unix_secs();
        match res {
            Ok(Some(info)) => {
                let host = info.host.as_deref().unwrap_or("unknown");
                self.log(&format!(
                    "updater: update {} available from host {host}",
                    info.version
                ));
                let notes = truncate_notes(info.notes.as_deref());
                let version = info.version.clone();
                Ok(self.publish(|inner| {
                    inner.cancel_tx = None;
                    inner.available_info = Some(info);
                    inner.status.state = UpdateState::Available;
                    inner.status.available_version = Some(version);
                    inner.status.notes = notes;
                    inner.status.progress = None;
                    inner.status.error_code = None;
                    inner.status.checked_at = Some(checked_at);
                }))
            }
            Ok(None) => {
                self.log("updater: application is up to date");
                Ok(self.publish(|inner| {
                    inner.cancel_tx = None;
                    inner.available_info = None;
                    inner.status.state = UpdateState::UpToDate;
                    inner.status.available_version = None;
                    inner.status.notes = None;
                    inner.status.progress = None;
                    inner.status.error_code = None;
                    inner.status.checked_at = Some(checked_at);
                }))
            }
            Err(UpdateError::Cancelled) => {
                self.log("updater: update check cancelled");
                Ok(self.publish(|inner| {
                    inner.cancel_tx = None;
                    inner.status.state = if inner.available_info.is_some() {
                        UpdateState::Available
                    } else {
                        UpdateState::Idle
                    };
                    inner.status.progress = None;
                    inner.status.error_code = Some(UpdateErrorCode::UpdateCancelled);
                }))
            }
            Err(err) => {
                let code = err.code();
                self.log(&format!("updater: check failed ({})", code.as_str()));
                Ok(self.publish(|inner| {
                    inner.cancel_tx = None;
                    inner.status.state = UpdateState::Error;
                    inner.status.progress = None;
                    inner.status.error_code = Some(code);
                    inner.status.checked_at = Some(checked_at);
                }))
            }
        }
    }

    /// Download, verify signature, and install an available update (`update_install`).
    pub async fn install(&self) -> Result<UpdateStatus, String> {
        {
            let guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
            if guard.status.state == UpdateState::Disabled {
                return Ok(guard.status.clone());
            }
        }

        if self
            .busy
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err(UpdateErrorCode::UpdateBusy.as_str().to_owned());
        }
        let _busy_guard = BusyGuard(self.busy.clone());

        let (cancel_tx, mut cancel_rx) = watch::channel(false);
        let info = {
            let mut guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
            match guard.status.state {
                UpdateState::Disabled => return Ok(guard.status.clone()),
                UpdateState::Available => {
                    let Some(info) = guard.available_info.clone() else {
                        return Err(UpdateErrorCode::UpdateInstallFailed.as_str().to_owned());
                    };
                    guard.status.state = UpdateState::Downloading;
                    guard.status.progress = Some(UpdateProgress {
                        downloaded: 0,
                        total: None,
                    });
                    guard.status.error_code = None;
                    guard.cancel_tx = Some(cancel_tx);
                    let st = guard.status.clone();
                    drop(guard);
                    (self.on_status)(&st);
                    info
                }
                UpdateState::Checking | UpdateState::Downloading => {
                    return Err(UpdateErrorCode::UpdateBusy.as_str().to_owned());
                }
                _ => {
                    return Err(UpdateErrorCode::UpdateInstallFailed.as_str().to_owned());
                }
            }
        };

        let inner_ref = self.inner.clone();
        let on_status_ref = self.on_status.clone();
        let mut downloaded_total: u64 = 0;
        let mut last_emit: Option<Instant> = None;

        let progress_cb = Box::new(move |chunk_len: usize, total: Option<u64>| {
            downloaded_total = downloaded_total.saturating_add(chunk_len as u64);
            let now = Instant::now();
            let should_emit = match last_emit {
                None => true,
                Some(prev) => now.duration_since(prev) >= PROGRESS_THROTTLE,
            };
            let mut guard = inner_ref.lock().unwrap_or_else(|e| e.into_inner());
            if guard.status.state != UpdateState::Downloading {
                return;
            }
            guard.status.progress = Some(UpdateProgress {
                downloaded: downloaded_total,
                total,
            });
            if should_emit {
                last_emit = Some(now);
                let snapshot = guard.status.clone();
                drop(guard);
                on_status_ref(&snapshot);
            }
        });

        let source = self.source.clone();
        let dl_cancel_rx = cancel_rx.clone();
        let download_res = tokio::select! {
            r = source.download(&info, progress_cb, dl_cancel_rx) => r,
            _ = cancel_rx.wait_for(|c| *c) => Err(UpdateError::Cancelled),
        };

        let payload = match download_res {
            Ok(bytes) => {
                if *cancel_rx.borrow() {
                    self.log("updater: download cancelled before install");
                    return Ok(self.publish(|inner| {
                        inner.cancel_tx = None;
                        inner.status.state = UpdateState::Available;
                        inner.status.progress = None;
                        inner.status.error_code = Some(UpdateErrorCode::UpdateCancelled);
                    }));
                }
                bytes
            }
            Err(UpdateError::Cancelled) => {
                self.log("updater: download cancelled");
                return Ok(self.publish(|inner| {
                    inner.cancel_tx = None;
                    inner.status.state = UpdateState::Available;
                    inner.status.progress = None;
                    inner.status.error_code = Some(UpdateErrorCode::UpdateCancelled);
                }));
            }
            Err(err) => {
                let code = err.code();
                let host = info.host.as_deref().unwrap_or("unknown");
                self.log(&format!(
                    "updater: download/verify from {host} failed ({})",
                    code.as_str()
                ));
                return Ok(self.publish(|inner| {
                    inner.cancel_tx = None;
                    // Return to retryable Available state and retain old version
                    inner.status.state = UpdateState::Available;
                    inner.status.progress = None;
                    inner.status.error_code = Some(code);
                }));
            }
        };

        // Clear cancel handle before entering synchronous/atomic install phase
        {
            let mut guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
            guard.cancel_tx = None;
        }

        match self.source.install(payload).await {
            Ok(()) => {
                self.log(&format!(
                    "updater: update {} installed and ready to restart",
                    info.version
                ));
                Ok(self.publish(|inner| {
                    inner.status.state = UpdateState::Ready;
                    inner.status.progress = None;
                    inner.status.error_code = None;
                }))
            }
            Err(err) => {
                let code = err.code();
                self.log(&format!(
                    "updater: install failed ({}), old version retained",
                    code.as_str()
                ));
                Ok(self.publish(|inner| {
                    // Return to retryable Available state and retain old version
                    inner.status.state = UpdateState::Available;
                    inner.status.progress = None;
                    inner.status.error_code = Some(code);
                }))
            }
        }
    }

    /// Cancel an in-flight check or download (`update_cancel`).
    /// Only effective in `checking` or `downloading`; returns snapshot unchanged otherwise.
    pub fn cancel(&self) -> UpdateStatus {
        let mut guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        match guard.status.state {
            UpdateState::Checking => {
                if let Some(tx) = guard.cancel_tx.take() {
                    let _ = tx.send(true);
                }
                guard.status.state = if guard.available_info.is_some() {
                    UpdateState::Available
                } else {
                    UpdateState::Idle
                };
                guard.status.progress = None;
                guard.status.error_code = Some(UpdateErrorCode::UpdateCancelled);
                let snapshot = guard.status.clone();
                drop(guard);
                (self.on_status)(&snapshot);
                snapshot
            }
            UpdateState::Downloading => {
                if let Some(tx) = guard.cancel_tx.take() {
                    let _ = tx.send(true);
                }
                guard.status.state = UpdateState::Available;
                guard.status.progress = None;
                guard.status.error_code = Some(UpdateErrorCode::UpdateCancelled);
                let snapshot = guard.status.clone();
                drop(guard);
                (self.on_status)(&snapshot);
                snapshot
            }
            _ => guard.status.clone(),
        }
    }

    /// Coordinate backend shutdown and restart the application (`update_restart`).
    /// Only allowed when `state == Ready`.
    pub async fn restart(&self) -> Result<(), String> {
        {
            let guard = self.inner.lock().unwrap_or_else(|e| e.into_inner());
            match guard.status.state {
                UpdateState::Ready => {}
                UpdateState::Disabled => {
                    let code = guard
                        .status
                        .error_code
                        .unwrap_or(UpdateErrorCode::UpdateNotConfigured);
                    return Err(code.as_str().to_owned());
                }
                UpdateState::Checking | UpdateState::Downloading => {
                    return Err(UpdateErrorCode::UpdateBusy.as_str().to_owned());
                }
                _ => {
                    return Err(UpdateErrorCode::UpdateInstallFailed.as_str().to_owned());
                }
            }
        }
        (self.on_restart)().await;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Production `UpdateSource` backed by `tauri-plugin-updater`
// ---------------------------------------------------------------------------

pub struct TauriUpdateSource<R: Runtime> {
    app: AppHandle<R>,
    pending_update: Mutex<Option<Update>>,
}

impl<R: Runtime> TauriUpdateSource<R> {
    pub fn new(app: AppHandle<R>) -> Self {
        Self {
            app,
            pending_update: Mutex::new(None),
        }
    }
}

fn classify_plugin_download_error(err: &PluginError, host: Option<String>) -> UpdateError {
    match err {
        PluginError::Minisign(_)
        | PluginError::Base64(_)
        | PluginError::SignatureUtf8(_)
        | PluginError::SignedVersionMismatch { .. }
        | PluginError::MissingSignedVersion => UpdateError::SignatureInvalid,
        _ => UpdateError::DownloadFailed {
            host,
            reason: "download failed".to_owned(),
        },
    }
}

impl<R: Runtime> UpdateSource for TauriUpdateSource<R> {
    fn check(&self) -> BoxFuture<'_, Result<Option<UpdateInfo>, UpdateError>> {
        Box::pin(async move {
            let updater = self.app.updater().map_err(|_| UpdateError::CheckFailed {
                host: None,
                reason: "updater builder failed".to_owned(),
            })?;
            match updater.check().await {
                Ok(Some(update)) => {
                    let host = update.download_url.host_str().map(str::to_owned);
                    let info = UpdateInfo {
                        version: update.version.clone(),
                        notes: update.body.clone(),
                        host,
                    };
                    *self
                        .pending_update
                        .lock()
                        .unwrap_or_else(|e| e.into_inner()) = Some(update);
                    Ok(Some(info))
                }
                Ok(None) => {
                    *self
                        .pending_update
                        .lock()
                        .unwrap_or_else(|e| e.into_inner()) = None;
                    Ok(None)
                }
                Err(_) => Err(UpdateError::CheckFailed {
                    host: None,
                    reason: "check failed".to_owned(),
                }),
            }
        })
    }

    fn download(
        &self,
        info: &UpdateInfo,
        mut progress_cb: Box<dyn FnMut(usize, Option<u64>) + Send>,
        mut cancel: watch::Receiver<bool>,
    ) -> BoxFuture<'_, Result<Vec<u8>, UpdateError>> {
        let update = self
            .pending_update
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
            .filter(|u| u.version == info.version);
        let host = info.host.clone();
        Box::pin(async move {
            let Some(update) = update else {
                return Err(UpdateError::DownloadFailed {
                    host,
                    reason: "no matching pending update".to_owned(),
                });
            };
            let download_fut = update.download(
                |chunk_len, content_len| {
                    progress_cb(chunk_len, content_len);
                },
                || {},
            );
            tokio::select! {
                res = download_fut => match res {
                    Ok(bytes) => Ok(bytes),
                    Err(e) => Err(classify_plugin_download_error(&e, host)),
                },
                _ = cancel.wait_for(|c| *c) => Err(UpdateError::Cancelled),
            }
        })
    }

    fn install(&self, payload: Vec<u8>) -> BoxFuture<'_, Result<(), UpdateError>> {
        let update = self
            .pending_update
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone();
        Box::pin(async move {
            let Some(update) = update else {
                return Err(UpdateError::InstallFailed {
                    reason: "no pending update to install".to_owned(),
                });
            };
            update.install(payload).map_err(|e| match e {
                PluginError::Minisign(_)
                | PluginError::Base64(_)
                | PluginError::SignatureUtf8(_)
                | PluginError::SignedVersionMismatch { .. }
                | PluginError::MissingSignedVersion => UpdateError::SignatureInvalid,
                _ => UpdateError::InstallFailed {
                    reason: "install failed".to_owned(),
                },
            })
        })
    }
}
