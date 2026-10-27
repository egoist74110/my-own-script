//! Backend process supervisor (no GUI dependency, unit-testable).
//!
//! Contract (see docs/modernization/WORK_PACKAGES.md, "S0 已定接口"):
//!
//! * the backend is spawned in its own process group, stdin piped and held open;
//! * the first and only stdout line is `TOOLBOX_READY {"v":1,"port":..,"token":"..","pid":..}`;
//! * stderr is forwarded to the shell log (the known token is redacted defensively);
//! * unexpected exits are restarted with exponential backoff (1,2,4.. <= 30 s,
//!   reset after 60 s of stability);
//! * shutdown is one coordinated sequence: close stdin -> SIGTERM the group ->
//!   wait <= 5 s -> SIGKILL the group -> wait.
//!
//! Ownership model: a single run-loop task owns the child process. `shutdown()`
//! only raises a level-triggered flag, so a restart can never race with (or
//! outlive) a shutdown: the loop checks the flag before every spawn and every
//! await point that can block.

use std::{
    ffi::OsString,
    fmt,
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};

use serde::Serialize;
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, BufReader},
    process::{Child, ChildStdin, Command},
    sync::watch,
    task::JoinHandle,
    time::{sleep, timeout, Instant},
};

pub const READY_PREFIX: &str = "TOOLBOX_READY ";
/// Upper bound for the handshake line; anything longer is a protocol error.
pub const MAX_READY_LINE: usize = 4096;
/// Name of the page-facing status event.
pub const STATUS_EVENT: &str = "backend://status";

// ---------------------------------------------------------------------------
// Handshake line
// ---------------------------------------------------------------------------

/// Parsed READY line.
#[derive(Clone, PartialEq, Eq)]
pub struct Ready {
    pub port: u16,
    pub token: String,
    pub pid: u32,
}

impl fmt::Debug for Ready {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Ready")
            .field("port", &self.port)
            .field("token", &"<redacted>")
            .field("pid", &self.pid)
            .finish()
    }
}

/// Why a handshake line was rejected. Never carries input text (the line
/// contains a secret).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReadyError {
    /// Does not start with `TOOLBOX_READY `.
    NotReadyLine,
    /// The payload is not valid JSON.
    InvalidJson,
    /// A field is missing or has the wrong type/range.
    InvalidField(&'static str),
}

impl fmt::Display for ReadyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotReadyLine => write!(f, "first stdout line is not a READY line"),
            Self::InvalidJson => write!(f, "READY payload is not valid JSON"),
            Self::InvalidField(name) => write!(f, "READY payload field `{name}` is invalid"),
        }
    }
}

impl std::error::Error for ReadyError {}

/// Parse one stdout line (a trailing `\r\n`/`\n` is tolerated).
pub fn parse_ready_line(line: &str) -> Result<Ready, ReadyError> {
    let line = line.trim_end_matches(['\n', '\r']);
    let payload = line
        .strip_prefix(READY_PREFIX)
        .ok_or(ReadyError::NotReadyLine)?;
    // Parse into a Value first: serde's typed errors echo the offending value,
    // which could be the token.
    let value: serde_json::Value =
        serde_json::from_str(payload).map_err(|_| ReadyError::InvalidJson)?;
    let obj = value
        .as_object()
        .ok_or(ReadyError::InvalidField("payload"))?;
    if obj.get("v").and_then(|v| v.as_u64()) != Some(1) {
        return Err(ReadyError::InvalidField("v"));
    }
    let port = obj
        .get("port")
        .and_then(|v| v.as_u64())
        .filter(|p| (1..=u64::from(u16::MAX)).contains(p))
        .ok_or(ReadyError::InvalidField("port"))? as u16;
    let token = obj
        .get("token")
        .and_then(|v| v.as_str())
        .filter(|t| !t.is_empty())
        .ok_or(ReadyError::InvalidField("token"))?
        .to_owned();
    let pid = obj
        .get("pid")
        .and_then(|v| v.as_u64())
        .filter(|p| (1..=u64::from(u32::MAX)).contains(p))
        .ok_or(ReadyError::InvalidField("pid"))? as u32;
    Ok(Ready { port, token, pid })
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// What the page receives from the `backend_connection` command.
#[derive(Clone, PartialEq, Eq, Serialize)]
pub struct Connection {
    pub port: u16,
    pub token: String,
}

impl fmt::Debug for Connection {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Connection")
            .field("port", &self.port)
            .field("token", &"<redacted>")
            .finish()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum State {
    /// Process spawned (or about to be), waiting for READY.
    Starting,
    /// READY received; the connection is available.
    Ready,
    /// Backend exited unexpectedly; waiting out the backoff before respawn.
    Restarting,
    /// Coordinated shutdown in progress.
    Stopping,
    /// Shutdown finished; terminal state.
    Stopped,
}

/// Payload of `backend://status`. Deliberately has no token field.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Status {
    pub state: State,
    pub pid: Option<u32>,
    /// Cumulative number of restarts since the supervisor started.
    pub restarts: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConnectionError {
    Timeout,
    ShuttingDown,
}

impl fmt::Display for ConnectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Timeout => write!(f, "backend did not become ready in time"),
            Self::ShuttingDown => write!(f, "backend is shutting down"),
        }
    }
}

