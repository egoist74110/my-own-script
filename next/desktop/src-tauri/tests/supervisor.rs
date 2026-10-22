//! Supervisor behavior against a fake backend (tests/fixtures/fake_backend.py).
//! No GUI, no real ports, no network.

use std::{
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use tempfile::TempDir;
use toolbox_desktop_lib::backend::{
    group_alive, BackendCommand, ConnectionError, State, Status, Supervisor, SupervisorConfig,
};

const TOKEN: &str = "TESTTOKEN-4f9a1c77e2b84d0a";

struct Harness {
    dir: TempDir,
    logs: Arc<Mutex<Vec<String>>>,
    statuses: Arc<Mutex<Vec<Status>>>,
    cfg: SupervisorConfig,
}

fn fixture() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fake_backend.py")
}

impl Harness {
    fn new(mode: &str) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let command = BackendCommand::new("/usr/bin/env")
            .args(["python3".into(), fixture().into_os_string()])
            .env("FAKE_MODE", mode)
            .env("FAKE_TOKEN", TOKEN)
            .env("FAKE_STATE_DIR", dir.path());
        let mut cfg = SupervisorConfig::new(command);
        cfg.ready_timeout = Duration::from_secs(5);
        cfg.backoff_base = Duration::from_millis(100);
        cfg.backoff_max = Duration::from_millis(800);
        cfg.stable_reset = Duration::from_secs(60);
        cfg.term_grace = Duration::from_millis(700);
        cfg.connection_wait = Duration::from_secs(5);
        let logs = Arc::new(Mutex::new(Vec::new()));
        let statuses = Arc::new(Mutex::new(Vec::new()));
        {
            let logs = logs.clone();
            cfg.log = Arc::new(move |l| logs.lock().unwrap().push(l.to_owned()));
            let statuses = statuses.clone();
            cfg.on_status = Some(Arc::new(move |s| statuses.lock().unwrap().push(s.clone())));
        }
        Self {
            dir,
            logs,
            statuses,
            cfg,
        }
    }

    fn env(mut self, k: &str, v: &str) -> Self {
        self.cfg.command = self.cfg.command.clone().env(k, v);
        self
    }

    fn start(&self) -> Supervisor {
        Supervisor::start(self.cfg.clone())
    }

    fn marker_lines(&self, name: &str) -> Vec<String> {
        fs::read_to_string(self.dir.path().join(name))
            .map(|s| s.lines().map(str::to_owned).collect())
            .unwrap_or_default()
    }

    fn logs(&self) -> Vec<String> {
        self.logs.lock().unwrap().clone()
    }

    fn statuses(&self) -> Vec<Status> {
        self.statuses.lock().unwrap().clone()
    }

    fn pids(&self) -> Vec<i32> {
        self.marker_lines("pids")
            .iter()
            .filter_map(|l| l.parse().ok())
            .collect()
    }

    /// Token must be absent from every log line and every status payload.
    fn assert_no_token_leak(&self) {
        for l in self.logs() {
            assert!(!l.contains(TOKEN), "token leaked in log: {l}");
        }
        for s in self.statuses() {
            let json = serde_json::to_string(&s).unwrap();
            assert!(!json.contains(TOKEN), "token leaked in status: {json}");
            let v: serde_json::Value = serde_json::from_str(&json).unwrap();
            let mut keys: Vec<&str> = v.as_object().unwrap().keys().map(String::as_str).collect();
            keys.sort_unstable();
            assert_eq!(keys, ["pid", "restarts", "state"]);
        }
    }
}

async fn wait_status(sup: &Supervisor, secs: u64, pred: impl Fn(&Status) -> bool) -> Status {
    let mut rx = sup.subscribe();
    let r = tokio::time::timeout(Duration::from_secs(secs), rx.wait_for(|s| pred(s)))
        .await
        .unwrap_or_else(|_| panic!("timed out waiting for status; last = {:?}", sup.status()))
        .unwrap();
    r.clone()
}

