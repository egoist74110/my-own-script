//! Unit and state-machine tests for in-app updater (fake UpdateSource, no network).

use std::{
    future::Future,
    pin::Pin,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};

use tokio::sync::{watch, Notify};
use toolbox_desktop_lib::updater::{
    has_updater_plugin_config, is_packaged_executable, truncate_notes, UpdateCoordinator,
    UpdateError, UpdateErrorCode, UpdateInfo, UpdateProgress, UpdateSource, UpdateState,
    UpdateStatus, MAX_NOTES_CHARS, UPDATE_STATUS_EVENT,
};

type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

#[derive(Clone)]
struct FakeSource {
    check_calls: Arc<AtomicUsize>,
    download_calls: Arc<AtomicUsize>,
    install_calls: Arc<AtomicUsize>,
    installed_payloads: Arc<Mutex<Vec<Vec<u8>>>>,
    check_mode: Arc<Mutex<CheckMode>>,
    download_mode: Arc<Mutex<DownloadMode>>,
    install_mode: Arc<Mutex<Result<(), UpdateError>>>,
}

impl Default for FakeSource {
    fn default() -> Self {
        Self {
            check_calls: Arc::default(),
            download_calls: Arc::default(),
            install_calls: Arc::default(),
            installed_payloads: Arc::default(),
            check_mode: Arc::default(),
            download_mode: Arc::default(),
            install_mode: Arc::new(Mutex::new(Ok(()))),
        }
    }
}

#[derive(Clone, Default)]
enum CheckMode {
    #[default]
    UpToDate,
    Available(UpdateInfo),
    Error(UpdateError),
    HoldUntil(Arc<Notify>, Result<Option<UpdateInfo>, UpdateError>),
}

#[derive(Clone)]
enum DownloadMode {
    Chunks {
        chunks: Vec<(usize, Option<u64>, Duration)>,
        payload: Vec<u8>,
        after_verify: Result<(), UpdateError>,
    },
    HoldUntil {
        first_chunk: Option<(usize, Option<u64>)>,
        started: Arc<Notify>,
        gate: Arc<Notify>,
        result: Result<Vec<u8>, UpdateError>,
    },
    Error(UpdateError),
}

impl Default for DownloadMode {
    fn default() -> Self {
        Self::Chunks {
            chunks: vec![
                (50, Some(100), Duration::ZERO),
                (50, Some(100), Duration::ZERO),
            ],
            payload: b"verified-app-tar-gz".to_vec(),
            after_verify: Ok(()),
        }
    }
}

impl UpdateSource for FakeSource {
    fn check(&self) -> BoxFuture<'_, Result<Option<UpdateInfo>, UpdateError>> {
        self.check_calls.fetch_add(1, Ordering::SeqCst);
        let mode = self.check_mode.lock().unwrap().clone();
        Box::pin(async move {
            match mode {
                CheckMode::UpToDate => Ok(None),
                CheckMode::Available(info) => Ok(Some(info)),
                CheckMode::Error(e) => Err(e),
                CheckMode::HoldUntil(notify, res) => {
                    notify.notified().await;
                    res
                }
            }
        })
    }

    fn download(
        &self,
        _info: &UpdateInfo,
        mut progress_cb: Box<dyn FnMut(usize, Option<u64>) + Send>,
        mut cancel: watch::Receiver<bool>,
    ) -> BoxFuture<'_, Result<Vec<u8>, UpdateError>> {
        self.download_calls.fetch_add(1, Ordering::SeqCst);
        let mode = self.download_mode.lock().unwrap().clone();
        Box::pin(async move {
            match mode {
                DownloadMode::Chunks {
                    chunks,
                    payload,
                    after_verify,
                } => {
                    for (len, total, delay) in chunks {
                        if !delay.is_zero() {
                            tokio::select! {
                                _ = tokio::time::sleep(delay) => {}
                                _ = cancel.wait_for(|c| *c) => return Err(UpdateError::Cancelled),
                            }
                        }
                        if *cancel.borrow() {
                            return Err(UpdateError::Cancelled);
                        }
                        progress_cb(len, total);
                    }
                    after_verify?;
                    Ok(payload)
                }
                DownloadMode::HoldUntil {
                    first_chunk,
                    started,
                    gate,
                    result,
                } => {
                    if let Some((len, total)) = first_chunk {
                        progress_cb(len, total);
                    }
                    started.notify_waiters();
                    tokio::select! {
                        _ = gate.notified() => result,
                        _ = cancel.wait_for(|c| *c) => Err(UpdateError::Cancelled),
                    }
                }
                DownloadMode::Error(e) => Err(e),
            }
        })
    }

    fn install(&self, payload: Vec<u8>) -> BoxFuture<'_, Result<(), UpdateError>> {
        self.install_calls.fetch_add(1, Ordering::SeqCst);
        self.installed_payloads.lock().unwrap().push(payload);
        let res = self.install_mode.lock().unwrap().clone();
        Box::pin(async move { res })
    }
}

