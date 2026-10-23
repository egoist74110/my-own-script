# ruff: noqa: F811
"""S5-B: Claude headless flow, queueing, interruption, faults and restart/resume."""

import asyncio
import os
from uuid import uuid4

import pytest

from tests.s5b_helpers import (
    chat,  # noqa: F401  (fixture)
    client_for,
    configure,
    events,
    make_app,
    new_body,
    records,
    say,
    session_state,
    use_fakes,
    wait_event,
    wait_for,
)
from toolbox_backend.adapters.ai_store import AIStore
from toolbox_backend.logging_setup import register_secret


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.mark.asyncio
async def test_claude_two_turns_interrupt_close_restart_resume(tmp_path, monkeypatch):
    log = use_fakes(monkeypatch, tmp_path)
    app = make_app(tmp_path)
    async with app.router.lifespan_context(app):
        await configure(app, tmp_path)
        async with client_for(app) as client:
            created = (await client.post("/api/ai/sessions", json=new_body())).json()
            sid = created["id"]
            assert created["state"] == "idle" and created["has_external_id"]
            assert (await say(client, sid, "one TOOL")) == {"status": "sent", "position": 0}
            await wait_event(client, sid, "turn_completed", 1)
            assert (await say(client, sid, "two"))["status"] == "sent"
            await wait_event(client, sid, "turn_completed", 2)
            kinds = [e["kind"] for e in await events(client, sid)]
            for kind in ("init", "thinking", "assistant", "tool_use", "tool_result", "turn_started"):
                assert kind in kinds
            seqs = [e["session_seq"] for e in await events(client, sid)]
            assert seqs == sorted(set(seqs))
            view = (await client.get(f"/api/ai/sessions/{sid}")).json()
            assert view["usage"]["turns"] == 2 and view["usage"]["input_tokens"] == 20
            # interrupt a running turn: exactly one terminal event, session usable afterwards
            await say(client, sid, "three SLOW")
            await session_state(client, sid, "busy")
            await asyncio.sleep(0.3)
            assert (await client.post(f"/api/ai/sessions/{sid}/interrupt")).status_code == 200
            interrupted = await wait_event(client, sid, "turn_failed", 1, status="interrupted")
            assert len(interrupted) == 1
            await session_state(client, sid, "idle")
            await say(client, sid, "four")
            await wait_event(client, sid, "turn_completed", 3)
            closed = (await client.post(f"/api/ai/sessions/{sid}/close")).json()
            assert closed["state"] == "ended" and closed["ended_reason"] == "user_closed"
            terminals = [
                e for e in await events(client, sid) if e["kind"] in ("turn_completed", "turn_failed")
            ]
            assert len({e["payload"]["turn"] for e in terminals}) == len(terminals) == 4
            external = log.read_text()
            assert "--session-id" in external
    # restart the backend on the same data dir and resume
    app2 = make_app(tmp_path)
    async with app2.router.lifespan_context(app2):
        await configure(app2, tmp_path)
        async with client_for(app2) as client:
            body = dict(request_id=str(uuid4()))
            resumed = await client.post(f"/api/ai/sessions/{sid}/resume", json=body)
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["id"] != sid
            assert (await client.post(f"/api/ai/sessions/{sid}/resume", json=body)).json()["id"] == resumed.json()["id"]
            await say(client, resumed.json()["id"], "five")
            await wait_event(client, resumed.json()["id"], "turn_completed")
            launches = [r for r in records(log) if r.get("cli") == "claude"]
            first, second = launches[0]["argv"], launches[-1]["argv"]
            token = first[first.index("--session-id") + 1]
            assert second[second.index("--resume") + 1] == token and "--session-id" not in second
            await client.post(f"/api/ai/sessions/{resumed.json()['id']}/close")


@pytest.mark.asyncio
async def test_queue_limit_dedupe_and_after_end(chat):
    app, client, _, log = chat
    sid = (await client.post("/api/ai/sessions", json=new_body())).json()["id"]
    first = dict(request_id=str(uuid4()), text="first SLOW")
    assert (await client.post(f"/api/ai/sessions/{sid}/messages", json=first)).json()["status"] == "sent"
    assert (await client.post(f"/api/ai/sessions/{sid}/messages", json=first)).json()["status"] == "sent"
    positions = []
    for index in range(10):
        r = await client.post(
            f"/api/ai/sessions/{sid}/messages", json=dict(request_id=str(uuid4()), text=f"q{index}")
        )
        assert r.json()["status"] == "queued"
        positions.append(r.json()["position"])
    assert positions == list(range(1, 11))
    view = (await client.get(f"/api/ai/sessions/{sid}")).json()
    assert view["queue_len"] == 10
    full = await client.post(
        f"/api/ai/sessions/{sid}/messages", json=dict(request_id=str(uuid4()), text="x")
    )
    assert full.status_code == 409 and full.json()["detail"]["code"] == "ai_queue_full"
    big = await client.post(
        f"/api/ai/sessions/{sid}/messages", json=dict(request_id=str(uuid4()), text="x" * 32769)
    )
    assert big.status_code == 422
    await asyncio.sleep(0.6)  # let the fake enter its turn so the interrupt is observed
    await client.post(f"/api/ai/sessions/{sid}/interrupt")
    await session_state(client, sid, "idle")
    assert (await client.get(f"/api/ai/sessions/{sid}")).json()["queue_len"] == 0
    await client.post(f"/api/ai/sessions/{sid}/close")
    late = await client.post(
        f"/api/ai/sessions/{sid}/messages", json=dict(request_id=str(uuid4()), text="late")
    )
    assert late.status_code == 409 and late.json()["detail"]["code"] == "session_ended"
    assert len(set(r["prompt_received"] for r in records(log) if "prompt_received" in r)) == 1


