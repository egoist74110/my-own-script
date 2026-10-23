import asyncio
import base64
import os
import shlex
import sqlite3
import stat
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from toolbox_backend.adapters.ai_store import AIStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.adapters.pty_terminal import PTYTerminal
from toolbox_backend.app import create_app
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import LocalRepo
from toolbox_backend.settings import Settings

PYTHON_NAME = Path(sys.executable).resolve().name
FAKE = Path(__file__).parent / "fixtures/fake_cli/fake.py"


class FakeProcess:
    owners = []

    def __init__(self):
        self.event = asyncio.Event()
        self.identity = dict(
            pid=999990, pgid=999990, proc_start_time="fake-start", executable="/fake"
        )
        self.proc = self
        self.stdout = asyncio.StreamReader()
        self.closed = False
        self.__class__.owners.append(self)

    @classmethod
    async def start(cls, *args, **kwargs):
        return cls()

    async def wait(self):
        await self.event.wait()
        return 0

    def stop(self):
        self.event.set()

    async def close(self):
        self.closed = True
        self.event.set()


@pytest_asyncio.fixture
async def kernel(tmp_path, monkeypatch):
    import toolbox_backend.services.ai_sessions as module

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(FAKE.parent) + ":/usr/bin:/bin")
    monkeypatch.setattr(module, "SupervisedProcess", FakeProcess)
    FakeProcess.owners = []
    app = create_app(
        Settings(
            token="s5a-local-test-token",
            port=12345,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
    )
    async with app.router.lifespan_context(app):
        repo = tmp_path / "repo"
        repo.mkdir()

        def configure(c):
            c.ado.local_repos.append(LocalRepo(id="repo", name="repo", path=str(repo)))
            c.ai.profiles[0].command = shlex.join([sys.executable, str(FAKE), "--echo"])
            c.ai.profiles[0].upgrade_command = shlex.join([sys.executable, str(FAKE), "--version"])

        await app.state.config_store.update(0, configure)
        app.state.ai_service.path_extras = []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:12345",
            headers={"Authorization": "Bearer s5a-local-test-token"},
        ) as client:
            yield app, client, repo
    assert all(p.closed for p in FakeProcess.owners)


def payload(**kw):
    return dict(request_id=str(uuid4()), kind="terminal", profile_id="codex", repo_id="repo", **kw)


@pytest.mark.asyncio
async def test_create_idempotent_close_and_events(kernel):
    app, client, _ = kernel
    body = payload()
    first = await client.post("/api/ai/sessions", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "idle"
    second = await client.post("/api/ai/sessions", json=body)
    assert first.json()["id"] == second.json()["id"]
    assert len(FakeProcess.owners) == 1
    sid = first.json()["id"]
    closed = await client.post(f"/api/ai/sessions/{sid}/close")
    assert closed.json()["state"] == "ended"
    assert closed.json()["ended_reason"] == "user_closed"
    assert (await client.post(f"/api/ai/sessions/{sid}/close")).json() == closed.json()
    events = (await client.get(f"/api/ai/sessions/{sid}/events")).json()
    assert [e["session_seq"] for e in events["items"]] == list(range(1, events["last_seq"] + 1))
    assert (await client.delete(f"/api/ai/sessions/{sid}")).status_code == 204


@pytest.mark.asyncio
async def test_session_limits_and_parallel_shutdown(kernel):
    app, client, _ = kernel
    for _ in range(4):
        response = await client.post("/api/ai/sessions", json=payload())
        assert response.status_code == 200, response.text
    limit = await client.post("/api/ai/sessions", json=payload())
    assert limit.status_code == 409 and limit.json()["detail"]["code"] == "ai_session_limit"
    started = time.monotonic()
    await app.state.ai_service.close()
    assert time.monotonic() - started < 5
    assert not app.state.ai_service._active


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model", ["; rm", "$(echo bad)", "`bad`", "safe\nunsafe", "--dangerously-all"]
)
async def test_model_injection_not_echoed(kernel, model):
    _, client, _ = kernel
    response = await client.post("/api/ai/sessions", json=payload(model=model))
    assert response.status_code == 422
    assert model not in response.text
    assert not FakeProcess.owners


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "symlink", "unknown"])
async def test_repository_boundary(kernel, tmp_path, change):
    _, client, repo = kernel
    if change == "deleted":
        repo.rmdir()
    elif change == "symlink":
        repo.rmdir()
        other = tmp_path / "other"
        other.mkdir()
        repo.symlink_to(other, target_is_directory=True)
    body = payload()
    if change == "unknown":
        body["repo_id"] = "not-registered"
    response = await client.post("/api/ai/sessions", json=body)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "repo_missing"
    assert not FakeProcess.owners