impl std::error::Error for ConnectionError {}

pub type StatusCallback = Arc<dyn Fn(&Status) + Send + Sync>;
pub type LogSink = Arc<dyn Fn(&str) + Send + Sync>;

/// How to launch the backend.
#[derive(Debug, Clone)]
pub struct BackendCommand {
    pub program: OsString,
    pub args: Vec<OsString>,
    pub cwd: Option<PathBuf>,
    pub env: Vec<(OsString, OsString)>,
    /// Environment variables removed from the child (not inherited from the app).
    pub env_remove: Vec<OsString>,
}

impl BackendCommand {
    pub fn new(program: impl Into<OsString>) -> Self {
        Self {
            program: program.into(),
            args: Vec::new(),
            cwd: None,
            env: Vec::new(),
            env_remove: Vec::new(),
        }
    }

    pub fn args<I, S>(mut self, args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<OsString>,
    {
        self.args.extend(args.into_iter().map(Into::into));
        self
    }

    pub fn cwd(mut self, cwd: impl Into<PathBuf>) -> Self {
        self.cwd = Some(cwd.into());
        self
    }

    pub fn env(mut self, key: impl Into<OsString>, value: impl Into<OsString>) -> Self {
        self.env.push((key.into(), value.into()));
        self
    }

    pub fn env_remove(mut self, key: impl Into<OsString>) -> Self {
        self.env_remove.push(key.into());
        self
    }

    /// Resolve override, bundled runtime beside the executable, then dev mode.
    /// `repo_root` is only a development fallback; it need not exist in a bundle.
    pub fn packaged(
        executable: &Path,
        repo_root: &Path,
        override_cmd: Option<&str>,
    ) -> Result<Self, String> {
        if override_cmd.is_some_and(|raw| !raw.trim().is_empty()) {
            return Self::dev(repo_root, override_cmd);
        }
        if let Some(contents) = executable.parent().and_then(Path::parent) {
            let backend = contents.join("Resources/backend");
            let python = backend.join("bin/python3.14");
            if python.exists() {
                return Ok(Self::new(python)
                    .args(["-m", "toolbox_backend"])
                    .cwd(backend)
                    .env("PYTHONDONTWRITEBYTECODE", "1")
                    .env("PYTHONNOUSERSITE", "1")
                    .env_remove("PYTHONPATH")
                    .env_remove("PYTHONHOME")
                    .env_remove("PYTHONSTARTUP"));
            }
        }
        Self::dev(repo_root, override_cmd)
    }

    /// Dev-mode command: `<repo>/next/backend/.venv/bin/python -m toolbox_backend --dev`
    /// with cwd `<repo>/next/backend`; `override_cmd` (the value of
    /// `TOOLBOX_BACKEND_CMD`, shell-style quoting) replaces program and args.
    pub fn dev(repo_root: &Path, override_cmd: Option<&str>) -> Result<Self, String> {
        let backend_dir = repo_root.join("next").join("backend");
        let mut cmd = match override_cmd.map(str::trim).filter(|s| !s.is_empty()) {
            Some(raw) => {
                let mut parts = shlex::split(raw)
                    .ok_or_else(|| "TOOLBOX_BACKEND_CMD has unbalanced quotes".to_owned())?;
                if parts.is_empty() {
                    return Err("TOOLBOX_BACKEND_CMD is empty".to_owned());
                }
                let program = parts.remove(0);
                Self::new(program).args(parts)
            }
            None => Self::new(backend_dir.join(".venv").join("bin").join("python")).args([
                "-m",
                "toolbox_backend",
                "--dev",
            ]),
        };
        if backend_dir.is_dir() {
            cmd = cmd.cwd(backend_dir);
        }
        Ok(cmd)
    }
}

/// Supervisor tunables. `new()` gives the production values from the contract.
#[derive(Clone)]
pub struct SupervisorConfig {
    pub command: BackendCommand,
    /// Max wait for the READY line after spawn (contract: 20 s).
    pub ready_timeout: Duration,
    pub backoff_base: Duration,
    pub backoff_max: Duration,
    /// Uptime after READY that resets the backoff sequence (contract: 60 s).
    pub stable_reset: Duration,
    /// SIGTERM -> SIGKILL grace (contract: 5 s).
    pub term_grace: Duration,
    /// Max wait inside `connection()` (contract: 20 s).
    pub connection_wait: Duration,
    pub on_status: Option<StatusCallback>,
    pub log: LogSink,
}

impl SupervisorConfig {
    pub fn new(command: BackendCommand) -> Self {
        Self {
            command,
            ready_timeout: Duration::from_secs(20),
            backoff_base: Duration::from_secs(1),
            backoff_max: Duration::from_secs(30),
            stable_reset: Duration::from_secs(60),
            term_grace: Duration::from_secs(5),
            connection_wait: Duration::from_secs(20),
            on_status: None,
            log: Arc::new(|line| eprintln!("{line}")),
        }
    }
}

/// Delay before the `failures`-th consecutive restart (0-based): base * 2^n, capped.
pub fn backoff_delay(base: Duration, max: Duration, failures: u32) -> Duration {
    let factor = 1u32.checked_shl(failures.min(31)).unwrap_or(u32::MAX);
    base.checked_mul(factor).map_or(max, |d| d.min(max))
}

// ---------------------------------------------------------------------------
// Supervisor
// ---------------------------------------------------------------------------

struct Shared {
    cfg: SupervisorConfig,
    status: Mutex<Status>,
    status_tx: watch::Sender<Status>,
    conn_tx: watch::Sender<Option<Connection>>,
    shutdown_started: AtomicBool,
    shutdown_tx: watch::Sender<bool>,
    done_tx: watch::Sender<bool>,
}

impl Shared {
    fn log(&self, msg: &str) {
        (self.cfg.log)(msg);
    }

