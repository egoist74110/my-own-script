"""Runtime process-group tests; ps identity is isolated because sandbox forbids /bin/ps."""

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from toolbox_backend.adapters.ai_process import SupervisedProcess

FAKE = Path(__file__).parent / "fixtures/fake_cli/fake.py"
SUPERVISOR = "toolbox_backend.adapters.proc_supervisor"
BOOT = (
    "import sys; import toolbox_backend.adapters.proc_supervisor as m; "
    'm.process_identity=lambda pid: {"proc_start_time":"test-only","executable":sys.executable}; '
    "sys.exit(m.main())"
)


@pytest.fixture
def isolated_supervisor(monkeypatch, tmp_path):
    original = asyncio.create_subprocess_exec

    async def spawn(*argv, **kwargs):
        if len(argv) >= 3 and argv[1:3] == ("-m", SUPERVISOR):
            argv = (argv[0], "-c", BOOT)
        return await original(*argv, **kwargs)

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(FAKE.parent) + ":/usr/bin:/bin")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)


@pytest.mark.asyncio
async def test_supervisor_pipe_normal_exit_with_mocked_ps(isolated_supervisor, tmp_path):
    owner = await SupervisedProcess.start(
        [sys.executable, str(FAKE), "--version"], str(tmp_path), path_extras=[]
    )
    try:
        assert owner.identity["pgid"] == owner.identity["pid"]
        assert await owner.proc.stdout.readline() == b"toolbox-fake-ai 1.0\n"
        assert await owner.proc.wait() == 0
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_supervisor_parallel_ignore_term_cleanup_with_mocked_ps(
    isolated_supervisor, tmp_path
):
    owners = []
    try:
        for _ in range(3):
            owners.append(
                await SupervisedProcess.start(
                    [sys.executable, str(FAKE), "--ignore-term"], str(tmp_path), path_extras=[]
                )
            )
        for owner in owners:
            assert await owner.proc.stdout.readline() == b"ready\n"
        start = time.monotonic()
        await asyncio.gather(*(owner.close() for owner in owners))
        assert time.monotonic() - start < 5
        for owner in owners:
            with pytest.raises(ProcessLookupError):
                os.kill(owner.identity["pid"], 0)
    finally:
        await asyncio.gather(*(owner.close() for owner in owners))


@pytest.mark.asyncio
async def test_supervisor_cli_env_and_controlling_terminal(
    isolated_supervisor, tmp_path, monkeypatch
):
    import json
    import pty

    monkeypatch.setenv("S5A_PAT", "s5a-fake-pat-secret-runtime")
    monkeypatch.setenv("S5A_TOKEN", "s5a-fake-token-secret-runtime")
    master, slave = pty.openpty()
    owner = None
    try:
        owner = await SupervisedProcess.start(
            [sys.executable, str(FAKE), "--echo", "--env"],
            str(tmp_path),
            slave=slave,
            path_extras=[],
        )
        os.close(slave)
        slave = -1
        pid = owner.identity["pid"]
        assert os.getpgid(pid) == pid
        assert os.getsid(pid) == pid
        assert os.tcgetpgrp(master) == pid
        os.set_blocking(master, False)
        output = bytearray()
        async with asyncio.timeout(3):
            while b"ready" not in output:
                try:
                    output.extend(os.read(master, 65536))
                except BlockingIOError:
                    await asyncio.sleep(0.01)
        env = json.loads(output.splitlines()[0])
        assert "S5A_PAT" not in env and "S5A_TOKEN" not in env
        assert env["HOME"] == str(tmp_path)
        assert env["COLORTERM"] == "truecolor"
        assert not any(k.startswith("TOOLBOX_") for k in env)
    finally:
        if owner:
            await owner.close()
        if slave >= 0:
            os.close(slave)
        os.close(master)


def test_backend_never_forks_outside_isolated_supervisor():
    source = Path(__file__).parents[1] / "src/toolbox_backend"
    violations = []
    for path in source.rglob("*.py"):
        if path.name != "proc_supervisor.py" and "os.fork(" in path.read_text():
            violations.append(str(path))
    assert violations == []