@pytest.mark.asyncio
async def test_bad_json_long_line_and_stderr_flood(chat):
    app, client, _, _ = chat
    sid = (await client.post("/api/ai/sessions", json=new_body())).json()["id"]
    await say(client, sid, "BADJSON LONGLINE FLOODERR go")
    await wait_event(client, sid, "turn_completed")
    items = await events(client, sid)
    errors = [e["payload"] for e in items if e["kind"] == "error"]
    assert any(e.get("category") == "bad_json" for e in errors)
    assert any(e.get("category") == "line_too_long" for e in errors)
    stderr = [e for e in errors if e.get("category") == "stderr"]
    assert 0 < len(stderr) <= 40  # 3000 lines are rate limited and merged
    await wait_event(client, sid, "notice", reason="suppressed")
    # the reader was never blocked: the next turn still works
    await say(client, sid, "after")
    await wait_event(client, sid, "turn_completed", 2)
    await client.post(f"/api/ai/sessions/{sid}/close")


@pytest.mark.asyncio
async def test_claude_crash_ends_session_with_turn_failed(chat):
    app, client, _, _ = chat
    sid = (await client.post("/api/ai/sessions", json=new_body())).json()["id"]
    await say(client, sid, "CRASH now")
    view = await session_state(client, sid, "ended")
    assert view["ended_reason"] == "process_exited" and view["exit_code"] == 3
    items = await events(client, sid)
    failed = [e for e in items if e["kind"] == "turn_failed"]
    assert len(failed) == 1 and failed[0]["payload"]["category"] == "process_exited"
    assert any("simulated crash" in str(e["payload"]) for e in items if e["kind"] == "error")


@pytest.mark.asyncio
async def test_start_failure_and_cli_not_found(chat, monkeypatch):
    app, client, _, _ = chat
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    r = await client.post("/api/ai/sessions", json=new_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cli_not_found"
    r = await client.post("/api/ai/sessions", json=new_body(profile="nope"))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_no_secret_leaks_and_env_filtered(chat, monkeypatch, tmp_path):
    app, client, _, log = chat
    secret = "sk-test-secret-value-0123456789"
    monkeypatch.setenv("FAKE_API_KEY", secret)
    register_secret(secret)
    sid = (await client.post("/api/ai/sessions", json=new_body())).json()["id"]
    await say(client, sid, f"SECRET please {secret}")
    await wait_event(client, sid, "turn_completed")
    await client.post(f"/api/ai/sessions/{sid}/close")
    env = [r for r in records(log) if r.get("cli") == "claude"][0]["env"]
    assert "FAKE_API_KEY" not in env
    blob = repr(await events(client, sid))
    for path in (app.state.ai_store.path, *(tmp_path / "data").glob("ai.sqlite3-*")):
        blob += path.read_bytes().decode("latin1")
    assert secret not in blob
    assert "***" in repr(await events(client, sid))


@pytest.mark.asyncio
async def test_idle_timeout_and_no_leftover_processes(chat):
    app, client, _, log = chat
    app.state.ai_service.claude_idle_s = 0.3
    sid = (await client.post("/api/ai/sessions", json=new_body())).json()["id"]
    await say(client, sid, "GRANDCHILD hi")
    await wait_event(client, sid, "turn_completed")
    view = await session_state(client, sid, "ended")
    assert view["ended_reason"] == "limit"
    pids = [r["pid"] for r in records(log) if "pid" in r] + [
        r["grandchild"] for r in records(log) if "grandchild" in r
    ]
    await wait_for(lambda: asyncio.sleep(0, result=not any(alive(p) for p in pids)))


@pytest.mark.asyncio
async def test_shutdown_ends_chat_sessions_quickly(chat):
    app, client, _, _ = chat
    sids = [(await client.post("/api/ai/sessions", json=new_body())).json()["id"] for _ in range(3)]
    await say(client, sids[0], "busy SLOW")
    await asyncio.sleep(0.3)
    import time

    started = time.monotonic()
    await app.state.ai_service.close()
    assert time.monotonic() - started < 5
    reopened = AIStore(app.state.settings.data_dir)
    await reopened.initialize()
    for sid in sids:
        row = await reopened.get(sid)
        assert row["state"] == "ended" and row["ended_reason"] == "interrupted_on_exit"
        assert row["external_id"]  # kept for the next resume
    await reopened.close()