    /// Apply `f` to the status and notify. After shutdown has started only
    /// Stopping/Stopped may be published, so a late `Ready`/`Starting` from the
    /// run loop can never overwrite the shutdown state.
    fn publish(&self, f: impl FnOnce(&mut Status)) {
        let mut guard = self.status.lock().unwrap_or_else(|e| e.into_inner());
        let mut next = guard.clone();
        f(&mut next);
        if self.shutdown_started.load(Ordering::SeqCst)
            && !matches!(next.state, State::Stopping | State::Stopped)
        {
            return;
        }
        if next == *guard {
            return;
        }
        *guard = next.clone();
        self.status_tx.send_replace(next.clone());
        if let Some(cb) = &self.cfg.on_status {
            cb(&next);
        }
    }
}

/// Raises the `done` flag when the run loop ends (also on panic).
struct DoneGuard(watch::Sender<bool>);

impl Drop for DoneGuard {
    fn drop(&mut self) {
        self.0.send_replace(true);
    }
}

pub struct Supervisor {
    shared: Arc<Shared>,
    _task: JoinHandle<()>,
}

impl Supervisor {
    /// Start supervising. Must be called inside a Tokio runtime.
    pub fn start(cfg: SupervisorConfig) -> Self {
        let initial = Status {
            state: State::Starting,
            pid: None,
            restarts: 0,
        };
        let shared = Arc::new(Shared {
            cfg,
            status: Mutex::new(initial.clone()),
            status_tx: watch::channel(initial).0,
            conn_tx: watch::channel(None).0,
            shutdown_started: AtomicBool::new(false),
            shutdown_tx: watch::channel(false).0,
            done_tx: watch::channel(false).0,
        });
        let task = tokio::spawn(run_loop(shared.clone()));
        Self {
            shared,
            _task: task,
        }
    }