struct TestRig {
    source: FakeSource,
    events: Arc<Mutex<Vec<UpdateStatus>>>,
    logs: Arc<Mutex<Vec<String>>>,
    restarts: Arc<AtomicUsize>,
    coordinator: UpdateCoordinator,
}

impl TestRig {
    fn new_enabled() -> Self {
        Self::with_disabled(None)
    }

    fn with_disabled(disabled_reason: Option<UpdateErrorCode>) -> Self {
        let source = FakeSource {
            install_mode: Arc::new(Mutex::new(Ok(()))),
            ..Default::default()
        };
        let events = Arc::new(Mutex::new(Vec::new()));
        let logs = Arc::new(Mutex::new(Vec::new()));
        let restarts = Arc::new(AtomicUsize::new(0));

        let events_cb = events.clone();
        let logs_cb = logs.clone();
        let restarts_cb = restarts.clone();

        let coordinator = UpdateCoordinator::new(
            "1.0.0".to_owned(),
            disabled_reason,
            Arc::new(source.clone()),
            Arc::new(move |status| {
                events_cb.lock().unwrap().push(status.clone());
            }),
            Arc::new(move |line| {
                logs_cb.lock().unwrap().push(line.to_owned());
            }),
            Arc::new(move || {
                let restarts_cb = restarts_cb.clone();
                Box::pin(async move {
                    restarts_cb.fetch_add(1, Ordering::SeqCst);
                })
            }),
        );

        Self {
            source,
            events,
            logs,
            restarts,
            coordinator,
        }
    }

    fn emitted(&self) -> Vec<UpdateStatus> {
        self.events.lock().unwrap().clone()
    }

    fn logs(&self) -> Vec<String> {
        self.logs.lock().unwrap().clone()
    }
}

fn assert_status_json_contract(status: &UpdateStatus) {
    let raw = serde_json::to_string(status).unwrap();
    for forbidden in ["url", "signature", "endpoint", "SECRET_SIG", "https://"] {
        assert!(
            !raw.contains(forbidden),
            "status JSON must not contain {forbidden:?}: {raw}"
        );
    }
    let val: serde_json::Value = serde_json::from_str(&raw).unwrap();
    let obj = val.as_object().unwrap();
    let mut keys: Vec<&str> = obj.keys().map(String::as_str).collect();
    keys.sort_unstable();
    assert_eq!(
        keys,
        vec![
            "available_version",
            "checked_at",
            "current_version",
            "error_code",
            "notes",
            "progress",
            "state",
        ]
    );
    if let Some(p) = obj["progress"].as_object() {
        let mut pkeys: Vec<&str> = p.keys().map(String::as_str).collect();
        pkeys.sort_unstable();
        assert_eq!(pkeys, vec!["downloaded", "total"]);
    }
}