@pytest.mark.asyncio
async def test_service_shutdown_parallel_term_ignoring_ptys(isolated_supervisor, tmp_path):
    import shlex
    import sqlite3
    from uuid import uuid4

    from toolbox_backend.adapters.ai_store import AIStore
    from toolbox_backend.adapters.config_store import ConfigStore
    from toolbox_backend.api.ai_schemas import SessionCreate
    from toolbox_backend.domain.settings import LocalRepo
    from toolbox_backend.services.ai_sessions import AISessionService
    from toolbox_backend.services.events import EventHub

    data = tmp_path / "data"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigStore(data)

    def configure(c):
        c.ado.local_repos.append(LocalRepo(id="repo", name="repo", path=str(repo)))
        c.ai.profiles[0].command = shlex.join([sys.executable, str(FAKE), "--ignore-term"])

    await config.update(0, configure)
    store = AIStore(data)
    service = AISessionService(config, store, EventHub(), path_extras=[])
    await service.initialize()
    pids = []
    try:
        for _ in range(3):
            view = await service.create(
                SessionCreate(
                    request_id=uuid4(), kind="terminal", profile_id="codex", repo_id="repo"
                )
            )
            assert view.state == "idle"
        pids = await store.call(
            lambda: [
                r[0]
                for r in store.require().execute(
                    "SELECT pid FROM ai_processes WHERE ended_at IS NULL"
                )
            ]
        )
        # The fixture announces readiness only after installing SIGTERM handling.
        async with asyncio.timeout(3):
            for terminal in service.terminals.values():
                while b"ready" not in terminal.buffer:
                    terminal.changed.clear()
                    await terminal.changed.wait()
        started = time.monotonic()
        await service.close()
        assert time.monotonic() - started < 5
        assert service._active == {}
        assert all(terminal.closed for terminal in service.terminals.values())
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        with sqlite3.connect(data / "ai.sqlite3") as db:
            rows = db.execute("SELECT state,ended_reason FROM ai_sessions").fetchall()
            assert rows == [("ended", "interrupted_on_exit")] * 3
            assert (
                db.execute("SELECT count(*) FROM ai_processes WHERE ended_at IS NULL").fetchone()[0]
                == 0
            )
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_killed_controller_reaps_cli_and_grandchild_without_ps(isolated_supervisor, tmp_path):
    import json

    pid_file = tmp_path / "owned-pids"
    helper_code = """
import asyncio, json, sys
from toolbox_backend.adapters.ai_process import SupervisedProcess
BOOT = sys.argv[1]
original = asyncio.create_subprocess_exec
async def spawn(*argv, **kw):
    if argv[1:3] == ('-m', 'toolbox_backend.adapters.proc_supervisor'):
        argv = (argv[0], '-c', BOOT)
    return await original(*argv, **kw)
asyncio.create_subprocess_exec = spawn
async def main():
    owner = await SupervisedProcess.start(
        [sys.executable, sys.argv[2], '--ignore-term', '--grandchild', '--pid-file', sys.argv[3]],
        sys.argv[4], path_extras=[])
    print(json.dumps({'supervisor':owner.proc.pid, 'pgid':owner.identity['pgid']}), flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
"""
    helper = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        helper_code,
        BOOT,
        str(FAKE),
        str(pid_file),
        str(tmp_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    record = None
    pids = []

    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    try:
        line = await asyncio.wait_for(helper.stdout.readline(), 8)
        assert line
        record = json.loads(line)
        async with asyncio.timeout(3):
            while len(pids) < 2:
                if pid_file.exists():
                    pids = [int(value) for value in pid_file.read_text().splitlines()]
                await asyncio.sleep(0.01)
        helper.kill()
        await asyncio.wait_for(helper.wait(), 2)
        async with asyncio.timeout(5):
            while any(alive(pid) for pid in [record["supervisor"], *pids]):  # noqa: ASYNC110
                # Reparented processes do not expose an asyncio child-wait handle.
                await asyncio.sleep(0.02)
        assert len(pids) == 2
    finally:
        if helper.returncode is None:
            helper.kill()
        await helper.communicate()
        if record and any(alive(pid) for pid in pids):
            try:
                os.killpg(record["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