    pub fn status(&self) -> Status {
        self.shared
            .status
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    pub fn subscribe(&self) -> watch::Receiver<Status> {
        self.shared.status_tx.subscribe()
    }

    pub fn connection_wait(&self) -> Duration {
        self.shared.cfg.connection_wait
    }

    pub fn is_stopped(&self) -> bool {
        *self.shared.done_tx.borrow()
    }

    /// Current connection, waiting up to `wait` for the backend to be ready.
    pub async fn connection(&self, wait: Duration) -> Result<Connection, ConnectionError> {
        let mut conn_rx = self.shared.conn_tx.subscribe();
        let mut shutdown_rx = self.shared.shutdown_tx.subscribe();
        tokio::select! {
            res = timeout(wait, conn_rx.wait_for(|c| c.is_some())) => match res {
                Ok(Ok(guard)) => guard.clone().ok_or(ConnectionError::ShuttingDown),
                Ok(Err(_)) => Err(ConnectionError::ShuttingDown),
                Err(_) => Err(ConnectionError::Timeout),
            },
            _ = shutdown_rx.wait_for(|v| *v) => Err(ConnectionError::ShuttingDown),
        }
    }

    /// Coordinated shutdown. Idempotent and safe to call concurrently: the
    /// sequence runs exactly once (compare-and-swap on a flag, executed by the
    /// run-loop task that owns the child); every caller returns after it ended.
    pub async fn shutdown(&self) {
        self.begin_shutdown();
        let mut done = self.shared.done_tx.subscribe();
        let _ = done.wait_for(|d| *d).await;
    }

    fn begin_shutdown(&self) {
        if self
            .shared
            .shutdown_started
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            self.shared.publish(|s| s.state = State::Stopping);
            self.shared.shutdown_tx.send_replace(true);
        }
    }
}

impl Drop for Supervisor {
    /// Safety net: signal shutdown so the run loop reaps the child if the
    /// owner forgot (or could not await) `shutdown()`.
    fn drop(&mut self) {
        self.begin_shutdown();
    }
}

// ---------------------------------------------------------------------------
// Run loop
// ---------------------------------------------------------------------------

enum Outcome {
    /// Shutdown was requested; the child (if any) has been stopped.
    Shutdown,
    /// The child ended on its own (or never got ready). `ready_for` is how long
    /// it stayed ready, if it ever did.
    Exited { ready_for: Option<Duration> },
}

async fn run_loop(shared: Arc<Shared>) {
    let _done = DoneGuard(shared.done_tx.clone());
    let mut shutdown_rx = shared.shutdown_tx.subscribe();
    let mut failures: u32 = 0;
    let mut restarts: u32 = 0;

    loop {
        if *shutdown_rx.borrow() {
            break;
        }
        shared.publish(|s| {
            s.state = State::Starting;
            s.pid = None;
            s.restarts = restarts;
        });
        match run_once(&shared, &mut shutdown_rx, restarts).await {
            Outcome::Shutdown => break,
            Outcome::Exited { ready_for } => {
                if ready_for.is_some_and(|d| d >= shared.cfg.stable_reset) {
                    failures = 0;
                }
                let delay =
                    backoff_delay(shared.cfg.backoff_base, shared.cfg.backoff_max, failures);
                failures = failures.saturating_add(1);
                restarts = restarts.saturating_add(1);
                shared.publish(|s| {
                    s.state = State::Restarting;
                    s.pid = None;
                    s.restarts = restarts;
                });
                shared.log(&format!(
                    "supervisor: backend down, restart #{restarts} in {}ms",
                    delay.as_millis()
                ));
                tokio::select! {
                    _ = sleep(delay) => {}
                    _ = shutdown_rx.wait_for(|v| *v) => break,
                }
            }
        }
    }

    shared.conn_tx.send_replace(None);
    shared.publish(|s| {
        s.state = State::Stopped;
        s.pid = None;
    });
}

enum Handshake {
    Ready(Ready),
    Failed(String),
}

async fn read_ready<R: AsyncRead + Unpin>(reader: &mut BufReader<R>) -> Handshake {
    let mut buf = Vec::new();
    let n = match (&mut *reader)
        .take(MAX_READY_LINE as u64)
        .read_until(b'\n', &mut buf)
        .await
    {
        Ok(n) => n,
        Err(e) => return Handshake::Failed(format!("stdout read error: {}", e.kind())),
    };
    if n == 0 {
        return Handshake::Failed("stdout closed before READY".to_owned());
    }
    if buf.last() != Some(&b'\n') && n >= MAX_READY_LINE {
        return Handshake::Failed("READY line exceeds size limit".to_owned());
    }
    let Ok(line) = std::str::from_utf8(&buf) else {
        return Handshake::Failed("READY line is not UTF-8".to_owned());
    };
    match parse_ready_line(line) {
        Ok(r) => Handshake::Ready(r),
        Err(e) => Handshake::Failed(e.to_string()),
    }
}

fn redact(line: &str, token: Option<&str>) -> String {
    match token {
        Some(t) if !t.is_empty() => line.replace(t, "[REDACTED]"),
        _ => line.to_owned(),
    }
}

/// Holds back stderr lines until the handshake has resolved, so that a line
/// racing the READY line is redacted with the token once it is known.
enum Gate {
    /// Handshake pending: queue (bounded) instead of logging.
    Pending(Vec<String>),
    /// Handshake resolved: log directly, redacting the token if there is one.
    Open(Option<String>),
}

const GATE_QUEUE_MAX: usize = 1000;
/// Longest stderr line forwarded (longer lines are truncated).
const STDERR_LINE_MAX: usize = 64 * 1024;
const STDERR_TAIL_GUARD: usize = 256;

type SharedGate = Arc<Mutex<Gate>>;

fn emit_line(shared: &Shared, text: &str, token: Option<&str>) {
    shared.log(&format!("backend: {}", redact(text, token)));
}

/// Resolve the handshake gate: flush queued lines (redacted) and let later
/// lines through. Idempotent.
fn open_gate(gate: &SharedGate, shared: &Shared, token: Option<String>) {
    let mut g = gate.lock().unwrap_or_else(|e| e.into_inner());
    if let Gate::Pending(queue) = &mut *g {
        for line in queue.drain(..) {
            emit_line(shared, &line, token.as_deref());
        }
    }
    *g = Gate::Open(token);
}

/// Forward backend stderr line by line to the shell log.
fn spawn_stderr_forwarder<R>(stderr: R, shared: Arc<Shared>, gate: SharedGate) -> JoinHandle<()>
where
    R: AsyncRead + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        let mut reader = BufReader::new(stderr);
        let mut line: Vec<u8> = Vec::new();
        let mut chunk: Vec<u8> = Vec::new();
        let mut skipping = false; // discarding the rest of an over-long line
        loop {
            // Assemble a whole line first: redaction must see the entire text,
            // or a token straddling a read boundary would slip through.
            line.clear();
            let mut truncated = false;
            let eof = loop {
                chunk.clear();
                match (&mut reader)
                    .take(MAX_READY_LINE as u64)
                    .read_until(b'\n', &mut chunk)
                    .await
                {
                    Ok(0) | Err(_) => break true,
                    Ok(_) => {
                        let complete = chunk.last() == Some(&b'\n');
                        if skipping {
                            skipping = !complete;
                            if complete {
                                break false;
                            }
                            continue;
                        }
                        line.extend_from_slice(&chunk);
                        if complete {
                            break false;
                        }
                        if line.len() >= STDERR_LINE_MAX {
                            // Cut inside the line; keep a tail guard so a
                            // token cut by the limit leaves no prefix behind.
                            line.truncate(STDERR_LINE_MAX - STDERR_TAIL_GUARD);
                            truncated = true;
                            skipping = true;
                        }
                    }
                }
            };
            if !line.is_empty() {
                let text = String::from_utf8_lossy(&line);
                let mut text = text.trim_end_matches(['\n', '\r']).to_owned();
                if truncated {
                    text.push_str(" ...[truncated]");
                }
                let mut g = gate.lock().unwrap_or_else(|e| e.into_inner());
                match &mut *g {
                    Gate::Pending(queue) => {
                        if queue.len() < GATE_QUEUE_MAX {
                            queue.push(text);
                        }
                    }
                    Gate::Open(tok) => emit_line(&shared, &text, tok.as_deref()),
                }
            }
            if eof {
                break;
            }
        }
    })
}