#[test]
fn status_event_name_and_serialization_match_frozen_contract() {
    assert_eq!(UPDATE_STATUS_EVENT, "update://status");
    let st = UpdateStatus {
        state: UpdateState::Downloading,
        current_version: "1.0.0".into(),
        available_version: Some("1.1.0".into()),
        notes: Some("notes".into()),
        progress: Some(UpdateProgress {
            downloaded: 128,
            total: Some(1024),
        }),
        error_code: None,
        checked_at: Some(1_700_000_000),
    };
    assert_status_json_contract(&st);
    let v = serde_json::to_value(&st).unwrap();
    assert_eq!(v["state"], "downloading");
    assert_eq!(v["progress"]["downloaded"], 128);
    assert_eq!(v["progress"]["total"], 1024);

    for (state, expected) in [
        (UpdateState::Disabled, "disabled"),
        (UpdateState::Idle, "idle"),
        (UpdateState::Checking, "checking"),
        (UpdateState::UpToDate, "up_to_date"),
        (UpdateState::Available, "available"),
        (UpdateState::Downloading, "downloading"),
        (UpdateState::Ready, "ready"),
        (UpdateState::Error, "error"),
    ] {
        assert_eq!(serde_json::to_value(state).unwrap(), expected);
    }

    for (code, expected) in [
        (
            UpdateErrorCode::UpdateNotConfigured,
            "update_not_configured",
        ),
        (
            UpdateErrorCode::UpdateUnsupportedDev,
            "update_unsupported_dev",
        ),
        (UpdateErrorCode::UpdateBusy, "update_busy"),
        (UpdateErrorCode::UpdateCheckFailed, "update_check_failed"),
        (
            UpdateErrorCode::UpdateDownloadFailed,
            "update_download_failed",
        ),
        (
            UpdateErrorCode::UpdateSignatureInvalid,
            "update_signature_invalid",
        ),
        (
            UpdateErrorCode::UpdateInstallFailed,
            "update_install_failed",
        ),
        (UpdateErrorCode::UpdateCancelled, "update_cancelled"),
    ] {
        assert_eq!(serde_json::to_value(code).unwrap(), expected);
        assert_eq!(code.as_str(), expected);
    }
}

#[test]
fn notes_truncation_caps_at_2000_chars() {
    let long = "测".repeat(2500);
    let truncated = truncate_notes(Some(&long)).unwrap();
    assert_eq!(truncated.chars().count(), MAX_NOTES_CHARS);
    assert_eq!(MAX_NOTES_CHARS, 2000);
    assert_eq!(truncate_notes(Some("short")).as_deref(), Some("short"));
    assert!(truncate_notes(None).is_none());
}

#[test]
fn packaged_and_plugin_config_detection() {
    let temp = tempfile::tempdir().unwrap();
    let contents = temp.path().join("TOOLBOX.app/Contents");
    let exe = contents.join("MacOS/toolbox-desktop");
    std::fs::create_dir_all(exe.parent().unwrap()).unwrap();
    assert!(!is_packaged_executable(&exe, None));

    let py = contents.join("Resources/backend/bin/python3.14");
    std::fs::create_dir_all(py.parent().unwrap()).unwrap();
    std::fs::write(&py, "").unwrap();
    assert!(is_packaged_executable(&exe, None));
    assert!(is_packaged_executable(&exe, Some("   ")));
    assert!(!is_packaged_executable(&exe, Some("/bin/echo override")));

    let empty_plugins: serde_json::Value = serde_json::json!({});
    assert!(!has_updater_plugin_config(&empty_plugins));

    let incomplete: serde_json::Value = serde_json::json!({
        "updater": { "pubkey": "", "endpoints": [] }
    });
    assert!(!has_updater_plugin_config(&incomplete));

    let configured: serde_json::Value = serde_json::json!({
        "updater": {
            "pubkey": "RWQ...",
            "endpoints": ["https://github.com/OWNER/REPO/releases/latest/download/latest.json"]
        }
    });
    assert!(has_updater_plugin_config(&configured));
}

