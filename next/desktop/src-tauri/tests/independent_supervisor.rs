//! Independent acceptance tests for the S0-C backend supervisor.
//!
//! Written by the independent tester against the public API of
//! `toolbox_desktop_lib::backend` and the stand-in
//! `tests/fixtures/independent/indep_backend.py`. No sockets, no network.
//!
//! Cleanup: every process the stand-in creates is recorded (pid) in the test's
//! own temp dir. Reaping only touches those recorded pids: `killpg` on a
//! recorded leader pgid, and `kill` on a recorded grandchild whose pgid is one
//! of the recorded leaders. Nothing is matched by process name.

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

const TOKEN: &str = "INDEP-TOKEN-7c1e0b5d9a42f836";
const PORT: u16 = 41001;
const GRACE: Duration = Duration::from_millis(500);

struct Run {
    dir: TempDir,
    logs: Arc<Mutex<Vec<String>>>,
    statuses: Arc<Mutex<Vec<Status>>>,
    cfg: SupervisorConfig,
}

fn fixture() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/independent/indep_backend.py")
}

fn pid_alive(pid: i32) -> bool {
    // SAFETY: signal 0 only probes existence.
    unsafe { libc::kill(pid, 0) == 0 }
}

fn read_procs(dir: &Path) -> Vec<(String, i32)> {
    fs::read_to_string(dir.join("procs"))
        .unwrap_or_default()
        .lines()
        .filter_map(|l| {
            let mut it = l.split_whitespace();
            let role = it.next()?.to_owned();
            let pid = it.next()?.parse().ok()?;
            Some((role, pid))
        })
        .collect()
}

