# ruff: noqa: F811
"""S5-B: per-turn Codex / agy processes, stdin prompts, resume and timeouts."""

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


def launches(log, cli):
    return [r for r in records(log) if r.get("cli") == cli]


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


async def create(client, profile, **extra):
    r = await client.post("/api/ai/sessions", json=new_body(profile, **extra))
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_codex_flow_stdin_prompt_resume_and_sandbox(tmp_path, monkeypatch):
    log = use_fakes(monkeypatch, tmp_path)
    app = make_app(tmp_path)
    prompt = "first; rm -rf $(id) `x` --dangerously-bypass-approvals-and-sandbox TOOL"
    async with app.router.lifespan_context(app):
        repo = await configure(app, tmp_path)
        async with client_for(app) as client:
            sid = await create(client, "codex", permission="read-only", model="gpt-x", effort="low")
            assert (await client.get(f"/api/ai/sessions/{sid}")).json()["has_external_id"] is False
            assert (await say(client, sid, prompt))["status"] == "sent"
            await wait_event(client, sid, "turn_completed", 1)
            await say(client, sid, "second")
            await wait_event(client, sid, "turn_completed", 2)
            first, second = launches(log, "codex")
            cwd = str(repo.resolve())
            assert first["argv"] == [
                "exec", "--json", "--skip-git-repo-check", "-C", cwd, "-m", "gpt-x",
                "-c", "model_reasoning_effort=low", "-s", "read-only", "-",
            ]  # fmt: skip
            assert not first["prompt_in_argv"] and first["stdin_prompt"].startswith("first;")
            thread = (await client.get(f"/api/ai/sessions/{sid}/events")).json()["items"]
            thread = [e for e in thread if e["kind"] == "init"][0]["payload"]["external_id"]
            assert second["argv"][:4] == ["exec", "resume", thread, "--json"]
            assert "-s" not in second["argv"] and "-C" not in second["argv"]
            assert "--full-auto" not in first["argv"] + second["argv"]
            assert second["argv"][-1] == "-" and not second["prompt_in_argv"]
            kinds = [e["kind"] for e in await events(client, sid)]
            assert "tool_use" in kinds and "tool_result" in kinds and "assistant" in kinds
            view = (await client.get(f"/api/ai/sessions/{sid}")).json()
            assert view["has_external_id"] and view["usage"]["turns"] == 2
            await client.post(f"/api/ai/sessions/{sid}/close")
            # no per-turn process survives
            await wait_for(
                lambda: asyncio.sleep(0, result=not any(alive(r["pid"]) for r in launches(log, "codex")))
            )
    app2 = make_app(tmp_path)
    async with app2.router.lifespan_context(app2):
        await configure(app2, tmp_path)
        async with client_for(app2) as client:
            resumed = (
                await client.post(f"/api/ai/sessions/{sid}/resume", json=dict(request_id=str(uuid4())))
            ).json()
            assert resumed["permission"] == "read-only"  # sandbox fixed by the first turn
            await say(client, resumed["id"], "third")
            await wait_event(client, resumed["id"], "turn_completed")
            last = launches(log, "codex")[-1]["argv"]
            assert last[:3] == ["exec", "resume", thread]
            assert "-s" not in last and "--dangerously-bypass-approvals-and-sandbox" not in last
            await client.post(f"/api/ai/sessions/{resumed['id']}/close")