#[tokio::test]
async fn disabled_modes_never_call_source() {
    for reason in [
        UpdateErrorCode::UpdateNotConfigured,
        UpdateErrorCode::UpdateUnsupportedDev,
    ] {
        let rig = TestRig::with_disabled(Some(reason));
        let st = rig.coordinator.status();
        assert_eq!(st.state, UpdateState::Disabled);
        assert_eq!(st.error_code, Some(reason));
        assert_status_json_contract(&st);

        // check / cancel on disabled return current snapshot with error_code, without calling source
        let checked = rig.coordinator.check().await.unwrap();
        assert_eq!(checked.state, UpdateState::Disabled);
        assert_eq!(checked.error_code, Some(reason));
        assert_eq!(rig.source.check_calls.load(Ordering::SeqCst), 0);

        let install_res = rig.coordinator.install().await;
        match install_res {
            Ok(s) => {
                assert_eq!(s.state, UpdateState::Disabled);
                assert_eq!(s.error_code, Some(reason));
            }
            Err(code) => assert_eq!(code, reason.as_str()),
        }
        assert_eq!(rig.source.download_calls.load(Ordering::SeqCst), 0);
        assert_eq!(rig.source.install_calls.load(Ordering::SeqCst), 0);

        let cancelled = rig.coordinator.cancel();
        assert_eq!(cancelled.state, UpdateState::Disabled);
        assert!(rig.coordinator.restart().await.is_err());
    }
}

#[tokio::test]
async fn check_up_to_date_and_available_and_failure_transitions() {
    let rig = TestRig::new_enabled();
    assert_eq!(rig.coordinator.status().state, UpdateState::Idle);

    // 1. idle -> checking -> up_to_date
    let st = rig.coordinator.check().await.unwrap();
    assert_eq!(st.state, UpdateState::UpToDate);
    assert!(st.available_version.is_none());
    assert!(st.checked_at.is_some());
    assert_eq!(st.error_code, None);
    assert_status_json_contract(&st);

    // 2. up_to_date -> checking -> available (with notes truncation)
    *rig.source.check_mode.lock().unwrap() = CheckMode::Available(UpdateInfo {
        version: "1.2.0".into(),
        notes: Some("x".repeat(2200)),
        host: Some("github.com".into()),
    });
    let st = rig.coordinator.check().await.unwrap();
    assert_eq!(st.state, UpdateState::Available);
    assert_eq!(st.available_version.as_deref(), Some("1.2.0"));
    assert_eq!(st.notes.as_ref().unwrap().chars().count(), 2000);
    assert_eq!(st.error_code, None);
    assert_status_json_contract(&st);

    // 3. check fails -> error(update_check_failed), then retry check succeeds
    let rig2 = TestRig::new_enabled();
    *rig2.source.check_mode.lock().unwrap() = CheckMode::Error(UpdateError::CheckFailed {
        host: Some("github.com".into()),
        reason: "network down".into(),
    });
    let st_err = rig2.coordinator.check().await.unwrap();
    assert_eq!(st_err.state, UpdateState::Error);
    assert_eq!(st_err.error_code, Some(UpdateErrorCode::UpdateCheckFailed));
    assert_status_json_contract(&st_err);

    // Retry from error -> up_to_date
    *rig2.source.check_mode.lock().unwrap() = CheckMode::UpToDate;
    let st_ok = rig2.coordinator.check().await.unwrap();
    assert_eq!(st_ok.state, UpdateState::UpToDate);
    assert_eq!(st_ok.error_code, None);
}

