"""S6-B regression tests for Figma MCP wrapper and /api/mcp/figma/self-test."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from keyring.backend import KeyringBackend

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.mcp import NodeRuntime
from toolbox_backend.domain.settings import Config, CredentialMeta
from toolbox_backend.settings import Settings


class EnvTestKeyring(KeyringBackend):
    """Test-only keyring reading from TEST_FIGMA_KEYRING_VALUE env var."""

    priority = 100

    def get_password(self, service, username):
        if service == "toolbox-next" and username == "figma_token":
            return os.environ.get("TEST_FIGMA_KEYRING_VALUE") or None
        return None

    def set_password(self, service, username, password):
        pass

    def delete_password(self, service, username):
        pass


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


def _setup_fake_figma_runtime(
    data_dir: Path,
    tmp_path: Path,
    *,
    ignore_term: bool = False,
    spawn_grandchild: bool = False,
    pid_file: Path | None = None,
) -> Path:
    data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    data_dir.chmod(0o700)

    bin_dir = tmp_path / "fake_node_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    node_path = bin_dir / "node"
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

    from toolbox_backend.mcp.runner import secure_directory

    pkg_root = secure_directory(data_dir, "mcp", "packages")
    figma_dir = pkg_root / "node_modules/figma-developer-mcp/dist"
    figma_dir.mkdir(parents=True, exist_ok=True)
    (figma_dir.parent / "package.json").write_text(
        '{"version": "0.13.2"}', encoding="utf-8"
    )
    lark_dir = pkg_root / "node_modules/@larksuiteoapi/lark-mcp/dist"
    lark_dir.mkdir(parents=True, exist_ok=True)
    (lark_dir / "cli.js").write_text("// fake\n", encoding="utf-8")
    (lark_dir.parent / "package.json").write_text(
        '{"version": "0.5.1"}', encoding="utf-8"
    )

    bin_js = figma_dir / "bin.js"
    bin_js.write_text(
        f"""import json, os, pathlib, signal, subprocess, sys, time