impl Run {
    fn new(mode: &str) -> Self {
        let dir = tempfile::tempdir().unwrap();
        let command = BackendCommand::new("/usr/bin/env")
            .args(["python3".into(), fixture().into_os_string()])
            .env("IND_MODE", mode)
            .env("IND_TOKEN", TOKEN)
            .env("IND_STATE_DIR", dir.path());
        let mut cfg = SupervisorConfig::new(command);
        cfg.ready_timeout = Duration::from_secs(3);
        cfg.backoff_base = Duration::from_millis(50);
        cfg.backoff_max = Duration::from_millis(200);
        cfg.stable_reset = Duration::from_secs(60);
        cfg.term_grace = GRACE;
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

    fn env(&mut self, k: &str, v: &str) {
        self.cfg.command = self.cfg.command.clone().env(k, v);
    }

    fn start(&self) -> Supervisor {
        Supervisor::start(self.cfg.clone())
    }

    fn logs(&self) -> Vec<String> {
        self.logs.lock().unwrap().clone()
    }

    fn statuses(&self) -> Vec<Status> {
        self.statuses.lock().unwrap().clone()
    }

    fn leaders(&self) -> Vec<i32> {
        read_procs(self.dir.path())
            .into_iter()
            .filter(|(r, _)| r == "leader")
            .map(|(_, p)| p)
            .collect()
    }

    fn grandchildren(&self) -> Vec<i32> {
        read_procs(self.dir.path())
            .into_iter()
            .filter(|(r, _)| r == "gc")
            .map(|(_, p)| p)
            .collect()
    }

    fn term_count(&self) -> usize {
        fs::read_to_string(self.dir.path().join("term"))
            .map(|s| s.lines().count())
            .unwrap_or(0)
    }

    /// Token must be absent from every log line and every status payload.
    fn assert_no_token_leak(&self) {
        for l in self.logs() {
            assert!(!l.contains(TOKEN), "token leaked in log: {l}");
        }
        for s in self.statuses() {
            let json = serde_json::to_string(&s).unwrap();
            assert!(!json.contains(TOKEN), "token leaked in status: {json}");
        }
    }

    /// Every recorded leader's group and every recorded grandchild must be gone.
    async fn assert_all_gone(&self) {
        for (role, pid) in read_procs(self.dir.path()) {
            if role == "leader" {
                assert!(
                    wait_for(|| !group_alive(pid)).await,
                    "process group {pid} still has live members"
                );
            } else {
                assert!(
                    wait_for(|| !pid_alive(pid)).await,
                    "grandchild {pid} still alive"
                );
            }
        }
    }
}

impl Drop for Run {
    /// Safety net for a failed assertion: reap only the pids this test recorded.
    fn drop(&mut self) {
        let procs = read_procs(self.dir.path());
        let leaders: Vec<i32> = procs
            .iter()
            .filter(|(r, _)| r == "leader")
            .map(|(_, p)| *p)
            .collect();
        for &pid in &leaders {
            if group_alive(pid) {
                // SAFETY: killpg on a pgid this test recorded (leader pid == pgid).
                unsafe {
                    libc::killpg(pid, libc::SIGKILL);
                }
            }
        }
        for (role, pid) in procs {
            if role != "gc" {
                continue;
            }
            // SAFETY: getpgid only queries; kill only if the pid still belongs to
            // one of our recorded groups (guards against pid reuse).
            let pg = unsafe { libc::getpgid(pid) };
            if leaders.contains(&pg) {
                unsafe {
                    libc::kill(pid, libc::SIGKILL);
                }
            }
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

async fn wait_for(cond: impl Fn() -> bool) -> bool {
    for _ in 0..150 {
        if cond() {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    cond()
}

// ---------------------------------------------------------------------------

/// READY followed by more stdout: the backend stays Ready, the connection does
/// not change, and the extra content never reaches the logs or the status.
#[tokio::test]
async fn stdout_after_ready_keeps_ready_state_and_connection_and_hides_content() {
    let r = Run::new("chatter");
    let sup = r.start();
    let c1 = sup.connection(Duration::from_secs(5)).await.unwrap();
    assert_eq!(c1.port, PORT);
    let st = wait_status(&sup, 5, |s| s.state == State::Ready).await;
    let pid = st.pid;

    let started = Instant::now();
    while started.elapsed() < Duration::from_millis(1500) {
        let s = sup.status();
        assert_eq!(s.state, State::Ready, "left Ready after stdout chatter");
        assert_eq!(s.restarts, 0, "restarted after stdout chatter");
        assert_eq!(s.pid, pid, "pid changed after stdout chatter");
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    let c2 = sup.connection(Duration::from_secs(1)).await.unwrap();
    assert_eq!(c1, c2, "connection changed after stdout chatter");

    let logs = r.logs();
    assert!(
        logs.iter()
            .any(|l| l.contains("unexpected stdout byte(s) after READY")),
        "post-READY stdout was not reported: {logs:?}"
    );
    assert!(
        logs.iter().all(|l| !l.contains("CHATTER-SECRET-PAYLOAD")),
        "post-READY stdout content reached the log"
    );
    r.assert_no_token_leak();

    sup.shutdown().await;
    assert_eq!(sup.status().state, State::Stopped);
    r.assert_all_gone().await;
}

/// A backend that never prints READY is failed by the handshake timeout, the
/// supervisor restarts it, and no connection is ever published.
#[tokio::test]
async fn handshake_timeout_restarts_and_never_publishes_a_connection() {
    let mut r = Run::new("silent");
    r.cfg.ready_timeout = Duration::from_millis(300);
    let sup = r.start();

    let err = sup
        .connection(Duration::from_millis(800))
        .await
        .unwrap_err();
    assert_eq!(err, ConnectionError::Timeout);
    wait_status(&sup, 5, |s| s.restarts >= 2).await;
    assert!(
        r.logs()
            .iter()
            .any(|l| l.contains("handshake failed: no READY line within 300ms")),
        "logs = {:?}",
        r.logs()
    );
    assert!(r.statuses().iter().all(|s| s.state != State::Ready));

    sup.shutdown().await;
    r.assert_all_gone().await;
    r.assert_no_token_leak();
}

/// Crash loop with 1-4 ms backoff, shutdown issued in the middle of it: no
/// new backend is spawned after shutdown completes and nothing survives.
#[tokio::test]
async fn restart_storm_racing_shutdown_spawns_nothing_new_and_leaves_no_survivors() {
    let mut r = Run::new("crash_fast");
    r.cfg.backoff_base = Duration::from_millis(1);
    r.cfg.backoff_max = Duration::from_millis(4);
    let sup = r.start();

    wait_status(&sup, 10, |s| s.restarts >= 8).await;
    sup.shutdown().await;
    let spawned = r.leaders().len();
    // 8 observed exits imply at least 8 spawns (a 9th may or may not have started).
    assert!(spawned >= 8, "expected a storm, spawned {spawned}");

    tokio::time::sleep(Duration::from_millis(400)).await;
    assert_eq!(
        r.leaders().len(),
        spawned,
        "a backend was spawned after shutdown"
    );
    assert!(sup.is_stopped());
    assert_eq!(sup.status().state, State::Stopped);
    r.assert_all_gone().await;
    r.assert_no_token_leak();
}

/// A grandchild that ignores SIGTERM and was started while the backend ran:
/// shutdown must SIGKILL it after the grace period, leaving the group empty.
#[tokio::test]
async fn shutdown_reaps_sigterm_ignoring_grandchild_started_while_running() {
    let r = Run::new("grandchild_running");
    let sup = r.start();
    sup.connection(Duration::from_secs(5)).await.unwrap();
    wait_status(&sup, 5, |s| s.state == State::Ready).await;
    assert_eq!(r.grandchildren().len(), 1, "grandchild not recorded");
    let leader = r.leaders()[0];
    assert!(group_alive(leader));

    let t = Instant::now();
    sup.shutdown().await;
    let took = t.elapsed();
    assert!(
        took >= GRACE * 9 / 10,
        "returned before the grace period, so the grandchild cannot have been SIGKILLed: {took:?}"
    );
    assert!(
        took < GRACE + Duration::from_secs(5),
        "shutdown hung: {took:?}"
    );

    r.assert_all_gone().await;
    r.assert_no_token_leak();
}

/// The leader spawns a SIGTERM-ignoring grandchild while shutdown is already
/// in progress (on stdin EOF). The grandchild must not survive the shutdown.
#[tokio::test]
async fn grandchild_spawned_during_shutdown_does_not_survive_it() {
    let r = Run::new("spawn_on_eof");
    let sup = r.start();
    sup.connection(Duration::from_secs(5)).await.unwrap();
    wait_status(&sup, 5, |s| s.state == State::Ready).await;

    let t = Instant::now();
    sup.shutdown().await;
    let took = t.elapsed();
    assert_eq!(
        r.grandchildren().len(),
        1,
        "the leader did not spawn its grandchild during shutdown"
    );
    assert!(took >= GRACE * 9 / 10, "shutdown too fast: {took:?}");
    assert!(
        took < GRACE + Duration::from_secs(5),
        "shutdown hung: {took:?}"
    );

    r.assert_all_gone().await;
    r.assert_no_token_leak();
}

/// Eight concurrent shutdown() calls: the group receives exactly one SIGTERM,
/// every caller returns, and the SIGTERM-ignoring leader ends up SIGKILLed.
#[tokio::test]
async fn concurrent_shutdown_calls_send_sigterm_exactly_once() {
    let r = Run::new("term_count");
    let sup = Arc::new(r.start());
    sup.connection(Duration::from_secs(5)).await.unwrap();

    let mut joins = Vec::new();
    for _ in 0..8 {
        let s = sup.clone();
        joins.push(tokio::spawn(async move { s.shutdown().await }));
    }
    for j in joins {
        tokio::time::timeout(Duration::from_secs(10), j)
            .await
            .expect("a shutdown() caller hung")
            .unwrap();
    }

    assert_eq!(r.term_count(), 1, "SIGTERM was not sent exactly once");
    assert_eq!(sup.status().state, State::Stopped);
    r.assert_all_gone().await;
    r.assert_no_token_leak();
}

/// Each malformed READY payload is rejected with a reason that names the bad
/// field, the backend is never reported Ready, and the token never reaches logs.
#[tokio::test]
async fn invalid_ready_payloads_are_rejected_with_a_field_reason() {
    let cases: &[(&str, &str)] = &[
        (
            r#"TOOLBOX_READY {"v":1,"port":0,"token":"SECRET-IND-TOKEN","pid":7}"#,
            "field `port`",
        ),
        (
            r#"TOOLBOX_READY {"v":1,"port":65536,"token":"SECRET-IND-TOKEN","pid":7}"#,
            "field `port`",
        ),
        (
            r#"TOOLBOX_READY {"v":1,"port":41001,"token":"","pid":7}"#,
            "field `token`",
        ),
        (
            r#"TOOLBOX_READY {"v":2,"port":41001,"token":"SECRET-IND-TOKEN","pid":7}"#,
            "field `v`",
        ),
        (
            r#"TOOLBOX_READY {"v":"1","port":41001,"token":"SECRET-IND-TOKEN","pid":7}"#,
            "field `v`",
        ),
        (
            r#"TOOLBOX_READY {"v":1,"port":41001,"token":"SECRET-IND-TOKEN" "pid":7}"#,
            "not valid JSON",
        ),
        (
            r#"TOOLBOX_READY {"v":1,"port":41001,"token":"SECRET-IND-TOKEN","pid":0}"#,
            "field `pid`",
        ),
        (r#"TOOLBOX_READY [1,"SECRET-IND-TOKEN"]"#, "payload"),
        (
            r#"TOOLBOX_READYX {"v":1,"port":41001,"token":"SECRET-IND-TOKEN","pid":7}"#,
            "not a READY line",
        ),
    ];
    for (line, reason) in cases {
        let mut r = Run::new("raw");
        r.env("IND_RAW_LINE", line);
        let sup = r.start();

        wait_status(&sup, 5, |s| s.restarts >= 1).await;
        let err = sup
            .connection(Duration::from_millis(100))
            .await
            .unwrap_err();
        assert_eq!(err, ConnectionError::Timeout, "case: {line}");
        assert!(
            r.statuses().iter().all(|s| s.state != State::Ready),
            "case reported Ready: {line}"
        );
        let logs = r.logs();
        assert!(
            logs.iter()
                .any(|l| l.contains("handshake failed") && l.contains(reason)),
            "case: {line}; expected reason containing {reason:?}; logs = {logs:?}"
        );
        assert!(
            logs.iter().all(|l| !l.contains("SECRET-IND")),
            "case: {line}; secret reached logs: {logs:?}"
        );

        sup.shutdown().await;
        r.assert_all_gone().await;
    }
}

/// A READY line longer than the 4096-byte limit is rejected (and not logged).
#[tokio::test]
async fn oversized_ready_line_is_rejected_and_its_content_is_not_logged() {
    let line = format!(
        r#"TOOLBOX_READY {{"v":1,"port":41001,"token":"{TOKEN}","pad":"{}"}}"#,
        "x".repeat(5000)
    );
    let mut r = Run::new("raw");
    r.env("IND_RAW_LINE", &line);
    let sup = r.start();

    wait_status(&sup, 5, |s| s.restarts >= 1).await;
    assert!(sup.connection(Duration::from_millis(100)).await.is_err());
    assert!(r.statuses().iter().all(|s| s.state != State::Ready));
    let logs = r.logs();
    assert!(
        logs.iter()
            .any(|l| l.contains("READY line exceeds size limit")),
        "logs = {logs:?}"
    );
    r.assert_no_token_leak();

    sup.shutdown().await;
    r.assert_all_gone().await;
}

/// The token is split across the 4096-byte stderr forwarding chunk, so
/// per-chunk redaction cannot match the full token. Expected to FAIL against
/// the current implementation: its first 20 characters appear in the log.
/// Assertion deliberately not relaxed.
#[tokio::test]
async fn token_straddling_the_stderr_chunk_limit_is_not_leaked_to_logs() {
    let r = Run::new("stderr_long");
    let sup = r.start();
    sup.connection(Duration::from_secs(5)).await.unwrap();
    wait_status(&sup, 5, |s| s.state == State::Ready).await;
    assert!(
        wait_for(|| r.logs().iter().any(|l| l.starts_with("backend: "))).await,
        "stderr line never forwarded"
    );

    sup.shutdown().await;
    let prefix = &TOKEN[..16];
    for l in r.logs() {
        assert!(
            !l.contains(prefix),
            "token prefix reached the log ({} bytes in this line): {l}",
            l.len()
        );
    }
    r.assert_all_gone().await;
}