#[tokio::test]
async fn single_flight_mutex_returns_update_busy_during_check_and_download() {
    let rig = TestRig::new_enabled();
    let gate = Arc::new(Notify::new());
    *rig.source.check_mode.lock().unwrap() = CheckMode::HoldUntil(
        gate.clone(),
        Ok(Some(UpdateInfo {
            version: "1.1.0".into(),
            notes: None,
            host: Some("github.com".into()),
        })),
    );

    let coord = rig.coordinator.clone();
    let check_task = tokio::spawn(async move { coord.check().await });

    // Wait until state enters Checking
    for _ in 0..50 {
        if rig.coordinator.status().state == UpdateState::Checking {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert_eq!(rig.coordinator.status().state, UpdateState::Checking);

    // Concurrent check or install must return update_busy
    assert_eq!(
        rig.coordinator.check().await.unwrap_err(),
        "update_busy".to_owned()
    );
    assert_eq!(
        rig.coordinator.install().await.unwrap_err(),
        "update_busy".to_owned()
    );

    gate.notify_waiters();
    let st = check_task.await.unwrap().unwrap();
    assert_eq!(st.state, UpdateState::Available);
}

#[tokio::test]
async fn cancel_during_checking_returns_to_idle_with_update_cancelled() {
    let rig = TestRig::new_enabled();
    let gate = Arc::new(Notify::new());
    *rig.source.check_mode.lock().unwrap() = CheckMode::HoldUntil(gate.clone(), Ok(None));

    let coord = rig.coordinator.clone();
    let check_task = tokio::spawn(async move { coord.check().await });

    for _ in 0..50 {
        if rig.coordinator.status().state == UpdateState::Checking {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let cancelled_st = rig.coordinator.cancel();
    assert_eq!(cancelled_st.state, UpdateState::Idle);
    assert_eq!(
        cancelled_st.error_code,
        Some(UpdateErrorCode::UpdateCancelled)
    );

    let check_res = check_task.await.unwrap().unwrap();
    assert_eq!(check_res.state, UpdateState::Idle);
    assert_eq!(check_res.error_code, Some(UpdateErrorCode::UpdateCancelled));
}

#[tokio::test]
async fn cancel_during_downloading_does_not_install_and_remains_retryable_from_available() {
    let rig = TestRig::new_enabled();
    *rig.source.check_mode.lock().unwrap() = CheckMode::Available(UpdateInfo {
        version: "1.3.0".into(),
        notes: Some("Release 1.3.0".into()),
        host: Some("github.com".into()),
    });
    let st = rig.coordinator.check().await.unwrap();
    assert_eq!(st.state, UpdateState::Available);

    let started = Arc::new(Notify::new());
    let gate = Arc::new(Notify::new());
    *rig.source.download_mode.lock().unwrap() = DownloadMode::HoldUntil {
        first_chunk: Some((25, Some(100))),
        started: started.clone(),
        gate: gate.clone(),
        result: Ok(b"payload".to_vec()),
    };

    let coord = rig.coordinator.clone();
    let install_task = tokio::spawn(async move { coord.install().await });
    started.notified().await;
    assert_eq!(rig.coordinator.status().state, UpdateState::Downloading);

    let after_cancel = rig.coordinator.cancel();
    assert_eq!(after_cancel.state, UpdateState::Available);
    assert_eq!(after_cancel.available_version.as_deref(), Some("1.3.0"));
    assert_eq!(
        after_cancel.error_code,
        Some(UpdateErrorCode::UpdateCancelled)
    );
    assert!(after_cancel.progress.is_none());

    let task_out = install_task.await.unwrap().unwrap();
    assert_eq!(task_out.state, UpdateState::Available);
    assert_eq!(rig.source.install_calls.load(Ordering::SeqCst), 0);

    // Retry install from Available succeeds -> Ready
    *rig.source.download_mode.lock().unwrap() = DownloadMode::default();
    let ready = rig.coordinator.install().await.unwrap();
    assert_eq!(ready.state, UpdateState::Ready);
    assert_eq!(ready.error_code, None);
    assert_eq!(rig.source.install_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn signature_invalid_and_download_or_install_failures_keep_old_version_and_allow_retry() {
    let rig = TestRig::new_enabled();
    *rig.source.check_mode.lock().unwrap() = CheckMode::Available(UpdateInfo {
        version: "1.4.0".into(),
        notes: None,
        host: Some("github.com".into()),
    });
    rig.coordinator.check().await.unwrap();

    // 1. Signature invalid during download verification -> never calls install, returns to Available (retryable) with update_signature_invalid
    *rig.source.download_mode.lock().unwrap() = DownloadMode::Chunks {
        chunks: vec![(100, Some(100), Duration::ZERO)],
        payload: b"tampered".to_vec(),
        after_verify: Err(UpdateError::SignatureInvalid),
    };
    let sig_st = rig.coordinator.install().await.unwrap();
    assert_eq!(sig_st.state, UpdateState::Available);
    assert_eq!(
        sig_st.error_code,
        Some(UpdateErrorCode::UpdateSignatureInvalid)
    );
    assert_eq!(rig.source.install_calls.load(Ordering::SeqCst), 0);

    // 2. Download network failure -> update_download_failed, never calls install, still retryable
    *rig.source.download_mode.lock().unwrap() = DownloadMode::Error(UpdateError::DownloadFailed {
        host: Some("objects.githubusercontent.com".into()),
        reason: "connection reset".into(),
    });
    let dl_st = rig.coordinator.install().await.unwrap();
    assert_eq!(dl_st.state, UpdateState::Available);
    assert_eq!(
        dl_st.error_code,
        Some(UpdateErrorCode::UpdateDownloadFailed)
    );
    assert_eq!(rig.source.install_calls.load(Ordering::SeqCst), 0);

    // 3. Install failure -> update_install_failed, still retryable
    *rig.source.download_mode.lock().unwrap() = DownloadMode::default();
    *rig.source.install_mode.lock().unwrap() = Err(UpdateError::InstallFailed {
        reason: "permission denied".into(),
    });
    let inst_st = rig.coordinator.install().await.unwrap();
    assert_eq!(inst_st.state, UpdateState::Available);
    assert_eq!(
        inst_st.error_code,
        Some(UpdateErrorCode::UpdateInstallFailed)
    );
    assert_eq!(rig.source.install_calls.load(Ordering::SeqCst), 1);

    // 4. Retry install succeeds -> Ready
    *rig.source.install_mode.lock().unwrap() = Ok(());
    let ready_st = rig.coordinator.install().await.unwrap();
    assert_eq!(ready_st.state, UpdateState::Ready);
    assert_eq!(ready_st.error_code, None);
    assert_eq!(rig.source.install_calls.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn progress_events_are_throttled_to_at_most_five_per_second_and_logs_redact_urls() {
    let rig = TestRig::new_enabled();
    *rig.source.check_mode.lock().unwrap() = CheckMode::Available(UpdateInfo {
        version: "1.5.0".into(),
        notes: None,
        host: Some("github.com".into()),
    });
    rig.coordinator.check().await.unwrap();

    // Emit 20 chunks rapidly within ~20ms; at <= 5 events/sec (200ms interval),
    // only the first progress chunk (and at most 1 more) should emit a downloading status event.
    let chunks = (0..20)
        .map(|_| (10usize, Some(200u64), Duration::from_millis(1)))
        .collect();
    *rig.source.download_mode.lock().unwrap() = DownloadMode::Chunks {
        chunks,
        payload: b"ok".to_vec(),
        after_verify: Ok(()),
    };

    let st = rig.coordinator.install().await.unwrap();
    assert_eq!(st.state, UpdateState::Ready);

    let all_events = rig.emitted();
    let downloading_events: Vec<&UpdateStatus> = all_events
        .iter()
        .filter(|e| e.state == UpdateState::Downloading)
        .collect();
    // Initial downloading transition + first chunk (or coalesced): must be <= 3 for a 20ms run
    assert!(
        downloading_events.len() <= 3,
        "expected throttled downloading events <= 3, got {}",
        downloading_events.len()
    );
    for ev in &all_events {
        assert_status_json_contract(ev);
    }
    for line in rig.logs() {
        assert!(!line.contains("https://"), "log leaked full URL: {line}");
        assert!(!line.contains("signature"), "log leaked signature: {line}");
    }
}

#[tokio::test]
async fn restart_only_allowed_in_ready_state_and_invokes_coordinated_quit_once() {
    let rig = TestRig::new_enabled();

    // Idle -> restart fails
    assert!(rig.coordinator.restart().await.is_err());
    assert_eq!(rig.restarts.load(Ordering::SeqCst), 0);

    *rig.source.check_mode.lock().unwrap() = CheckMode::Available(UpdateInfo {
        version: "1.6.0".into(),
        notes: None,
        host: Some("github.com".into()),
    });
    rig.coordinator.check().await.unwrap();

    // Available -> restart fails
    assert!(rig.coordinator.restart().await.is_err());
    assert_eq!(rig.restarts.load(Ordering::SeqCst), 0);

    // Install -> Ready -> restart succeeds and calls coordinated shutdown callback once
    rig.coordinator.install().await.unwrap();
    assert_eq!(rig.coordinator.status().state, UpdateState::Ready);

    // In Ready state, check and install are rejected
    assert!(rig.coordinator.check().await.is_err());
    assert!(rig.coordinator.install().await.is_err());

    rig.coordinator.restart().await.unwrap();
    assert_eq!(rig.restarts.load(Ordering::SeqCst), 1);
}
