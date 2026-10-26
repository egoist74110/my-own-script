import asyncio
import os
import signal
import sys

import pytest

from toolbox_backend.adapters.ai_process import SupervisedProcess
from toolbox_backend.mcp.runner import (
    CommandSpec,
    mcp_environment,
    prepare_run_directory,
    run_self_test,
)


@pytest.fixture(autouse=True)
async def isolated_supervisor(monkeypatch, tmp_path):
    original = asyncio.create_subprocess_exec
    original_start = SupervisedProcess.start
    owners = []

    async def spawn(*argv, **kwargs):
        if argv[1:3] == ("-m", "toolbox_backend.adapters.proc_supervisor"):
            argv = (
                argv[0],
                "-c",
                "import sys; from toolbox_backend.adapters import proc_supervisor as m; m.process_identity=lambda pid: {}; sys.exit(m.main())",
            )
        return await original(*argv, **kwargs)

    async def recorded_start(*args, **kwargs):
        owner = await original_start(*args, **kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr(SupervisedProcess, "start", staticmethod(recorded_start))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setenv("PATH", str(tmp_path))
    yield
    for owner in owners:
        assert owner.proc.returncode is not None
        assert owner.control is None and owner.status is None
        assert not owner._transports
        # Includes descendants that inherited the child's process group.
        try:
            os.killpg(owner.identity["pgid"], 0)
        except ProcessLookupError:
            pass
        else:
            os.killpg(owner.identity["pgid"], signal.SIGKILL)
            pytest.fail("self-test left an owned process group behind")


def test_mcp_env_and_empty_directory(tmp_path, monkeypatch):
    for key in [
        "APP_ID",
        "APP_SECRET",
        "LARK_DOMAIN",
        "USER_ACCESS_TOKEN",
        "FIGMA_X",
        "NODE_OPTIONS",
    ]:
        monkeypatch.setenv(key, "fake-secret-" + key)
    env = mcp_environment(path_extras=[])
    assert not set(env) & {
        "APP_ID",
        "APP_SECRET",
        "LARK_DOMAIN",
        "USER_ACCESS_TOKEN",
        "FIGMA_X",
        "NODE_OPTIONS",
    }
    path = prepare_run_directory(tmp_path, "ado")
    assert path.stat().st_mode & 0o777 == 0o700
    (path / ".env").write_text("EVIL=1")
    with pytest.raises(ValueError):
        prepare_run_directory(tmp_path, "ado")


@pytest.mark.parametrize(
    "mode", ["ok", "wrong", "exit", "hang", "stderr", "ignore_term", "grandchild"]
)
async def test_runner_fake_modes(tmp_path, mode):
    fake = tmp_path / "fake.py"
    fake.write_text("""import sys,json,time,signal,subprocess,os
mode=sys.argv[1]
if mode=='ignore_term': signal.signal(signal.SIGTERM,signal.SIG_IGN)
if mode=='grandchild': subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])
if mode=='exit': sys.exit(3)
if mode in ('hang','ignore_term','grandchild'): time.sleep(120)
if mode=='stderr': sys.stderr.write('Bearer fake_secret_0123456789\\n'*10000);sys.stderr.flush()
for line in sys.stdin:
 q=json.loads(line)
 if 'id' not in q: continue
 r={'protocolVersion':'2025-06-18','serverInfo':{'name':'fake'}} if q['method']=='initialize' else {'tools':[{'name':'fake_tool'}]}
 if mode=='wrong': r={}
 print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':r}),flush=True)
""")
    result = await run_self_test(
        CommandSpec(name="fake", argv=[sys.executable, str(fake), mode], path_extras=[]),
        tmp_path,
        timeout_s=8,
    )
    assert result.ok == (mode in ("ok", "stderr"))
    assert result.duration_ms < 8500
    assert len(result.stderr_tail.encode()) <= 65536
    assert "fake_secret_0123456789" not in result.stderr_tail


async def test_runner_cancel_reaps(tmp_path):
    fake = tmp_path / "wait.py"
    fake.write_text("import time\ntime.sleep(120)")
    task = asyncio.create_task(
        run_self_test(
            CommandSpec(name="fake", argv=[sys.executable, str(fake)], path_extras=[]), tmp_path
        )
    )
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_runner_child_argv_env_and_cwd_isolation(tmp_path, monkeypatch):
    import json

    for key in [
        "APP_ID",
        "APP_SECRET",
        "LARK_DOMAIN",
        "USER_ACCESS_TOKEN",
        "FIGMA_API_KEY",
        "NODE_OPTIONS",
    ]:
        monkeypatch.setenv(key, "env-fake-" + key)
    script = tmp_path / "echo.py"
    script.write_text("""import sys,os,json
print(json.dumps({'argv':sys.argv,'env':dict(os.environ),'cwd':os.getcwd()}),file=sys.stderr,flush=True)
for raw in sys.stdin:
 q=json.loads(raw)
 if 'id' not in q: continue
 r={'protocolVersion':'2025-06-18','serverInfo':{'name':'fake'}} if q['method']=='initialize' else {'tools':[]}
 print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':r}),flush=True)
""")
    r = await run_self_test(
        CommandSpec("echo", [sys.executable, str(script)], path_extras=[]), tmp_path
    )
    assert r.ok
    emitted = json.loads(r.stderr_tail)
    assert emitted["cwd"] == str(tmp_path / "mcp/run/echo")
    assert emitted["env"]["PATH"] == str(tmp_path)
    assert not any("env-fake-" in arg for arg in emitted["argv"])
    assert "env-fake-" not in r.stderr_tail


async def test_snapshot_does_not_wait_for_self_test(tmp_path, monkeypatch):
    from toolbox_backend.adapters.credentials import MemoryCredentials
    from toolbox_backend.api.mcp_schemas import SelfTestRequest, SelfTestResult
    from toolbox_backend.app import create_app
    from toolbox_backend.mcp import runner
    from toolbox_backend.settings import Settings

    entered, release = asyncio.Event(), asyncio.Event()

    async def wait(*_, **__):
        entered.set()
        await release.wait()
        return SelfTestResult(ok=True)

    monkeypatch.setattr(runner, "run_self_test", wait)
    app = create_app(
        Settings(token="snapshot-token", port=12345, data_dir=tmp_path),
        credentials=MemoryCredentials(),
    )
    service = app.state.mcp_service
    task = asyncio.create_task(service.self_test(SelfTestRequest()))
    try:
        await entered.wait()
        snapshot = await asyncio.wait_for(service.snapshot(), 0.2)
        assert snapshot.self_test_running
        from toolbox_backend.domain.errors import SettingsError

        with pytest.raises(SettingsError) as exc:
            await service.self_test(SelfTestRequest())
        assert exc.value.code == "mcp_busy"
    finally:
        release.set()
        await task
    assert not (await service.snapshot()).self_test_running