/// After READY nothing may be written to stdout. Keep draining so the child
/// never blocks on a full pipe, and log (without content) that it happened.
fn spawn_stdout_drain<R>(mut reader: BufReader<R>, shared: Arc<Shared>) -> JoinHandle<()>
where
    R: AsyncRead + Unpin + Send + 'static,
{
    tokio::spawn(async move {
        let mut chunk = [0u8; 4096];
        loop {
            match reader.read(&mut chunk).await {
                Ok(0) | Err(_) => break,
                Ok(n) => shared.log(&format!(
                    "supervisor: backend wrote {n} unexpected stdout byte(s) after READY (content withheld)"
                )),
            }
        }
    })
}

async fn run_once(
    shared: &Arc<Shared>,
    shutdown_rx: &mut watch::Receiver<bool>,
    restarts: u32,
) -> Outcome {
    let cfg = &shared.cfg;
    let mut command = Command::new(&cfg.command.program);
    command
        .args(&cfg.command.args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(false)
        .process_group(0);
    if let Some(cwd) = &cfg.command.cwd {
        command.current_dir(cwd);
    }
    for k in &cfg.command.env_remove {
        command.env_remove(k);
    }
    for (k, v) in &cfg.command.env {
        command.env(k, v);
    }

    let mut child = match command.spawn() {
        Ok(c) => c,
        Err(e) => {
            shared.log(&format!(
                "supervisor: failed to spawn backend: {}",
                e.kind()
            ));
            return Outcome::Exited { ready_for: None };
        }
    };
    let Some(pid) = child.id() else {
        shared.log("supervisor: backend vanished right after spawn");
        return Outcome::Exited { ready_for: None };
    };
    let pgid = pid as libc::pid_t; // process_group(0): pgid == pid
    shared.publish(|s| {
        s.state = State::Starting;
        s.pid = Some(pid);
        s.restarts = restarts;
    });

    // Held for the whole run; dropping it is the first step of shutdown.
    let mut stdin = child.stdin.take();
    let gate: SharedGate = Arc::new(Mutex::new(Gate::Pending(Vec::new())));
    let stderr_task = child
        .stderr
        .take()
        .map(|e| spawn_stderr_forwarder(e, shared.clone(), gate.clone()));
    let mut stdout = BufReader::new(child.stdout.take().expect("stdout is piped"));
    let mut aux: Vec<JoinHandle<()>> = stderr_task.into_iter().collect();

    // ---- handshake ----
    let handshake = tokio::select! {
        res = timeout(cfg.ready_timeout, read_ready(&mut stdout)) => match res {
            Ok(h) => Some(h),
            Err(_) => Some(Handshake::Failed(format!(
                "no READY line within {}ms", cfg.ready_timeout.as_millis()
            ))),
        },
        _ = shutdown_rx.wait_for(|v| *v) => None,
    };
    let ready = match handshake {
        None => {
            open_gate(&gate, shared, None);
            stop_group(&mut child, stdin.take(), pgid, cfg.term_grace).await;
            drain_and_abort(aux).await;
            return Outcome::Shutdown;
        }
        Some(Handshake::Failed(why)) => {
            // The failed line is never logged, so nothing to redact here.
            open_gate(&gate, shared, None);
            shared.log(&format!("supervisor: handshake failed: {why}"));
            stop_group(&mut child, stdin.take(), pgid, cfg.term_grace).await;
            drain_and_abort(aux).await;
            return Outcome::Exited { ready_for: None };
        }
        Some(Handshake::Ready(r)) => r,
    };

    open_gate(&gate, shared, Some(ready.token.clone()));
    aux.push(spawn_stdout_drain(stdout, shared.clone()));
    shared.conn_tx.send_replace(Some(Connection {
        port: ready.port,
        token: ready.token,
    }));
    shared.publish(|s| {
        s.state = State::Ready;
        s.pid = Some(pid);
        s.restarts = restarts;
    });
    shared.log(&format!(
        "supervisor: backend ready (pid {pid}, port {})",
        ready.port
    ));
    let ready_at = Instant::now();

    // ---- running ----
    let outcome = tokio::select! {
        res = child.wait() => {
            match res {
                Ok(st) => shared.log(&format!("supervisor: backend exited unexpectedly ({st})")),
                Err(e) => shared.log(&format!("supervisor: wait on backend failed: {}", e.kind())),
            }
            Outcome::Exited { ready_for: Some(ready_at.elapsed()) }
        }
        _ = shutdown_rx.wait_for(|v| *v) => Outcome::Shutdown,
    };
    shared.conn_tx.send_replace(None);
    // Leader gone or shutdown: either way take down everything left in the group.
    stop_group(&mut child, stdin.take(), pgid, cfg.term_grace).await;
    drain_and_abort(aux).await;
    outcome
}

/// Give the log forwarders a moment to flush the backend's last words (pipes
/// hit EOF once the group is gone), then stop them; a surviving grandchild
/// holding a pipe open must not keep them alive.
async fn drain_and_abort(tasks: Vec<JoinHandle<()>>) {
    for mut t in tasks {
        let _ = timeout(Duration::from_millis(200), &mut t).await;
        t.abort();
    }
}

// ---------------------------------------------------------------------------
// Process-group helpers
// ---------------------------------------------------------------------------

/// True while any process of group `pgid` exists (`kill(-pgid, 0)`).
pub fn group_alive(pgid: i32) -> bool {
    // SAFETY: signal 0 only checks for existence.
    let rc = unsafe { libc::kill(-pgid, 0) };
    if rc == 0 {
        return true;
    }
    std::io::Error::last_os_error().raw_os_error() != Some(libc::ESRCH)
}

fn signal_group(pgid: i32, sig: libc::c_int) {
    // SAFETY: plain signal delivery to a group we created via process_group(0).
    unsafe {
        libc::killpg(pgid, sig);
    }
}

async fn wait_group_gone(pgid: i32, limit: Duration) -> bool {
    let deadline = Instant::now() + limit;
    while group_alive(pgid) {
        if Instant::now() >= deadline {
            return false;
        }
        sleep(Duration::from_millis(20)).await;
    }
    true
}

/// The coordinated stop: close stdin -> SIGTERM group -> wait <= `grace` ->
/// SIGKILL group -> wait. Safe on an already-exited leader (cleans leftovers).
async fn stop_group(child: &mut Child, stdin: Option<ChildStdin>, pgid: i32, grace: Duration) {
    drop(stdin);
    let started = Instant::now();
    signal_group(pgid, libc::SIGTERM);
    // Leader first, then any stragglers, all within one grace window.
    let _ = timeout(grace, child.wait()).await;
    let remaining = grace.saturating_sub(started.elapsed());
    if !wait_group_gone(pgid, remaining).await {
        signal_group(pgid, libc::SIGKILL);
        let _ = timeout(Duration::from_secs(2), child.wait()).await;
        let _ = wait_group_gone(pgid, Duration::from_secs(2)).await;
    }
}

// ---------------------------------------------------------------------------
// Unit tests (pure logic; process behavior lives in tests/supervisor.rs)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn ready(json: &str) -> Result<Ready, ReadyError> {
        parse_ready_line(&format!("{READY_PREFIX}{json}\n"))
    }

    #[test]
    fn parses_valid_line() {
        let r = ready(r#"{"v":1,"port":51234,"token":"abc_DEF-123","pid":4242}"#).unwrap();
        assert_eq!(
            r,
            Ready {
                port: 51234,
                token: "abc_DEF-123".into(),
                pid: 4242
            }
        );
    }

    #[test]
    fn tolerates_crlf_and_extra_fields() {
        let line = format!(
            "{READY_PREFIX}{}\r\n",
            r#"{"v":1,"port":1,"token":"t","pid":1,"x":true}"#
        );
        assert!(parse_ready_line(&line).is_ok());
    }

    #[test]
    fn rejects_malformed_lines() {
        assert_eq!(parse_ready_line("hello\n"), Err(ReadyError::NotReadyLine));
        assert_eq!(parse_ready_line(""), Err(ReadyError::NotReadyLine));
        assert_eq!(
            parse_ready_line("TOOLBOX_READY{\"v\":1}"),
            Err(ReadyError::NotReadyLine)
        );
        assert_eq!(ready("not json"), Err(ReadyError::InvalidJson));
        assert_eq!(ready("[1,2]"), Err(ReadyError::InvalidField("payload")));
        assert_eq!(
            ready(r#"{"v":2,"port":1,"token":"t","pid":1}"#),
            Err(ReadyError::InvalidField("v"))
        );
        assert_eq!(
            ready(r#"{"port":1,"token":"t","pid":1}"#),
            Err(ReadyError::InvalidField("v"))
        );
        for bad_port in ["0", "65536", "-1", "\"80\"", "1.5", "null"] {
            let j = format!(r#"{{"v":1,"port":{bad_port},"token":"t","pid":1}}"#);
            assert_eq!(
                ready(&j),
                Err(ReadyError::InvalidField("port")),
                "{bad_port}"
            );
        }
        assert_eq!(
            ready(r#"{"v":1,"port":80,"token":"","pid":1}"#),
            Err(ReadyError::InvalidField("token"))
        );
        assert_eq!(
            ready(r#"{"v":1,"port":80,"token":7,"pid":1}"#),
            Err(ReadyError::InvalidField("token"))
        );
        assert_eq!(
            ready(r#"{"v":1,"port":80,"token":"t","pid":0}"#),
            Err(ReadyError::InvalidField("pid"))
        );
    }

    #[test]
    fn errors_never_echo_the_token() {
        let secret = "SECRET-TOKEN-VALUE";
        let cases = [
            format!(r#"{{"v":1,"port":"{secret}","token":"{secret}","pid":1}}"#),
            format!(r#"{{"v":1,"port":0,"token":"{secret}","pid":1}}"#),
            format!(r#"{{"v":1,"port":1,"token":"{secret}" "pid":1}}"#),
        ];
        for c in cases {
            let err = ready(&c).unwrap_err();
            assert!(!format!("{err} {err:?}").contains(secret));
        }
    }

    #[test]
    fn debug_and_status_do_not_leak_token() {
        let conn = Connection {
            port: 1,
            token: "SECRET-TOKEN-VALUE".into(),
        };
        assert!(!format!("{conn:?}").contains("SECRET"));
        let r = Ready {
            port: 1,
            token: "SECRET-TOKEN-VALUE".into(),
            pid: 2,
        };
        assert!(!format!("{r:?}").contains("SECRET"));
        let st = Status {
            state: State::Ready,
            pid: Some(2),
            restarts: 3,
        };
        let json = serde_json::to_value(&st).unwrap();
        assert_eq!(
            json,
            serde_json::json!({"state":"ready","pid":2,"restarts":3})
        );
    }

    #[test]
    fn backoff_sequence_is_capped() {
        let b = Duration::from_secs(1);
        let m = Duration::from_secs(30);
        let seq: Vec<u64> = (0..8).map(|n| backoff_delay(b, m, n).as_secs()).collect();
        assert_eq!(seq, vec![1, 2, 4, 8, 16, 30, 30, 30]);
        assert_eq!(backoff_delay(b, m, u32::MAX), m);
    }

    #[test]
    fn redacts_known_token() {
        assert_eq!(
            redact("a tok b tok", Some("tok")),
            "a [REDACTED] b [REDACTED]"
        );
        assert_eq!(redact("keep", None), "keep");
        assert_eq!(redact("keep", Some("")), "keep");
    }

    #[test]
    fn dev_command_defaults_and_override() {
        let root = Path::new("/nonexistent-root");
        let d = BackendCommand::dev(root, None).unwrap();
        assert_eq!(
            Path::new(&d.program),
            root.join("next/backend/.venv/bin/python")
        );
        assert_eq!(d.args, ["-m", "toolbox_backend", "--dev"]);
        assert!(d.cwd.is_none()); // directory does not exist here

        let o = BackendCommand::dev(root, Some("/bin/echo 'two words' x")).unwrap();
        assert_eq!(o.program, "/bin/echo");
        assert_eq!(o.args, ["two words", "x"]);

        assert!(BackendCommand::dev(root, Some("'unbalanced")).is_err());
        // blank override falls back to the default
        let blank = BackendCommand::dev(root, Some("   ")).unwrap();
        assert_eq!(blank.args.len(), 3);
    }

    #[test]
    fn packaged_command_strips_python_env_overrides() {
        let temp = tempfile::tempdir().unwrap();
        let macos = temp.path().join("App.app/Contents/MacOS");
        let backend = temp.path().join("App.app/Contents/Resources/backend");
        std::fs::create_dir_all(&macos).unwrap();
        std::fs::create_dir_all(backend.join("bin")).unwrap();
        std::fs::write(backend.join("bin/python3.14"), "").unwrap();
        let cmd = BackendCommand::packaged(
            &macos.join("toolbox-desktop"),
            Path::new("/nonexistent-root"),
            None,
        )
        .unwrap();
        for key in ["PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"] {
            assert!(cmd.env_remove.iter().any(|k| k == key), "{key} not removed");
        }
        assert!(cmd
            .env
            .iter()
            .any(|(k, v)| k == "PYTHONNOUSERSITE" && v == "1"));
        // dev mode leaves the environment untouched
        assert!(BackendCommand::dev(Path::new("/x"), None)
            .unwrap()
            .env_remove
            .is_empty());
    }
}