@pytest.mark.asyncio
async def test_chat_is_placeholder_and_high_risk_ack(kernel):
    _, client, _ = kernel
    # S5-B: structured chat is implemented for claude/codex/agy; only "other" keeps the 409.
    revision = (await client.get("/api/ai")).json()["revision"]
    created = await client.post(
        "/api/ai/profiles",
        json=dict(revision=revision, name="other", command=shlex.join([sys.executable, str(FAKE)])),
    )
    body = payload()
    body.update(kind="chat", profile_id=created.json()["id"])
    response = await client.post("/api/ai/sessions", json=body)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "unsupported_cli"
    response = await client.post("/api/ai/sessions", json=payload(permission="danger-full-access"))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "high_risk_ack_required"
    response = await client.post("/api/ai/sessions", json=payload(effort="ultra"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_builtin_profile_and_safe_settings(kernel):
    _, client, _ = kernel
    view = await client.get("/api/ai")
    assert view.status_code == 200, view.text
    assert view.json()["profiles"][0]["resolved"]["path_hint"] == PYTHON_NAME
    revision = view.json()["revision"]
    response = await client.delete("/api/ai/profiles/codex", params={"revision": revision})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "builtin_profile"
    response = await client.post(
        "/api/ai/profiles", json=dict(revision=revision, name="custom", command='"unterminated')
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_terminal_ring_replay_resize_and_input_limits():
    terminal = PTYTerminal()
    try:
        os.write(terminal.slave, b"first\n")
        await asyncio.sleep(0.01)
        start, first = terminal.replay(0)
        assert start == 0 and first == b"first\r\n"
        os.write(terminal.slave, b"second\n")
        await asyncio.sleep(0.01)
        start, second = terminal.replay(len(first))
        assert start == len(first) and second == b"second\r\n"
        assert terminal.replay(0)[1] == first + second
        with pytest.raises(ValueError):
            terminal.resize(4, 100)
        with pytest.raises(ValueError):
            await terminal.input("%%%")
        with pytest.raises(ValueError):
            await terminal.input(base64.b64encode(b"a" * 16385).decode())
    finally:
        terminal.close()
    assert terminal.replay(0)[1] == first + second


@pytest.mark.asyncio
async def test_ai_store_permissions_and_corrupt_isolation(tmp_path):
    data = tmp_path / "data"
    store = AIStore(data)
    await store.initialize()
    assert store.readonly_error is None
    assert stat.S_IMODE(data.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    await store.close()
    store.path.write_bytes(b"corrupt")
    broken = AIStore(data)
    await broken.initialize()
    try:
        assert broken.readonly_error
        with pytest.raises(SettingsError, match="AI 数据库"):
            await broken.list()
        assert store.path.read_bytes() == b"corrupt"
    finally:
        await broken.close()


@pytest.mark.asyncio
async def test_restart_scan_does_not_kill_reused_pid(kernel, monkeypatch):
    app, client, _ = kernel
    created = (await client.post("/api/ai/sessions", json=payload())).json()
    sid = created["id"]
    await app.state.ai_service.command(sid, "close")
    await app.state.ai_store.close()
    path = app.state.settings.data_dir / "ai.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE ai_sessions SET state='busy',ended_at=NULL WHERE id=?", (sid,))
        db.execute("UPDATE ai_processes SET ended_at=NULL")
    import toolbox_backend.adapters.ai_store as module

    monkeypatch.setattr(
        module, "process_identity", lambda _: dict(proc_start_time="REUSED", executable="/fake")
    )
    killed = []
    monkeypatch.setattr(module.os, "killpg", lambda *args: killed.append(args))
    recovered = AIStore(path.parent)
    await recovered.initialize()
    try:
        assert killed == []
        assert (await recovered.get(sid))["ended_reason"] == "backend_restart"
    finally:
        await recovered.close()


@pytest.mark.parametrize(
    "dev,memory,flag", [(False, True, "1"), (True, False, "1"), (True, True, "0")]
)
def test_fake_ai_three_gates(tmp_path, monkeypatch, dev, memory, flag):
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_AI", flag)
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory" if memory else "keyring")
    with pytest.raises(ValueError, match="requires"):
        create_app(
            Settings(
                token="fake-ai-gate-token",
                port=1,
                dev=dev,
                data_dir=tmp_path / "data",
                legacy_config_dir=tmp_path / "legacy",
            ),
            credentials=MemoryCredentials(),
        )


def test_fake_ai_uses_only_repo_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_AI", "1")
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    app = create_app(
        Settings(
            token="fake-ai-gate-token",
            port=1,
            dev=True,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
    )
    from toolbox_backend.domain.settings import Config

    profile = app.state.ai_service._profile(Config().ai, "codex")
    assert str(FAKE.resolve()) in profile.command
    assert "codex" not in shlex.split(profile.command)[0]


@pytest.mark.asyncio
async def test_ai_topic_registers_before_replay_and_buffers_commits(kernel):
    from toolbox_backend.api.ws import _subscribe_ai

    app, client, _ = kernel
    row = (await client.post("/api/ai/sessions", json=payload())).json()
    sid = row["id"]
    sub = app.state.hub.subscribe()

    class Socket:
        pass

    ws = Socket()
    ws.app = app
    try:
        await _subscribe_ai(ws, sub, {"session_id": sid, "after_seq": 0})
        frames = []
        while not sub.queue.empty():
            frames.append(__import__("json").loads(sub.queue.get_nowait()))
        events = [f["data"]["session_seq"] for f in frames if f["type"] == "ai.event"]
        assert events == list(range(1, row["last_seq"] + 1))
        assert frames[-1]["type"] == "ai.subscribed"
        await app.state.ai_service.command(sid, "close")
        frames = []
        while not sub.queue.empty():
            frames.append(__import__("json").loads(sub.queue.get_nowait()))
        events += [f["data"]["session_seq"] for f in frames if f["type"] == "ai.event"]
        assert events == sorted(set(events))
    finally:
        app.state.hub.unsubscribe(sub)


@pytest.mark.asyncio
async def test_terminal_ring_bound_rate_and_ended_replay():
    terminal = PTYTerminal()
    try:
        # Replace write with a consumer to test limits without filling the kernel PTY.
        written = []

        async def consume(data):
            written.append(data)

        terminal.write = consume
        chunk = base64.b64encode(b"a" * 16384).decode()
        for _ in range(16):
            await terminal.input(chunk)
        with pytest.raises(ValueError, match="rate"):
            await terminal.input(chunk)
        terminal.buffer = bytearray(b"a" * (terminal.capacity + 10))
        terminal.offset = len(terminal.buffer)
        # A new read trims oversized retained data to the fixed capacity.
        os.write(terminal.slave, b"z")
        await asyncio.sleep(0.01)
        assert len(terminal.buffer) == terminal.capacity
        assert terminal.replay(0)[0] == 11
    finally:
        terminal.close()
    assert terminal.replay(terminal.offset - 1)[1] == b"z"


class TerminalSocket:
    def __init__(self, app, frames, *, token="s5a-local-test-token", origin="tauri://localhost"):
        self.app = app
        self.headers = {"origin": origin}
        self.frames = asyncio.Queue()
        for frame in frames:
            self.frames.put_nowait(__import__("json").dumps(frame))
        self.token = token
        self.sent = []
        self.codes = []
        self.on_send = None

    async def accept(self):
        pass

    async def receive(self):
        return {
            "type": "websocket.receive",
            "text": __import__("json").dumps({"type": "auth", "token": self.token}),
        }

    async def receive_text(self):
        return await self.frames.get()

    async def send_bytes(self, data):
        self.sent.append(data)
        if self.on_send:
            self.on_send()
            self.on_send = None

    async def close(self, code):
        self.codes.append(code)


@pytest.mark.asyncio
async def test_terminal_ws_replay_live_handoff_ended_and_connection_cap(kernel):
    import struct

    from toolbox_backend.api.ai_routes import terminal_socket

    app, client, _ = kernel
    sid = (await client.post("/api/ai/sessions", json=payload())).json()["id"]
    await app.state.ai_service.command(sid, "close")
    terminal = app.state.ai_service.terminals[sid]
    terminal.buffer, terminal.offset = bytearray(b"first"), 5
    ws = TerminalSocket(app, [{"type": "attach", "after_offset": 0}])

    def concurrent_output():
        terminal.buffer.extend(b"second")
        terminal.offset += 6
        terminal.changed.set()

    ws.on_send = concurrent_output
    await terminal_socket(sid, ws)
    assert [(struct.unpack(">Q", data[:8])[0], data[8:]) for data in ws.sent] == [
        (0, b"first"),
        (5, b"second"),
    ]
    reconnect = TerminalSocket(app, [{"type": "attach", "after_offset": 5}])
    await terminal_socket(sid, reconnect)
    assert reconnect.sent == [struct.pack(">Q", 5) + b"second"]
    assert terminal.connections == 0
    terminal.connections = 2
    rejected = TerminalSocket(app, [])
    await terminal_socket(sid, rejected)
    assert 1008 in rejected.codes and terminal.connections == 2
    terminal.connections = 0


@pytest.mark.asyncio
async def test_terminal_ws_auth_origin_and_resize_rejected(kernel):
    from toolbox_backend.api.ai_routes import terminal_socket

    app, client, _ = kernel
    sid = (await client.post("/api/ai/sessions", json=payload())).json()["id"]
    bad_auth = TerminalSocket(app, [], token="invalid")
    await terminal_socket(sid, bad_auth)
    assert 4401 in bad_auth.codes
    bad_origin = TerminalSocket(app, [], origin="https://evil.invalid")
    await terminal_socket(sid, bad_origin)
    assert bad_origin.codes == [1008]
    invalid_resize = TerminalSocket(
        app, [{"type": "attach", "after_offset": 0}, {"type": "resize", "rows": 1, "cols": 1}]
    )
    await terminal_socket(sid, invalid_resize)
    assert 1008 in invalid_resize.codes


@pytest.mark.asyncio
async def test_upgrade_shares_per_cli_process_limit(kernel):
    _, client, _ = kernel
    for _ in range(4):
        assert (await client.post("/api/ai/sessions", json=payload())).status_code == 200
    response = await client.post("/api/ai/profiles/codex/upgrade")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "ai_session_limit"


@pytest.mark.asyncio
async def test_check_records_process_and_bounds_redacted_output(kernel, monkeypatch):
    app, client, _ = kernel
    from toolbox_backend.logging_setup import register_secret

    secret = "s5a-fake-output-private-value"
    register_secret(secret)

    async def start(*args, **kwargs):
        owner = FakeProcess()
        owner.stdout.feed_data((secret * 1000).encode())
        owner.stdout.feed_eof()
        owner.event.set()
        return owner

    monkeypatch.setattr(FakeProcess, "start", start)
    response = await client.post("/api/ai/profiles/codex/check")
    assert response.status_code == 200 and response.json()["ok"]
    assert secret not in response.text and len(response.json()["output"].encode()) <= 4096
    rows = await app.state.ai_store.call(
        lambda: list(
            app.state.ai_store.require().execute(
                "SELECT role,ended_at FROM ai_processes WHERE role='check'"
            )
        )
    )
    assert len(rows) == 1 and rows[0]["ended_at"] is not None


@pytest.mark.asyncio
async def test_upgrade_cancel_before_worker_starts_releases_slot(kernel):
    app, _, _ = kernel
    service = app.state.ai_service
    job = await service.upgrade("codex")
    try:
        await service.cancel_job(job["job_id"])
    except asyncio.CancelledError:
        pytest.fail("job cancellation escaped to caller")
    assert not service._aux
    assert service._jobs[job["job_id"]]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_kill_failed_is_visible_and_pending_approvals_expire(kernel, monkeypatch):
    app, client, _ = kernel
    sid = (await client.post("/api/ai/sessions", json=payload())).json()["id"]
    owner = FakeProcess.owners[-1]

    async def unconfirmed_close():
        owner.closed = True
        owner.event.set()
        raise TimeoutError

    monkeypatch.setattr(owner, "close", unconfirmed_close)
    await app.state.ai_store.call(
        lambda: app.state.ai_store.require().execute(
            "INSERT INTO ai_approvals(id,session_id,state) VALUES('approval',?,'pending')", (sid,)
        )
    )
    result = await app.state.ai_service.command(sid, "close")
    assert "kill_failed" in result.warnings
    state = await app.state.ai_store.call(
        lambda: (
            app.state.ai_store.require()
            .execute("SELECT state FROM ai_approvals WHERE id='approval'")
            .fetchone()[0]
        )
    )
    assert state == "expired"


@pytest.mark.asyncio
async def test_close_does_not_wait_for_blocked_initial_prompt_writer(kernel, monkeypatch):
    app, client, _ = kernel
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_write(self, data):
        entered.set()
        await release.wait()

    monkeypatch.setattr(PTYTerminal, "write", blocked_write)
    sid = (await client.post("/api/ai/sessions", json=payload(initial_prompt="hello"))).json()["id"]
    await asyncio.wait_for(entered.wait(), 1)
    try:
        result = await asyncio.wait_for(app.state.ai_service.command(sid, "close"), 0.5)
        assert result.state == "ended"
    finally:
        release.set()
        active = app.state.ai_service._active.get(sid)
        if active:
            await asyncio.wait_for(active["task"], 1)
