"""S6-B regression tests for Lark managed MCP state machine, ownership, login/logout, logs, and supervision."""

import asyncio
import json
import os
import signal
import socket
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.api.mcp_schemas import (
    LarkActionRequest,
    LarkOwnershipRequest,
    MCPSettingsPatch,
)
from toolbox_backend.app import create_app
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.mcp import LarkMcp, NodeRuntime
from toolbox_backend.domain.settings import Config, CredentialMeta
from toolbox_backend.mcp.lark_logs import is_port_in_use, probe_lark_http
from toolbox_backend.mcp.runner import secure_directory
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.mcp import McpService
from toolbox_backend.settings import Settings


@pytest.fixture
def isolated_supervisor(monkeypatch):
    original = asyncio.create_subprocess_exec

    async def spawn(*argv, **kwargs):
        if len(argv) >= 3 and argv[1:3] == ("-m", "toolbox_backend.adapters.proc_supervisor"):
            argv = (
                argv[0],
                "-c",
                "import sys; from toolbox_backend.adapters import proc_supervisor as m; "
                "m.process_identity=lambda pid: {}; sys.exit(m.main())",
            )
        return await original(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sandbox_blocks_loopback_connect() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cli:
            try:
                cli.connect(("127.0.0.1", port))
                return False
            except PermissionError:
                return True
            except OSError:
                return False


def _make_lark_prober(tmp_path: Path):
    sandbox_blocked = _sandbox_blocks_loopback_connect()

    async def _prober(port: int, timeout_s: float = 0.5) -> bool:
        if not sandbox_blocked:
            return await probe_lark_http(port, timeout_s)
        state_file = tmp_path / f"lark_listen_{port}.json"
        if not state_file.is_file():
            return False
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            pid = int(data["pid"])
            os.kill(pid, 0)
            return bool(data.get("listening"))
        except OSError, ValueError, KeyError:
            return False

    return _prober


def _setup_fake_lark_env(
    data_dir: Path,
    tmp_path: Path,
    *,
    port: int | None = None,
    owner_confirmed: bool = True,
    with_secret: bool = True,
    with_runtime: bool = True,
    mode_file: Path | None = None,
    dump_file: Path | None = None,
    pid_file: Path | None = None,
) -> tuple[ConfigStore, MemoryCredentials, int, Path]:
    data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    data_dir.chmod(0o700)
    chosen_port = port or _free_port()
    mode_path = mode_file or (tmp_path / "lark_mode.json")
    dump_path = dump_file or (tmp_path / "lark_dump.json")
    pids_path = pid_file or (tmp_path / "lark_pids.txt")
    if not mode_path.exists():
        mode_path.write_text(
            json.dumps(
                {
                    "mcp": "normal",
                    "patches": ["auth_store=applied", "oidc=applied", "mcp_tool=applied"],
                    "keytar_disabled": False,
                    "login": "ok",
                    "logout": "ok",
                }
            ),
            encoding="utf-8",
        )

    bin_dir = tmp_path / "fake_lark_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    node_path = bin_dir / "node"

    if with_runtime:
        node_path.write_text(
            f"""#!{sys.executable}
import sys, runpy
if "--version" in sys.argv or "-v" in sys.argv:
    print("v24.13.0")
    sys.exit(0)
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
""",
            encoding="utf-8",
        )
        node_path.chmod(0o755)

        pkg_root = secure_directory(data_dir, "mcp", "packages")
        lark_dir = pkg_root / "node_modules/@larksuiteoapi/lark-mcp/dist"
        lark_dir.mkdir(parents=True, exist_ok=True)
        (lark_dir.parent / "package.json").write_text(
            '{"version": "0.5.1"}', encoding="utf-8"
        )
        figma_dir = pkg_root / "node_modules/figma-developer-mcp/dist"
        figma_dir.mkdir(parents=True, exist_ok=True)
        (figma_dir / "bin.js").write_text("// fake\n", encoding="utf-8")
        (figma_dir.parent / "package.json").write_text(
            '{"version": "0.13.2"}', encoding="utf-8"
        )

        cli_js = lark_dir / "cli.js"
        cli_js.write_text(
            f"""import http.server, json, os, pathlib, signal, subprocess, sys, threading, time

mode_cfg = json.loads(pathlib.Path({str(mode_path)!r}).read_text(encoding="utf-8"))
subcmd = sys.argv[1] if len(sys.argv) > 1 else "mcp"

dump_data = {{
    "subcmd": subcmd,
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "env": dict(os.environ),
}}
pathlib.Path({str(dump_path)!r}).write_text(json.dumps(dump_data), encoding="utf-8")

if mode_cfg.get("ignore_term"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

grandchild = None
if mode_cfg.get("grandchild"):
    grandchild = subprocess.Popen(
        [sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"]
    )

pids = [str(os.getpid())]
if grandchild:
    pids.append(str(grandchild.pid))
pathlib.Path({str(pids_path)!r}).write_text("\\n".join(pids) + "\\n", encoding="utf-8")

if subcmd == "login":
    lmode = mode_cfg.get("login", "ok")
    print("Starting OAuth login code=oauth_secret_code_999 Bearer eyJloginBearer123 u-userTokenAbc ur-refreshTokenXyz", flush=True)
    if lmode == "hang":
        time.sleep(120)
    elif lmode == "fail":
        sys.stderr.write("Login failed\\n")
        sys.stderr.flush()
        sys.exit(1)
    print("Successfully exchanged authorization code", flush=True)
    sys.exit(0)

if subcmd == "logout":
    if mode_cfg.get("logout") == "fail":
        sys.stderr.write("Logout failed\\n")
        sys.stderr.flush()
        sys.exit(1)
    print("Logged out cleanly", flush=True)
    sys.exit(0)

# subcmd == "mcp"
for marker in mode_cfg.get("patches", []):
    sys.stderr.write(f"[toolbox-lark-patch] {{marker}}\\n")
if mode_cfg.get("keytar_disabled"):
    sys.stderr.write("[WARN] Builtin User Access Token Store will be disabled\\n")
sys.stderr.flush()

print(
    f"Lark starting with secret={{os.environ.get('APP_SECRET')}} "
    "Bearer eyJmcpBearerToken u-access12345 ur-refresh67890 code:my_auth_code_777",
    flush=True,
)
for extra_line in mode_cfg.get("extra_logs", []):
    print(extra_line, flush=True)

mcp_mode = mode_cfg.get("mcp", "normal")
if mcp_mode == "exit_early":
    sys.stderr.write("Fatal startup crash\\n")
    sys.stderr.flush()
    sys.exit(2)
if mcp_mode == "hang_no_listen":
    time.sleep(120)
    sys.exit(0)

port_idx = sys.argv.index("-p") + 1
listen_port = int(sys.argv[port_idx])

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            cur = json.loads(pathlib.Path({str(mode_path)!r}).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cur = {{}}
        if cur.get("drop_http") or cur.get("close_server"):
            # Close without response to simulate unhealthy endpoint
            return
        self.send_response(405)
        self.end_headers()
        self.wfile.write(b"Method Not Allowed")
    def log_message(self, *args):
        pass

class _NoDnsHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    def server_bind(self):
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

httpd = _NoDnsHTTPServer(("127.0.0.1", listen_port), Handler)
t = threading.Thread(target=httpd.serve_forever, kwargs={{"poll_interval": 0.02}}, daemon=True)
t.start()
listen_file = pathlib.Path({str(tmp_path)!r}) / f"lark_listen_{{listen_port}}.json"
listen_file.write_text(json.dumps({{"listening": True, "pid": os.getpid()}}), encoding="utf-8")
while True:
    try:
        cur = json.loads(pathlib.Path({str(mode_path)!r}).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {{}}
    if cur.get("close_server"):
        httpd.shutdown()
        httpd.server_close()
        listen_file.unlink(missing_ok=True)
        break
    time.sleep(0.05)
while True:
    time.sleep(1)
""",
            encoding="utf-8",
        )

    cfg = Config()
    cfg.revision = 1
    cfg.mcp.lark = LarkMcp(
        app_id="cli_test_app" if with_secret else "",
        domain="https://open.larksuite.com",
        port=chosen_port,
        owner_confirmed_at="2026-10-26T00:00:00Z" if owner_confirmed else None,
    )
    if with_runtime:
        cfg.mcp.runtime.node = NodeRuntime(
            source="detected", path=str(node_path), version="v24.13.0"
        )
    creds = MemoryCredentials()
    if with_secret:
        creds.set("lark_app_secret:cli_test_app", "lark_secret_val_987654321")
        cfg.credentials["lark_app_secret:cli_test_app"] = CredentialMeta(
            kind="lark_app_secret",
            ref="cli_test_app",
            source="manual",
            updated_at="2026-10-26T00:00:00Z",
        )
    store = ConfigStore(data_dir)
    store._write(cfg)
    return store, creds, chosen_port, mode_path


@pytest.mark.asyncio
async def test_lark_owner_unconfirmed_blocks_all_and_ownership_routes(
    isolated_supervisor, tmp_path
):
    data_dir = tmp_path / "data"
    store, creds, _, _ = _setup_fake_lark_env(
        data_dir, tmp_path, owner_confirmed=False
    )
    svc = McpService(
        store,
        creds,
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[tmp_path / "fake_lark_bin"],
    )
    for action in (svc.start_lark, svc.stop_lark, svc.login_lark, svc.logout_lark):
        with pytest.raises(SettingsError) as exc:
            await action()
        assert exc.value.code == "lark_owner_unconfirmed"
        assert exc.value.status == 409

    # Ownership POST without ack_old_app_stopped=True fails with 409
    with pytest.raises(SettingsError) as exc:
        await svc.confirm_lark_ownership(
            LarkOwnershipRequest(ack_old_app_stopped=False)
        )
    assert exc.value.code == "lark_owner_unconfirmed"

    # Ownership POST with ack_old_app_stopped=True succeeds
    snap = await svc.confirm_lark_ownership(
        LarkOwnershipRequest(ack_old_app_stopped=True)
    )
    assert snap.lark.owner_confirmed_at is not None

    # Ownership DELETE when stopped clears owner_confirmed_at
    snap2 = await svc.revoke_lark_ownership()
    assert snap2.lark.owner_confirmed_at is None


@pytest.mark.asyncio
async def test_lark_not_configured_and_runtime_missing_gates(
    isolated_supervisor, tmp_path
):
    # 1. Secret not configured -> 409 lark_not_configured
    d1 = tmp_path / "d1"
    store1, creds1, _, _ = _setup_fake_lark_env(
        d1, tmp_path, owner_confirmed=True, with_secret=False
    )
    svc1 = McpService(store1, creds1, MemoryCredentials(), events=EventHub())
    with pytest.raises(SettingsError) as exc:
        await svc1.start_lark()
    assert exc.value.code == "lark_not_configured"
    assert exc.value.status == 409

    # 2. Runtime missing -> 409 mcp_runtime_missing
    d2 = tmp_path / "d2"
    store2, creds2, _, _ = _setup_fake_lark_env(
        d2, tmp_path, owner_confirmed=True, with_secret=True, with_runtime=False
    )
    svc2 = McpService(
        store2, creds2, MemoryCredentials(), events=EventHub(), path_extras=[]
    )
    with pytest.raises(SettingsError) as exc:
        await svc2.start_lark()
    assert exc.value.code == "mcp_runtime_missing"
    assert exc.value.status == 409


@pytest.mark.asyncio
async def test_lark_port_in_use_returns_409(isolated_supervisor, tmp_path):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    occupied_port = sock.getsockname()[1]
    try:
        data_dir = tmp_path / "data"
        store, creds, _, _ = _setup_fake_lark_env(
            data_dir, tmp_path, port=occupied_port
        )
        svc = McpService(
            store,
            creds,
            MemoryCredentials(),
            events=EventHub(),
            path_extras=[tmp_path / "fake_lark_bin"],
        )
        with pytest.raises(SettingsError) as exc:
            await svc.start_lark()
        assert exc.value.code == "mcp_port_in_use"
        assert exc.value.status == 409
    finally:
        sock.close()


def test_is_port_in_use_sets_so_reuseaddr_to_ignore_time_wait(monkeypatch):
    """Regression: after probe_lark_http + stop_lark (e.g. during login_lark restart),
    the server's accepted socket is in TIME_WAIT. is_port_in_use must set SO_REUSEADDR
    on its bind probe so TIME_WAIT is not mistaken for an active listener."""
    real_socket = socket.socket

    class TimeWaitSimSocket:
        def __init__(self, *args, **kwargs):
            self._sock = real_socket(*args, **kwargs)
            self._reuseaddr = False

        def __enter__(self):
            self._sock.__enter__()
            return self

        def __exit__(self, *exc):
            return self._sock.__exit__(*exc)

        def settimeout(self, val):
            self._sock.settimeout(val)

        def setsockopt(self, level, optname, value):
            if level == socket.SOL_SOCKET and optname == socket.SO_REUSEADDR and value:
                self._reuseaddr = True
            self._sock.setsockopt(level, optname, value)

        def connect_ex(self, addr):
            # In TIME_WAIT (no listener), connect_ex returns ECONNREFUSED
            import errno as _errno
            return _errno.ECONNREFUSED

        def bind(self, addr):
            if not self._reuseaddr:
                import errno as _errno
                raise OSError(_errno.EADDRINUSE, "Address already in use (TIME_WAIT without SO_REUSEADDR)")
            return self._sock.bind(addr)

    free_p = _free_port()
    monkeypatch.setattr(socket, "socket", TimeWaitSimSocket)
    assert is_port_in_use(free_p) is False



@pytest.mark.asyncio
async def test_lark_start_running_env_argv_logs_redaction_and_stop(
    isolated_supervisor, tmp_path, monkeypatch
):
    monkeypatch.setenv("APP_ID", "parent_app_id_must_strip")
    monkeypatch.setenv("LARK_TOKEN", "parent_lark_tok_must_strip")
    monkeypatch.setenv("USER_ACCESS_TOKEN", "parent_uat_must_strip")

    data_dir = tmp_path / "data"
    dump_file = tmp_path / "lark_dump.json"
    store, creds, port, _ = _setup_fake_lark_env(
        data_dir, tmp_path, dump_file=dump_file
    )
    svc = McpService(
        store,
        creds,
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[tmp_path / "fake_lark_bin"],
    )
    svc.lark_http_prober = _make_lark_prober(tmp_path)
    try:
        req_id = uuid4()
        snap = await svc.start_lark(LarkActionRequest(request_id=req_id))
        assert snap.lark.state == "running"
        assert snap.lark.patches.all_applied is True
        assert snap.lark.keytar_available is True

        # Idempotent duplicate request_id returns same snapshot without error
        snap_dup = await svc.start_lark(LarkActionRequest(request_id=req_id))
        assert snap_dup.lark.state == "running"

        # Inspect child argv / env / cwd
        dump = json.loads(dump_file.read_text(encoding="utf-8"))
        argv = dump["argv"]
        env = dump["env"]
        assert "--debug" in argv
        assert "-m" in argv and "streamable" in argv
        assert "-s" not in argv and "--app-secret" not in argv
        assert "lark_secret_val_987654321" not in " ".join(argv)
        assert env.get("APP_SECRET") == "lark_secret_val_987654321"
        assert "APP_ID" not in env
        assert "USER_ACCESS_TOKEN" not in env
        assert not any(k.startswith("LARK_") for k in env)
        assert "lark_mcp_patches.js" in env.get("NODE_OPTIONS", "")
        assert dump["cwd"].endswith("/mcp/run/lark")

        # Verify ownership revoke and port/app_id patch are blocked while running
        with pytest.raises(SettingsError) as exc:
            await svc.revoke_lark_ownership()
        assert exc.value.code == "mcp_busy"

        with pytest.raises(SettingsError) as exc:
            await svc.patch(
                MCPSettingsPatch(
                    revision=snap.revision,
                    lark=LarkMcp(
                        app_id="cli_other",
                        port=port + 1,
                        owner_confirmed_at=snap.lark.owner_confirmed_at,
                    ),
                )
            )
        assert exc.value.code == "mcp_busy"

        # Verify log file permissions (0600) and redaction
        log_file = data_dir / "mcp/logs/lark-mcp.log"
        async with asyncio.timeout(3):
            while not log_file.exists() or "Lark starting" not in log_file.read_text(  # noqa: ASYNC110
                encoding="utf-8"
            ):
                await asyncio.sleep(0.05)
        assert log_file.stat().st_mode & 0o777 == 0o600
        log_text = log_file.read_text(encoding="utf-8")
        assert "lark_secret_val_987654321" not in log_text
        assert "eyJmcpBearerToken" not in log_text
        assert "u-access12345" not in log_text
        assert "ur-refresh67890" not in log_text
        assert "my_auth_code_777" not in log_text

        # Stop Lark MCP
        stopped_snap = await svc.stop_lark()
        assert stopped_snap.lark.state == "stopped"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_lark_running_degraded_when_patch_skipped_or_keytar_disabled(
    isolated_supervisor, tmp_path
):
    data_dir = tmp_path / "data"
    store, creds, _, mode_path = _setup_fake_lark_env(data_dir, tmp_path)
    mode_path.write_text(
        json.dumps(
            {
                "mcp": "normal",
                "patches": ["auth_store=applied", "oidc=skipped", "mcp_tool=applied"],
                "keytar_disabled": True,
            }
        ),
        encoding="utf-8",
    )
    svc = McpService(
        store,
        creds,
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[tmp_path / "fake_lark_bin"],
    )
    svc.lark_http_prober = _make_lark_prober(tmp_path)
    try:
        snap = await svc.start_lark()
        assert snap.lark.state == "running_degraded"
        assert snap.lark.patches.all_applied is False
        assert snap.lark.keytar_available is False
        assert any("刷新补丁未生效" in w for w in snap.lark.warnings)
        assert any("令牌存储不可用" in w for w in snap.lark.warnings)
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_lark_early_exit_and_start_timeout_enter_failed_and_snapshot_nonblocking(
    isolated_supervisor, tmp_path
):
    data_dir = tmp_path / "data"
    pid_file = tmp_path / "timeout_pids.txt"
    store, creds, _, mode_path = _setup_fake_lark_env(
        data_dir, tmp_path, pid_file=pid_file
    )
    svc = McpService(
        store,
        creds,
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[tmp_path / "fake_lark_bin"],
    )
    svc.lark_http_prober = _make_lark_prober(tmp_path)
    svc.start_timeout_s = 0.8

    try:
        # 1. Early exit -> failed(exited)
        mode_path.write_text(
            json.dumps({"mcp": "exit_early", "patches": []}), encoding="utf-8"
        )
        snap = await svc.start_lark()
        assert snap.lark.state == "failed"
        assert snap.lark.last_error == "exited"
        assert "Fatal startup crash" in snap.lark.log_tail

        # 2. Startup timeout -> failed(start_timeout), process group reaped, snapshot non-blocking during start
        mode_path.write_text(
            json.dumps(
                {
                    "mcp": "hang_no_listen",
                    "patches": [],
                    "ignore_term": True,
                    "grandchild": True,
                }
            ),
            encoding="utf-8",
        )
        start_task = asyncio.create_task(svc.start_lark())
        async with asyncio.timeout(3):
            while svc._lark_state != "starting":  # noqa: ASYNC110
                await asyncio.sleep(0.02)
        mid_snap = await asyncio.wait_for(svc.snapshot(), timeout=0.2)
        assert mid_snap.lark.state == "starting"

        final_snap = await start_task
        assert final_snap.lark.state == "failed"
        assert final_snap.lark.last_error == "start_timeout"

        pids = [int(x) for x in pid_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_lark_health_probe_marks_unhealthy_after_3_failures(
    isolated_supervisor, tmp_path
):
    data_dir = tmp_path / "data"
    store, creds, _, _ = _setup_fake_lark_env(data_dir, tmp_path)
    svc = McpService(
        store,
        creds,
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[tmp_path / "fake_lark_bin"],
    )
    probe_healthy = True
    tick_gate: asyncio.Queue[float] = asyncio.Queue()
    tick_done: asyncio.Queue[str] = asyncio.Queue()

    async def deterministic_prober(port: int, timeout_s: float = 0.5) -> bool:
        # A real HTTP probe only succeeds once the fake server listens, by which
        # time its stderr patch markers are out; mirror that so start_lark does
        # not judge patch state before the fake process has printed anything.
        for _ in range(200):
            if svc._lark_patches.all_applied:
                break
            await asyncio.sleep(0.01)
        return probe_healthy

    async def deterministic_health_sleep(interval_s: float) -> None:
        # Record state after previous tick (if any) and wait for next deterministic tick
        await tick_done.put(svc._lark_state)
        await tick_gate.get()

    svc.lark_http_prober = deterministic_prober
    svc.health_sleep = deterministic_health_sleep
    try:
        snap = await svc.start_lark()
        assert snap.lark.state == "running"

        # Wait until _lark_health_loop enters its first health_sleep
        initial_state = await asyncio.wait_for(tick_done.get(), timeout=2.0)
        assert initial_state == "running"

        # Simulate endpoint becoming unreachable while process stays alive
        probe_healthy = False

        # Failure 1 -> still running
        await tick_gate.put(0.0)
        after_1 = await asyncio.wait_for(tick_done.get(), timeout=2.0)
        assert after_1 == "running"

        # Failure 2 -> still running
        await tick_gate.put(0.0)
        after_2 = await asyncio.wait_for(tick_done.get(), timeout=2.0)
        assert after_2 == "running"

        # Failure 3 -> transitions deterministically to unhealthy
        await tick_gate.put(0.0)
        after_3 = await asyncio.wait_for(tick_done.get(), timeout=2.0)
        assert after_3 == "unhealthy"

        unhealthy_snap = await svc.snapshot()
        assert unhealthy_snap.lark.state == "unhealthy"
        assert unhealthy_snap.lark.last_error == "health_check_failed"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_backend_sigkill_reaps_lark_and_grandchild(tmp_path):
    """When backend process is killed with SIGKILL, proc_supervisor reaps lark-mcp and grandchild."""
    data_dir = tmp_path / "data"
    pid_file = tmp_path / "sigkill_pids.txt"
    _, _, _, mode_path = _setup_fake_lark_env(
        data_dir, tmp_path, pid_file=pid_file
    )
    mode_path.write_text(
        json.dumps(
            {
                "mcp": "normal",
                "patches": ["auth_store=applied", "oidc=applied", "mcp_tool=applied"],
                "ignore_term": True,
                "grandchild": True,
            }
        ),
        encoding="utf-8",
    )
    helper_code = """
import asyncio, json, os, socket, sys
from pathlib import Path
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.mcp.lark_logs import probe_lark_http
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.mcp import McpService

original = asyncio.create_subprocess_exec
async def spawn(*argv, **kw):
    if len(argv) >= 3 and argv[1:3] == ('-m', 'toolbox_backend.adapters.proc_supervisor'):
        argv = (
            argv[0],
            '-c',
            'import sys; from toolbox_backend.adapters import proc_supervisor as m; m.process_identity=lambda pid: {}; sys.exit(m.main())',
        )
    return await original(*argv, **kw)
asyncio.create_subprocess_exec = spawn

async def main():
    data_dir = Path(sys.argv[1])
    bin_dir = Path(sys.argv[2])
    tmp_dir = Path(sys.argv[3])
    store = ConfigStore(data_dir)
    creds = MemoryCredentials()
    creds.set('lark_app_secret:cli_test_app', 'lark_secret_val_987654321')
    svc = McpService(store, creds, MemoryCredentials(), events=EventHub(), path_extras=[bin_dir])
    async def _prober(port: int, timeout_s: float = 0.5) -> bool:
        if await probe_lark_http(port, timeout_s):
            return True
        f = tmp_dir / f'lark_listen_{port}.json'
        if not f.is_file():
            return False
        data = json.loads(f.read_text(encoding='utf-8'))
        os.kill(int(data['pid']), 0)
        return bool(data.get('listening'))
    svc.lark_http_prober = _prober
    snap = await svc.start_lark()
    print(json.dumps({'state': snap.lark.state, 'pid': snap.lark.pid}), flush=True)
    await asyncio.Event().wait()

asyncio.run(main())
"""
    helper = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        helper_code,
        str(data_dir),
        str(tmp_path / "fake_lark_bin"),
        str(tmp_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    pids = []
    try:
        line = await asyncio.wait_for(helper.stdout.readline(), timeout=8)
        assert line
        info = json.loads(line)
        assert info["state"] == "running"

        async with asyncio.timeout(3):
            while not pid_file.exists():  # noqa: ASYNC110
                await asyncio.sleep(0.02)
            pids = [
                int(x)
                for x in pid_file.read_text(encoding="utf-8").splitlines()
                if x.strip()
            ]
        assert len(pids) == 2

        helper.kill()
        await asyncio.wait_for(helper.wait(), timeout=2)

        def alive(pid: int) -> bool:
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False

        async with asyncio.timeout(5):
            while any(alive(p) for p in pids):  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        for p in pids:
            assert not alive(p)
    finally:
        if helper.returncode is None:
            helper.kill()
            await helper.communicate()
        for p in pids:
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.asyncio
async def test_lark_login_busy_cancel_timeout_success_logout_and_token_status(
    isolated_supervisor, tmp_path
):
    data_dir = tmp_path / "data"
    dump_file = tmp_path / "login_dump.json"
    pid_file = tmp_path / "login_pids.txt"
    store, creds, _, mode_path = _setup_fake_lark_env(
        data_dir, tmp_path, dump_file=dump_file, pid_file=pid_file
    )
    svc = McpService(
        store,
        creds,
        MemoryCredentials(),
        events=EventHub(),
        path_extras=[tmp_path / "fake_lark_bin"],
    )
    svc.lark_http_prober = _make_lark_prober(tmp_path)
    try:
        # 1. Hang login -> test busy rejection & cancel
        mode_path.write_text(
            json.dumps(
                {
                    "mcp": "normal",
                    "patches": ["auth_store=applied", "oidc=applied", "mcp_tool=applied"],
                    "login": "hang",
                    "ignore_term": True,
                    "grandchild": True,
                }
            ),
            encoding="utf-8",
        )
        pid_file.unlink(missing_ok=True)
        login_task = asyncio.create_task(svc.login_lark())
        async with asyncio.timeout(3):
            while svc._lark_state != "logging_in" or not pid_file.exists():  # noqa: ASYNC110
                await asyncio.sleep(0.02)

        # Start during login must be rejected with 409 mcp_busy
        with pytest.raises(SettingsError) as exc:
            await svc.start_lark()
        assert exc.value.code == "mcp_busy"

        # Cancel login -> reaps login process group
        cancel_snap = await svc.cancel_lark_login()
        assert cancel_snap.lark.state == "stopped"
        await login_task
        pids = [int(x) for x in pid_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        for p in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(p, 0)

        # 2. Login timeout -> enters failed(login_timeout) and reaps group
        svc.login_timeout_s = 0.5
        timeout_snap = await svc.login_lark()
        assert timeout_snap.lark.state == "failed"
        assert timeout_snap.lark.last_error == "login_timeout"
        svc.login_timeout_s = 300.0

        # 3. Start server -> then run successful login -> stops server, logs in, writes metadata, restarts server!
        mode_path.write_text(
            json.dumps(
                {
                    "mcp": "normal",
                    "patches": ["auth_store=applied", "oidc=applied", "mcp_tool=applied"],
                    "login": "ok",
                    "logout": "ok",
                }
            ),
            encoding="utf-8",
        )
        snap_running = await svc.start_lark()
        assert snap_running.lark.state == "running"

        snap_logged_in = await svc.login_lark()
        assert snap_logged_in.lark.state == "running"
        assert snap_logged_in.lark.login.logged_in_at is not None
        assert snap_logged_in.lark.login.scope is not None
        assert snap_logged_in.lark.token_status.state == "ok"

        # Verify login argv did not contain APP_SECRET
        login_dump = json.loads(dump_file.read_text(encoding="utf-8"))
        assert "lark_secret_val_987654321" not in " ".join(login_dump["argv"])

        # 4. Token refresh failed log -> token_status becomes refresh_failing
        log_file = data_dir / "mcp/logs/lark-mcp.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write("[ERROR] Token refresh failed: invalid grant\n")
        snap_failing = await svc.snapshot()
        assert snap_failing.lark.token_status.state == "refresh_failing"

        with log_file.open("a", encoding="utf-8") as f:
            f.write("[INFO] Successfully refreshed token\n")
        snap_recovered = await svc.snapshot()
        assert snap_recovered.lark.token_status.state == "ok"

        # 5. Logout -> stops server, clears login metadata, warns about CLI bearer invalidation
        snap_logout = await svc.logout_lark()
        assert snap_logout.lark.state == "stopped"
        assert snap_logout.lark.login.logged_in_at is None
        assert snap_logout.lark.token_status.state == "unknown"
        assert any("旧 bearer" in w for w in snap_logout.lark.warnings)
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_lark_http_routes_end_to_end(isolated_supervisor, tmp_path):
    data_dir = tmp_path / "data"
    _, creds, _, _ = _setup_fake_lark_env(data_dir, tmp_path, owner_confirmed=False)
    app = create_app(
        Settings(token="tok-lark-s6b", port=59999, data_dir=data_dir),
        credentials=creds,
        legacy_credentials=MemoryCredentials(),
    )
    app.state.mcp_service.path_extras = [tmp_path / "fake_lark_bin"]
    app.state.mcp_service.lark_http_prober = _make_lark_prober(tmp_path)
    headers = {"Authorization": "Bearer tok-lark-s6b"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:59999") as client:
            # Unconfirmed start -> 409
            r0 = await client.post("/api/mcp/lark/start", json={}, headers=headers)
            assert r0.status_code == 409
            assert r0.json()["detail"]["code"] == "lark_owner_unconfirmed"

            # Confirm ownership
            r1 = await client.post(
                "/api/mcp/lark/ownership",
                json={"ack_old_app_stopped": True},
                headers=headers,
            )
            assert r1.status_code == 200
            assert r1.json()["lark"]["owner_confirmed_at"] is not None

            # Start
            r2 = await client.post("/api/mcp/lark/start", json={}, headers=headers)
            assert r2.status_code == 200
            assert r2.json()["lark"]["state"] == "running"

            # Stop
            r3 = await client.post("/api/mcp/lark/stop", json={}, headers=headers)
            assert r3.status_code == 200
            assert r3.json()["lark"]["state"] == "stopped"

            # Login & Logout & Cancel routes
            r4 = await client.post("/api/mcp/lark/login", json={}, headers=headers)
            assert r4.status_code == 200
            assert r4.json()["lark"]["login"]["logged_in_at"] is not None

            r5 = await client.post("/api/mcp/lark/login/cancel", json={}, headers=headers)
            assert r5.status_code == 200

            r6 = await client.post("/api/mcp/lark/logout", json={}, headers=headers)
            assert r6.status_code == 200
            assert r6.json()["lark"]["login"]["logged_in_at"] is None

            # Revoke ownership
            r7 = await client.delete("/api/mcp/lark/ownership", headers=headers)
            assert r7.status_code == 200
            assert r7.json()["lark"]["owner_confirmed_at"] is None
    finally:
        await app.state.mcp_service.close()


@pytest.mark.asyncio
async def test_lark_real_tcp_http_405_probe():
    if _sandbox_blocks_loopback_connect():
        pytest.skip("sandbox forbids loopback TCP connect")
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(405)
            self.end_headers()
        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert await probe_lark_http(port) is True
    finally:
        srv.shutdown()
        srv.server_close()