if {ignore_term!r}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild = None
if {spawn_grandchild!r}:
    grandchild = subprocess.Popen(
        [sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"]
    )
if {str(pid_file) if pid_file else None!r}:
    pids = [str(os.getpid())]
    if grandchild:
        pids.append(str(grandchild.pid))
    pathlib.Path({str(pid_file) if pid_file else ""!r}).write_text("\\n".join(pids) + "\\n", encoding="utf-8")

info = {{
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "env": {{
        k: os.environ.get(k)
        for k in (
            "FIGMA_API_KEY",
            "FRAMELINK_TELEMETRY",
            "DO_NOT_TRACK",
            "FIGMA_MAX_CONCURRENCY",
            "FIGMA_MIN_INTERVAL_MS",
            "FIGMA_MAX_RETRY",
            "NODE_OPTIONS",
            "APP_SECRET",
            "LARK_DOMAIN",
        )
    }},
}}
for raw in sys.stdin:
    q = json.loads(raw)
    if "id" not in q:
        continue
    if q.get("method") == "initialize":
        res = {{"protocolVersion": "2025-06-18", "serverInfo": {{"name": "figma-fake"}}}}
    elif q.get("method") == "tools/list":
        res = {{"tools": [{{"name": "get_figma_data"}}, {{"name": "download_figma_images"}}]}}
    else:
        res = info
    print(json.dumps({{"jsonrpc": "2.0", "id": q["id"], "result": res}}), flush=True)
""",
        encoding="utf-8",
    )

    cfg = Config()
    cfg.revision = 1
    cfg.mcp.runtime.node = NodeRuntime(
        source="detected", path=str(node_path), version="v24.13.0"
    )
    cfg.mcp.figma.max_concurrency = 3
    cfg.mcp.figma.min_interval_ms = 450
    cfg.mcp.figma.max_retry = 5
    cfg.credentials["figma_token"] = CredentialMeta(
        kind="figma_token", ref="figma", source="manual", updated_at="2026-10-26T00:00:00Z"
    )
    ConfigStore(data_dir)._write(cfg)
    return node_path


def test_figma_wrapper_missing_token_exits_2(tmp_path):
    data_dir = tmp_path / "data"
    _setup_fake_figma_runtime(data_dir, tmp_path)
    env = {
        **os.environ,
        "PYTHON_KEYRING_BACKEND": "tests.test_s6b_figma.EnvTestKeyring",
        "TEST_FIGMA_KEYRING_VALUE": "",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "toolbox_backend.mcp.figma_wrapper",
            "--data-dir",
            str(data_dir),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )
    assert proc.returncode == 2
    assert "figma_token" in proc.stderr or "Figma" in proc.stderr


def test_figma_wrapper_env_cwd_args_and_stdin_eof_reaps_group(tmp_path):
    """Wrapper passes expected args/env/cwd and reaps child + grandchild on stdin EOF."""
    data_dir = tmp_path / "data"
    caller_cwd = tmp_path / "caller_workspace"
    caller_cwd.mkdir()
    pid_file = tmp_path / "figma_pids.txt"
    _setup_fake_figma_runtime(
        data_dir, tmp_path, ignore_term=True, spawn_grandchild=True, pid_file=pid_file
    )

    env = {
        **os.environ,
        "PYTHON_KEYRING_BACKEND": "tests.test_s6b_figma.EnvTestKeyring",
        "TEST_FIGMA_KEYRING_VALUE": "figd_secret_token_value_123",
        "APP_SECRET": "must_not_leak_lark_secret",
        "LARK_DOMAIN": "https://open.larksuite.com",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "toolbox_backend.mcp.figma_wrapper",
            "--data-dir",
            str(data_dir),
        ],
        cwd=caller_cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"inspect"}\n')
        proc.stdin.flush()
        line = proc.stdout.readline()
        assert line, proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        reply = json.loads(line)["result"]

        # Verify argv: --stdio --no-telemetry --image-dir <caller_cwd>
        assert "--stdio" in reply["argv"]
        assert "--no-telemetry" in reply["argv"]
        idx = reply["argv"].index("--image-dir")
        assert Path(reply["argv"][idx + 1]).resolve() == caller_cwd.resolve()
        assert "figd_secret_token_value_123" not in " ".join(reply["argv"])

        # Verify child cwd is <data-dir>/mcp/run/figma
        assert Path(reply["cwd"]).resolve() == (data_dir / "mcp/run/figma").resolve()

        # Verify child env
        c_env = reply["env"]
        assert c_env["FIGMA_API_KEY"] == "figd_secret_token_value_123"
        assert c_env["FRAMELINK_TELEMETRY"] == "off"
        assert c_env["DO_NOT_TRACK"] == "1"
        assert c_env["FIGMA_MAX_CONCURRENCY"] == "3"
        assert c_env["FIGMA_MIN_INTERVAL_MS"] == "450"
        assert c_env["FIGMA_MAX_RETRY"] == "5"
        assert "figma_mcp_concurrency.js" in (c_env["NODE_OPTIONS"] or "")
        assert c_env["APP_SECRET"] is None
        assert c_env["LARK_DOMAIN"] is None

        pids = [int(x) for x in pid_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert len(pids) == 2

        # Signal 1: stdin EOF -> reaps child & grandchild group
        proc.stdin.close()
        proc.wait(timeout=5)
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)


def test_figma_wrapper_sigterm_reaps_process_group(tmp_path):
    """Signal 2: SIGTERM to wrapper terminates child and grandchild even if ignoring SIGTERM."""
    data_dir = tmp_path / "data"
    pid_file = tmp_path / "sigterm_pids.txt"
    _setup_fake_figma_runtime(
        data_dir, tmp_path, ignore_term=True, spawn_grandchild=True, pid_file=pid_file
    )
    env = {
        **os.environ,
        "PYTHON_KEYRING_BACKEND": "tests.test_s6b_figma.EnvTestKeyring",
        "TEST_FIGMA_KEYRING_VALUE": "figd_secret_token_value_123",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "toolbox_backend.mcp.figma_wrapper",
            "--data-dir",
            str(data_dir),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_file.exists():
            time.sleep(0.05)
        pids = [int(x) for x in pid_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert len(pids) == 2

        proc.terminate()
        proc.wait(timeout=5)
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)


def test_figma_wrapper_ppid_change_reaps_process_group(tmp_path):
    """Signal 3: When parent process is killed (ppid changes), wrapper reaps child group and exits."""
    data_dir = tmp_path / "data"
    pid_file = tmp_path / "ppid_pids.txt"
    _setup_fake_figma_runtime(
        data_dir, tmp_path, ignore_term=True, spawn_grandchild=True, pid_file=pid_file
    )
    env = {
        **os.environ,
        "PYTHON_KEYRING_BACKEND": "tests.test_s6b_figma.EnvTestKeyring",
        "TEST_FIGMA_KEYRING_VALUE": "figd_secret_token_value_123",
    }
    bootstrap = """import subprocess, sys, time
p = subprocess.Popen(
    [sys.executable, "-m", "toolbox_backend.mcp.figma_wrapper", "--data-dir", sys.argv[1]],
    stdin=subprocess.PIPE,
)
print(p.pid, flush=True)
time.sleep(120)
"""
    parent = subprocess.Popen(
        [sys.executable, "-c", bootstrap, str(data_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    wrapper_pid = None
    pids = []
    try:
        assert parent.stdout is not None
        wrapper_pid = int(parent.stdout.readline().decode().strip())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_file.exists():
            time.sleep(0.05)
        pids = [int(x) for x in pid_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert len(pids) == 2

        # Kill the parent process with SIGKILL so wrapper's ppid changes
        parent.kill()
        parent.wait(timeout=3)

        # Wait up to 6s (<=2s ppid check + 3s TERM->KILL grace) for wrapper and group to exit
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            alive = False
            for pid in [wrapper_pid, *pids]:
                try:
                    os.kill(pid, 0)
                    alive = True
                except ProcessLookupError:
                    pass
            if not alive:
                break
            time.sleep(0.05)

        for pid in [wrapper_pid, *pids]:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        for pid in ([wrapper_pid] if wrapper_pid else []) + pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.asyncio
async def test_figma_self_test_route(isolated_supervisor, tmp_path):
    """POST /api/mcp/figma/self-test executes wrapper via generic runner and returns tools."""
    data_dir = tmp_path / "data"
    _setup_fake_figma_runtime(data_dir, tmp_path)
    creds = MemoryCredentials()
    creds.set("figma_token", "figd_self_test_token_12345")

    app = create_app(
        Settings(token="figma-test", port=12345, data_dir=data_dir),
        credentials=creds,
        legacy_credentials=MemoryCredentials(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:12345",
        headers={"Authorization": "Bearer figma-test"},
    ) as c:
        r = await c.post("/api/mcp/figma/self-test", json={"timeout_s": 10})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["server_name"] == "figma-fake"
        assert "get_figma_data" in body["tools"]
        assert "figd_self_test_token_12345" not in r.text