fn pid_alive(pid: i32) -> bool {
    // SAFETY: signal 0 only probes existence.
    unsafe { libc::kill(pid, 0) == 0 }
}

async fn wait_pid_dead(pid: i32) -> bool {
    for _ in 0..100 {
        if !pid_alive(pid) {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    false
}

// ---------------------------------------------------------------------------

#[tokio::test]
async fn handshake_provides_connection_and_ready_status() {
    let h = Harness::new("ok");
    let sup = h.start();
    let conn = sup.connection(Duration::from_secs(5)).await.unwrap();
    assert_eq!(conn.token, TOKEN);
    assert_eq!(conn.port, 40001);
    let st = wait_status(&sup, 5, |s| s.state == State::Ready).await;
    assert_eq!(st.restarts, 0);
    let pid = st.pid.expect("ready status carries pid");
    assert_eq!(h.pids(), vec![pid as i32]); // child pid == fixture's own pid
    sup.shutdown().await;
    assert!(!group_alive(pid as i32));
    h.assert_no_token_leak();
}

#[tokio::test]
async fn child_runs_in_its_own_process_group() {
    let h = Harness::new("ok");
    let sup = h.start();
    let st = wait_status(&sup, 5, |s| s.state == State::Ready).await;
    let pid = st.pid.unwrap() as i32;
    // SAFETY: getpgid on a live child.
    let child_pgid = unsafe { libc::getpgid(pid) };
    let own_pgid = unsafe { libc::getpgid(0) };
    assert_eq!(child_pgid, pid);
    assert_ne!(child_pgid, own_pgid);
    sup.shutdown().await;
}

#[tokio::test]
async fn closing_stdin_makes_a_well_behaved_backend_exit_by_itself() {
    // stdin_only ignores SIGTERM, so a clean (non-killed) exit proves the
    // shell closed its stdin handle.
    let mut h = Harness::new("stdin_only");
    h.cfg.term_grace = Duration::from_secs(4);
    let sup = h.start();
    let pid = wait_status(&sup, 5, |s| s.state == State::Ready)
        .await
        .pid
        .unwrap() as i32;
    let t0 = Instant::now();
    sup.shutdown().await;
    assert!(t0.elapsed() < Duration::from_secs(3), "{:?}", t0.elapsed());
    assert_eq!(h.marker_lines("stdin_eof"), vec!["EOF"]);
    assert!(!group_alive(pid));
    assert_eq!(sup.status().state, State::Stopped);
    assert!(sup.is_stopped());
}

#[tokio::test]
async fn sigterm_stops_a_backend_that_only_handles_the_signal() {
    let h = Harness::new("ok");
    let sup = h.start();
    let pid = wait_status(&sup, 5, |s| s.state == State::Ready)
        .await
        .pid
        .unwrap() as i32;
    let t0 = Instant::now();
    sup.shutdown().await;
    assert!(!group_alive(pid));
    // The fake exits 0 on TERM or on stdin EOF; needing SIGKILL would have
    // cost the whole 700ms grace.
    assert!(
        t0.elapsed() < Duration::from_millis(650),
        "{:?}",
        t0.elapsed()
    );
}

#[tokio::test]
async fn sigkill_after_default_five_second_grace_leaves_no_group_members() {
    let mut h = Harness::new("ignore_term");
    h.cfg.term_grace = Duration::from_secs(5); // contract value
    let sup = h.start();
    let pid = wait_status(&sup, 5, |s| s.state == State::Ready)
        .await
        .pid
        .unwrap() as i32;
    let gc: i32 = h.marker_lines("grandchild.pid")[0].parse().unwrap();
    assert!(pid_alive(gc));
    let t0 = Instant::now();
    sup.shutdown().await;
    let took = t0.elapsed();
    assert!(
        took >= Duration::from_millis(4900),
        "killed too early: {took:?}"
    );
    assert!(took < Duration::from_secs(8), "took too long: {took:?}");
    assert!(!group_alive(pid), "process group still alive");
    assert!(wait_pid_dead(gc).await, "grandchild survived");
    assert_eq!(h.marker_lines("term"), vec!["TERM"]);
}

#[tokio::test]
async fn crash_triggers_backoff_restarts_with_increasing_counter() {
    let h = Harness::new("ok").env("FAKE_CRASH_RUNS", "2");
    let sup = h.start();
    let t0 = Instant::now();
    let st = wait_status(&sup, 10, |s| s.state == State::Ready && s.restarts == 2).await;
    let elapsed = t0.elapsed();
    // delays: 100ms then 200ms
    assert!(elapsed >= Duration::from_millis(300), "{elapsed:?}");
    assert_eq!(st.restarts, 2);
    assert_eq!(h.pids().len(), 3);
    let conn = sup.connection(Duration::from_secs(2)).await.unwrap();
    assert_eq!(conn.port, 40003);

    let seen = h.statuses();
    let restarting: Vec<u32> = seen
        .iter()
        .filter(|s| s.state == State::Restarting)
        .map(|s| s.restarts)
        .collect();
    assert_eq!(restarting, vec![1, 2]);
    assert!(seen
        .iter()
        .filter(|s| s.state == State::Restarting)
        .all(|s| s.pid.is_none()));
    let delays: Vec<String> = h
        .logs()
        .into_iter()
        .filter(|l| l.contains("restart #"))
        .collect();
    assert!(delays[0].contains("in 100ms"), "{delays:?}");
    assert!(delays[1].contains("in 200ms"), "{delays:?}");
    sup.shutdown().await;
    h.assert_no_token_leak();
}

#[tokio::test]
async fn backoff_is_capped_and_resets_after_stable_period() {
    // Without stability: 100,200,400,800,800...
    let h = Harness::new("ok")
        .env("FAKE_CRASH_RUNS", "100")
        .env("FAKE_CRASH_DELAY", "0.05");
    let sup = h.start();
    wait_status(&sup, 15, |s| s.restarts >= 5).await;
    sup.shutdown().await;
    let ms: Vec<String> = h
        .logs()
        .into_iter()
        .filter(|l| l.contains("restart #"))
        .map(|l| l.rsplit("in ").next().unwrap().to_owned())
        .collect();
    assert_eq!(&ms[..5], ["100ms", "200ms", "400ms", "800ms", "800ms"]);

    // With a 100ms stability window and a backend that stays up 400ms, the
    // sequence never grows.
    let mut h = Harness::new("ok")
        .env("FAKE_CRASH_RUNS", "100")
        .env("FAKE_CRASH_DELAY", "0.4");
    h.cfg.stable_reset = Duration::from_millis(100);
    let sup = h.start();
    wait_status(&sup, 15, |s| s.restarts >= 3).await;
    sup.shutdown().await;
    let ms: Vec<String> = h
        .logs()
        .into_iter()
        .filter(|l| l.contains("restart #"))
        .map(|l| l.rsplit("in ").next().unwrap().to_owned())
        .collect();
    assert!(ms.len() >= 3);
    assert!(ms.iter().all(|m| m == "100ms"), "{ms:?}");
}

#[tokio::test]
async fn handshake_timeout_restarts_and_never_publishes_a_connection() {
    let mut h = Harness::new("no_output");
    h.cfg.ready_timeout = Duration::from_millis(300);
    let sup = h.start();
    wait_status(&sup, 10, |s| s.restarts >= 1).await;
    assert_eq!(
        sup.connection(Duration::from_millis(200)).await,
        Err(ConnectionError::Timeout)
    );
    assert!(h
        .logs()
        .iter()
        .any(|l| l.contains("no READY line within 300ms")));
    assert!(h.statuses().iter().all(|s| s.state != State::Ready));
    sup.shutdown().await;
    for pid in h.pids() {
        assert!(!group_alive(pid), "hung backend group {pid} survived");
    }
}

#[tokio::test]
async fn invalid_ready_lines_are_rejected_without_logging_their_content() {
    for mode in ["bad_line", "long_line"] {
        let h = Harness::new(mode);
        let sup = h.start();
        wait_status(&sup, 10, |s| s.restarts >= 1).await;
        assert!(
            h.statuses().iter().all(|s| s.state != State::Ready),
            "{mode}"
        );
        assert!(
            h.logs().iter().any(|l| l.contains("handshake failed")),
            "{mode}"
        );
        for l in h.logs() {
            assert!(!l.contains("garbage-secret-content"), "{l}");
            assert!(l.len() < 400, "log line too long: {}", l.len());
        }
        sup.shutdown().await;
        for pid in h.pids() {
            assert!(!group_alive(pid));
        }
    }
}

#[tokio::test]
async fn backend_exiting_before_ready_is_a_failed_handshake_and_restarted() {
    let h = Harness::new("ok").env("FAKE_FAIL_BEFORE_READY_RUNS", "2");
    let sup = h.start();
    // connection() must ride out the failed starts and return the third run's.
    let conn = sup.connection(Duration::from_secs(5)).await.unwrap();
    assert_eq!(conn.port, 40003);
    assert_eq!(sup.status().restarts, 2);
    sup.shutdown().await;
}

#[tokio::test]
async fn stderr_is_forwarded_and_token_redacted() {
    let h = Harness::new("leak_token");
    let sup = h.start();
    wait_status(&sup, 5, |s| s.state == State::Ready).await;
    // give the forwarder a moment for the second stderr line
    for _ in 0..50 {
        if h.logs().iter().any(|l| l.contains("leaked token=")) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    sup.shutdown().await;
    let logs = h.logs();
    assert!(
        logs.iter()
            .any(|l| l == "backend: leaked token=[REDACTED] end"),
        "{logs:?}"
    );
    assert!(logs
        .iter()
        .any(|l| l.starts_with("backend: fake backend starting")));
    h.assert_no_token_leak();
}

#[tokio::test]
async fn stdout_after_ready_is_drained_logged_without_content() {
    let h = Harness::new("stdout_after_ready");
    let sup = h.start();
    wait_status(&sup, 5, |s| s.state == State::Ready).await;
    for _ in 0..50 {
        if h.logs().iter().any(|l| l.contains("unexpected stdout")) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert_eq!(sup.status().state, State::Ready);
    assert!(h.logs().iter().any(|l| l.contains("unexpected stdout")));
    assert!(h
        .logs()
        .iter()
        .all(|l| !l.contains("unexpected-stdout-content")));
    sup.shutdown().await;
}

#[tokio::test]
async fn spawn_failure_is_retried_and_shutdown_still_works() {
    let mut h = Harness::new("ok");
    h.cfg.command = BackendCommand::new("/nonexistent/definitely-not-here");
    let sup = h.start();
    wait_status(&sup, 5, |s| s.restarts >= 2).await;
    assert!(h
        .logs()
        .iter()
        .any(|l| l.contains("failed to spawn backend")));
    sup.shutdown().await;
    assert_eq!(sup.status().state, State::Stopped);
}

#[tokio::test]
async fn shutdown_is_executed_once_even_when_called_concurrently() {
    let h = Harness::new("ignore_term");
    let sup = Arc::new(h.start());
    let pid = wait_status(&sup, 5, |s| s.state == State::Ready)
        .await
        .pid
        .unwrap() as i32;
    let calls: Vec<_> = (0..4)
        .map(|_| {
            let s = sup.clone();
            tokio::spawn(async move { s.shutdown().await })
        })
        .collect();
    for c in calls {
        c.await.unwrap();
    }
    sup.shutdown().await; // and once more after completion
    assert!(!group_alive(pid));
    assert_eq!(
        h.marker_lines("term"),
        vec!["TERM"],
        "SIGTERM sent more than once"
    );
    let seq: Vec<State> = h.statuses().iter().map(|s| s.state).collect();
    let stopping = seq.iter().position(|s| *s == State::Stopping).unwrap();
    assert!(
        seq[stopping..]
            .iter()
            .all(|s| matches!(s, State::Stopping | State::Stopped)),
        "{seq:?}"
    );
    assert_eq!(*seq.last().unwrap(), State::Stopped);
    assert_eq!(
        seq.iter().filter(|s| **s == State::Stopping).count(),
        1,
        "{seq:?}"
    );
}

#[tokio::test]
async fn shutdown_during_backoff_cancels_the_pending_restart() {
    let mut h = Harness::new("ok").env("FAKE_CRASH_RUNS", "100");
    h.cfg.backoff_base = Duration::from_secs(30);
    h.cfg.backoff_max = Duration::from_secs(30);
    let sup = h.start();
    wait_status(&sup, 5, |s| s.state == State::Restarting).await;
    let t0 = Instant::now();
    sup.shutdown().await;
    assert!(t0.elapsed() < Duration::from_secs(2));
    assert_eq!(h.pids().len(), 1, "a restart slipped in after shutdown");
    assert_eq!(sup.status().state, State::Stopped);
    assert_eq!(
        sup.connection(Duration::from_millis(100)).await,
        Err(ConnectionError::ShuttingDown)
    );
}

#[tokio::test]
async fn shutdown_during_handshake_stops_the_child_promptly() {
    let mut h = Harness::new("no_output");
    h.cfg.ready_timeout = Duration::from_secs(20);
    let sup = h.start();
    wait_status(&sup, 5, |s| s.state == State::Starting && s.pid.is_some()).await;
    let t0 = Instant::now();
    sup.shutdown().await;
    assert!(t0.elapsed() < Duration::from_secs(3), "{:?}", t0.elapsed());
    for pid in h.pids() {
        assert!(!group_alive(pid));
    }
}

#[tokio::test]
async fn restart_storm_racing_with_shutdown_leaves_no_survivors() {
    for round in 0..4 {
        let mut h = Harness::new("ok")
            .env("FAKE_CRASH_RUNS", "1000")
            .env("FAKE_CRASH_DELAY", "0");
        h.cfg.backoff_base = Duration::from_millis(1);
        h.cfg.backoff_max = Duration::from_millis(5);
        let sup = h.start();
        tokio::time::sleep(Duration::from_millis(250 + round * 40)).await;
        sup.shutdown().await;
        let before = h.pids().len();
        tokio::time::sleep(Duration::from_millis(200)).await;
        assert_eq!(
            h.pids().len(),
            before,
            "spawn after shutdown (round {round})"
        );
        for pid in h.pids() {
            assert!(wait_pid_dead(pid).await, "pid {pid} alive after shutdown");
        }
        assert_eq!(sup.status().state, State::Stopped);
    }
}

#[tokio::test]
async fn unexpected_exit_cleans_up_leftover_group_members() {
    let h = Harness::new("grandchild_crash");
    let sup = h.start();
    wait_status(&sup, 5, |s| s.restarts >= 1).await;
    let gc: i32 = h.marker_lines("grandchild.pid")[0].parse().unwrap();
    assert!(
        wait_pid_dead(gc).await,
        "orphaned grandchild was not reclaimed"
    );
    sup.shutdown().await;
    for pid in h.pids() {
        assert!(!group_alive(pid));
    }
    let gcs = h.marker_lines("grandchild.pid");
    for g in gcs {
        assert!(wait_pid_dead(g.parse().unwrap()).await);
    }
}

#[tokio::test]
async fn dropping_the_supervisor_still_reclaims_the_backend() {
    let h = Harness::new("ok");
    let sup = h.start();
    let pid = wait_status(&sup, 5, |s| s.state == State::Ready)
        .await
        .pid
        .unwrap() as i32;
    drop(sup);
    let mut gone = false;
    for _ in 0..100 {
        if !group_alive(pid) {
            gone = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    assert!(gone);
}