@pytest.mark.asyncio
async def test_codex_danger_needs_ack_and_resume_keeps_bypass(chat):
    app, client, _, log = chat
    r = await client.post("/api/ai/sessions", json=new_body("codex", permission="danger-full-access"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "high_risk_ack_required"
    sid = await create(client, "codex", permission="danger-full-access", ack_high_risk=True)
    await say(client, sid, "a")
    await wait_event(client, sid, "turn_completed", 1)
    await say(client, sid, "b")
    await wait_event(client, sid, "turn_completed", 2)
    first, second = launches(log, "codex")
    assert "--dangerously-bypass-approvals-and-sandbox" in first["argv"] and "-s" not in first["argv"]
    assert "--dangerously-bypass-approvals-and-sandbox" in second["argv"]
    await client.post(f"/api/ai/sessions/{sid}/close")
    again = await client.post(f"/api/ai/sessions/{sid}/resume", json=dict(request_id=str(uuid4())))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "high_risk_ack_required"
    ok = await client.post(
        f"/api/ai/sessions/{sid}/resume", json=dict(request_id=str(uuid4()), ack_high_risk=True)
    )
    assert ok.status_code == 200
    await client.post(f"/api/ai/sessions/{ok.json()['id']}/close")


@pytest.mark.asyncio
async def test_codex_failures_timeout_interrupt_and_crash(chat):
    app, client, _, log = chat
    sid = await create(client, "codex")
    await say(client, sid, "FAIL now")
    failed = await wait_event(client, sid, "turn_failed", 1)
    assert failed[0]["payload"]["category"] == "cli_error"
    await say(client, sid, "CRASH now")
    crashed = await wait_event(client, sid, "turn_failed", 2)
    assert crashed[1]["payload"]["category"] == "exit" and crashed[1]["payload"]["exit_code"] == 3
    assert (await client.get(f"/api/ai/sessions/{sid}")).json()["state"] == "idle"  # still usable
    app.state.ai_service.codex_turn_s = 0.8
    await say(client, sid, "SLOW timeout")
    timed = await wait_event(client, sid, "turn_failed", 3)
    assert timed[2]["payload"]["category"] == "timeout"
    app.state.ai_service.codex_turn_s = 60
    await say(client, sid, "SLOW again")
    await session_state(client, sid, "busy")
    await asyncio.sleep(0.5)
    await say(client, sid, "queued behind")
    await client.post(f"/api/ai/sessions/{sid}/interrupt")
    done = await wait_event(client, sid, "turn_failed", 4)
    assert done[3]["payload"]["status"] == "interrupted"
    view = await session_state(client, sid, "idle")
    assert view["queue_len"] == 0
    terminals = [e for e in await events(client, sid) if e["kind"] in ("turn_completed", "turn_failed")]
    assert len({e["payload"]["turn"] for e in terminals}) == len(terminals) == 4
    await client.post(f"/api/ai/sessions/{sid}/close")
    await wait_for(
        lambda: asyncio.sleep(0, result=not any(alive(r["pid"]) for r in launches(log, "codex")))
    )


@pytest.mark.asyncio
async def test_codex_queue_runs_in_order_and_ended_rejects(chat):
    app, client, _, log = chat
    sid = await create(client, "codex")
    await say(client, sid, "one")
    results = [await say(client, sid, f"later{i}") for i in range(3)]
    assert [r["status"] for r in results] == ["queued"] * 3
    await wait_event(client, sid, "turn_completed", 4)
    prompts = [r["stdin_prompt"] for r in launches(log, "codex")]
    assert prompts == ["one", "later0", "later1", "later2"]
    await client.post(f"/api/ai/sessions/{sid}/close")
    late = await client.post(f"/api/ai/sessions/{sid}/messages", json=dict(request_id=str(uuid4()), text="x"))
    assert late.status_code == 409 and late.json()["detail"]["code"] == "session_ended"


@pytest.mark.asyncio
async def test_agy_stdin_prompt_conversation_and_no_cross_talk(chat):
    app, client, repo, log = chat
    one = await create(client, "gemini")
    two = await create(client, "gemini")  # same cwd: no mutual exclusion, ids never mixed
    await asyncio.gather(say(client, one, "alpha TOOL"), say(client, two, "beta"))
    await wait_event(client, one, "turn_completed")
    await wait_event(client, two, "turn_completed")
    await say(client, one, "again")
    await wait_event(client, one, "turn_completed", 2)
    first_run = [r for r in launches(log, "agy") if "--conversation" not in r["argv"]]
    assert len(first_run) == 2
    for record in launches(log, "agy"):
        argv = record["argv"]
        assert argv[:5] == ["--print", "--input-format", "stream-json", "--output-format", "stream-json"]
        assert "--print-timeout=600s" in argv and "--sandbox" in argv
        assert not any(a.startswith("--print=") for a in argv)
        assert "--dangerously-skip-permissions" not in argv
    ids = {
        s: [e for e in await events(client, s) if e["kind"] == "init"][0]["payload"]["external_id"]
        for s in (one, two)
    }
    assert ids[one] != ids[two]
    resumed_runs = [r["argv"] for r in launches(log, "agy") if "--conversation" in r["argv"]]
    assert len(resumed_runs) == 1 and resumed_runs[0][resumed_runs[0].index("--conversation") + 1] == ids[one]
    kinds = [e["kind"] for e in await events(client, one)]
    assert "tool_use" in kinds and "tool_result" in kinds and "assistant" in kinds
    assert (await client.get(f"/api/ai/sessions/{one}")).json()["warnings"] == []
    for sid in (one, two):
        await client.post(f"/api/ai/sessions/{sid}/close")


@pytest.mark.asyncio
async def test_agy_modes_effort_and_high_risk(chat):
    app, client, _, log = chat
    plan = await create(client, "gemini", permission="plan", effort="high", model="m1")
    await say(client, plan, "p")
    await wait_event(client, plan, "turn_completed")
    argv = launches(log, "agy")[-1]["argv"]
    assert "--sandbox" in argv and argv[argv.index("--mode") + 1] == "plan"
    assert argv[argv.index("--effort") + 1] == "high" and argv[argv.index("--model") + 1] == "m1"
    r = await client.post("/api/ai/sessions", json=new_body("gemini", permission="auto"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "high_risk_ack_required"
    auto = await create(client, "gemini", permission="auto", ack_high_risk=True)
    await say(client, auto, "p")
    await wait_event(client, auto, "turn_completed")
    argv = launches(log, "agy")[-1]["argv"]
    assert "--dangerously-skip-permissions" in argv and "--sandbox" not in argv
    bad = await client.post("/api/ai/sessions", json=new_body("gemini", model="--dangerously-skip-permissions"))
    assert bad.status_code == 422
    for sid in (plan, auto):
        await client.post(f"/api/ai/sessions/{sid}/close")


@pytest.mark.asyncio
async def test_agy_print_timeout_is_a_failure_not_success(chat):
    app, client, _, _ = chat
    sid = await create(client, "gemini")
    await say(client, sid, "TIMEOUT please")
    failed = await wait_event(client, sid, "turn_failed", 1)
    assert failed[0]["payload"]["category"] == "timeout"
    assert not [e for e in await events(client, sid) if e["kind"] == "turn_completed"]
    # watchdog: a hung process is killed after print-timeout + grace
    app.state.ai_service.agy_print_timeout_s = 1
    app.state.ai_service.agy_watchdog_extra_s = 0.5
    await say(client, sid, "SLOW hang")
    hung = await wait_event(client, sid, "turn_failed", 2)
    assert hung[1]["payload"]["category"] == "timeout"
    await client.post(f"/api/ai/sessions/{sid}/close")


@pytest.mark.asyncio
async def test_agy_falls_back_to_argv_when_stdin_input_unsupported(chat, monkeypatch):
    app, client, _, log = chat
    monkeypatch.setenv("FAKE_AGY_NO_STDIN", "1")
    sid = await create(client, "gemini")
    await say(client, sid, "hello fallback")
    await wait_event(client, sid, "turn_completed")
    view = (await client.get(f"/api/ai/sessions/{sid}")).json()
    assert "prompt_visible_to_other_processes" in view["warnings"]
    argv = launches(log, "agy")[-1]["argv"]
    assert "--print=hello fallback" in argv and "--input-format" not in argv
    await say(client, sid, "second")
    await wait_event(client, sid, "turn_completed", 2)
    assert "--print=second" in launches(log, "agy")[-1]["argv"]
    await client.post(f"/api/ai/sessions/{sid}/close")
