# ruff: noqa: F811
"""Independent S5-B requirement and fault cases (written separately from tests/test_s5b_*.py).

Everything runs against the real app with the offline fake CLIs (tests/fixtures/fake_cli).
No real claude/codex/agy is ever launched and no network is used.
"""

import asyncio
import json
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
)

MAX_TEXT = 32768


def dumped(items):
    return json.dumps(items, ensure_ascii=False)


def launches(log, cli):
    return [r for r in records(log) if r.get("cli") == cli]


async def create(client, profile="claude_code", **extra):
    response = await client.post("/api/ai/sessions", json=new_body(profile, **extra))
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def send_raw(client, sid, text, request_id=None):
    body = dict(request_id=request_id or str(uuid4()), text=text)
    return await client.post(f"/api/ai/sessions/{sid}/messages", json=body)


# ---------------------------------------------------------------------------
# 1) concurrency: several sessions must not share events or external ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_claude_and_one_codex_run_concurrently_without_crosstalk(tmp_path, monkeypatch):
    log = use_fakes(monkeypatch, tmp_path)
    app = make_app(tmp_path)
    async with app.router.lifespan_context(app):
        await configure(app, tmp_path)
        async with client_for(app) as client:
            claude = [await create(client, "claude_code") for _ in range(3)]
            codex = await create(client, "codex")
            sids = claude + [codex]
            markers = {sid: f"MRK{index}X{uuid4().hex[:10]}" for index, sid in enumerate(sids)}
            await asyncio.gather(*(say(client, sid, f"{markers[sid]} tail") for sid in sids))
            for sid in sids:
                await wait_event(client, sid, "turn_completed", 1)
            for sid in sids:
                evs = await events(client, sid)
                blob = dumped(evs)
                assert markers[sid] in blob, f"own marker missing for {sid}"
                for other in sids:
                    if other != sid:
                        assert markers[other] not in blob, f"{sid} saw the marker of {other}"
                assert all(e.get("session_id", sid) == sid for e in evs)
            # the three Claude processes were started with three distinct backend-chosen ids
            claude_ids = [r["argv"][r["argv"].index("--session-id") + 1] for r in launches(log, "claude")]
            assert len(claude_ids) == 3 and len(set(claude_ids)) == 3
            for sid in sids:
                view = (await client.get(f"/api/ai/sessions/{sid}")).json()
                assert view["has_external_id"] is True


# ---------------------------------------------------------------------------
# 2) duplicate request_id on session creation: one process only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_creates_with_same_request_id_start_one_process(tmp_path, monkeypatch):
    log = use_fakes(monkeypatch, tmp_path)
    app = make_app(tmp_path)
    async with app.router.lifespan_context(app):
        await configure(app, tmp_path)
        async with client_for(app) as client:
            body = new_body("claude_code")
            results = await asyncio.gather(*(client.post("/api/ai/sessions", json=body) for _ in range(5)))
            assert {r.status_code for r in results} == {200}, [r.text for r in results]
            assert len({r.json()["id"] for r in results}) == 1
            await asyncio.sleep(1.0)
            assert len(launches(log, "claude")) == 1
            listed = (await client.get("/api/ai/sessions")).json()["items"]
            assert len(listed) == 1


# ---------------------------------------------------------------------------
# 3) duplicate message request_id: no second turn, no second queue slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_message_request_id_while_queued_does_not_add_a_turn(chat):
    app, client, _, log = chat
    sid = await create(client, "claude_code")
    await say(client, sid, "HOLD SLOW")
    await session_state(client, sid, "busy")
    rid = str(uuid4())
    first = await send_raw(client, sid, "QUEUEDUPMARK", request_id=rid)
    assert first.status_code == 200 and first.json()["status"] == "queued"
    second = await send_raw(client, sid, "QUEUEDUPMARK", request_id=rid)
    assert second.status_code == 200, second.text
    assert (await client.get(f"/api/ai/sessions/{sid}")).json()["queue_len"] == 1
    await client.post(f"/api/ai/sessions/{sid}/interrupt")
    # by design an interrupt cancels everything queued behind the running turn (ai_chat._interrupt)
    await session_state(client, sid, "idle")
    await asyncio.sleep(0.5)
    received = [r for r in records(log) if "QUEUEDUPMARK" in r.get("prompt_received", "")]
    assert received == [], "a cancelled queued duplicate must never reach the process"
    assert (await client.get(f"/api/ai/sessions/{sid}")).json()["queue_len"] == 0
    await client.post(f"/api/ai/sessions/{sid}/close")


@pytest.mark.asyncio
async def test_duplicate_message_request_id_after_completion_is_not_replayed(chat):
    app, client, _, log = chat
    sid = await create(client, "claude_code")
    rid = str(uuid4())
    body = dict(request_id=rid, text="REPLAYMARK once")
    assert (await client.post(f"/api/ai/sessions/{sid}/messages", json=body)).status_code == 200
    await wait_event(client, sid, "turn_completed", 1)
    again = await client.post(f"/api/ai/sessions/{sid}/messages", json=body)
    assert again.status_code == 200, again.text
    await asyncio.sleep(1.0)
    turns = [e for e in await events(client, sid) if e["kind"] == "turn_started"]
    assert len(turns) == 1, "a replayed request_id must not start a second turn"
    received = [r for r in records(log) if "REPLAYMARK" in r.get("prompt_received", "")]
    assert len(received) == 1


# ---------------------------------------------------------------------------
# 4) body validation: blank / oversized text, malformed ids, extra fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blank_and_oversized_messages_are_422_and_never_start_a_turn(chat):
    app, client, _, log = chat
    sid = await create(client, "claude_code")
    for text in ["", "   ", "\n\t \r\n", "a" * 32769, "集" * 10923]:
        r = await send_raw(client, sid, text)
        assert r.status_code == 422, (text[:10], r.status_code)
    await asyncio.sleep(0.4)
    assert [e for e in await events(client, sid) if e["kind"] == "turn_started"] == []
    assert not any(r.get("prompt_received") for r in records(log))


@pytest.mark.asyncio
async def test_exactly_32kib_message_is_accepted(chat):
    app, client, _, log = chat
    sid = await create(client, "claude_code")
    text = "Q" * MAX_TEXT
    assert len(text.encode()) == MAX_TEXT
    r = await send_raw(client, sid, text)
    assert r.status_code == 200 and r.json()["status"] == "sent", r.text
    await wait_event(client, sid, "turn_completed", 1)


@pytest.mark.asyncio
async def test_utf8_byte_limit_is_enforced_not_character_limit(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    # 10923 CJK characters are 32769 UTF-8 bytes: must be refused although the char count is small.
    r = await send_raw(client, sid, "集" * 10923)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_malformed_ids_and_unknown_fields_are_422(chat):
    app, client, _, _ = chat
    bad_create = [
        dict(new_body(), request_id="not-a-uuid"),
        dict(new_body(), kind="shell"),
        dict(new_body(), unexpected="field"),
        dict(new_body(), resume={"external_id": "--dangerous", }),
        dict(new_body(), resume={"external_id": "abc", "session_id": "ais_" + "0" * 32}),
        dict(new_body(), resume={}),
    ]
    for body in bad_create:
        r = await client.post("/api/ai/sessions", json=body)
        assert r.status_code == 422, (body, r.status_code, r.text[:200])
    sid = await create(client, "claude_code")
    for body in (
        {"request_id": "123", "text": "x"},
        {"request_id": str(uuid4()), "text": "x", "extra": 1},
        {"request_id": str(uuid4())},
    ):
        r = await client.post(f"/api/ai/sessions/{sid}/messages", json=body)
        assert r.status_code == 422, (body, r.status_code)
    r = await client.get(f"/api/ai/sessions/{sid}/events", params={"limit": 0})
    assert r.status_code == 422
    r = await client.get(f"/api/ai/sessions/{sid}/events", params={"limit": 1001})
    assert r.status_code == 422
    aid = str(uuid4())
    r = await client.post(f"/api/ai/sessions/{sid}/approvals/{aid}", json={"decision": "maybe"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 5) ended sessions: approvals, interrupt and close are idempotent, never 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ended_session_commands_are_idempotent_and_never_500(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    await say(client, sid, "one")
    await wait_event(client, sid, "turn_completed", 1)
    first = (await client.post(f"/api/ai/sessions/{sid}/close")).json()
    assert first["state"] == "ended"
    for _ in range(2):
        closed = await client.post(f"/api/ai/sessions/{sid}/close")
        assert closed.status_code == 200 and closed.json()["state"] == "ended"
        interrupted = await client.post(f"/api/ai/sessions/{sid}/interrupt")
        assert interrupted.status_code == 200 and interrupted.json()["state"] == "ended"
    sent = await send_raw(client, sid, "after end")
    assert sent.status_code == 409 and sent.json()["detail"]["code"] == "session_ended"
    decided = await client.post(
        f"/api/ai/sessions/{sid}/approvals/{uuid4()}", json={"decision": "deny"}
    )
    assert decided.status_code in (404, 409), decided.text


@pytest.mark.asyncio
async def test_close_while_approval_pending_then_decision_is_a_conflict(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    prompt = 'APPROVE:Write:{"file_path":"/tmp/indep"} go'
    await say(client, sid, prompt)
    async def pending():
        found = await wait_event(client, sid, "approval", 1, state="pending")
        return found[-1]["payload"]["approval_id"]
    aid = await asyncio.wait_for(pending(), 15)
    closed = await asyncio.wait_for(client.post(f"/api/ai/sessions/{sid}/close"), 15)
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "ended"
    late = await client.post(f"/api/ai/sessions/{sid}/approvals/{aid}", json={"decision": "allow_once"})
    assert late.status_code == 409, late.text
    again = await client.post(f"/api/ai/sessions/{sid}/approvals/{aid}", json={"decision": "deny"})
    assert again.status_code == 409 and again.status_code != 500


# ---------------------------------------------------------------------------
# 6) Codex: shell metacharacters and option-like prompts never reach argv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_hostile_prompt_stays_out_of_argv_and_arrives_on_stdin(chat):
    app, client, _, log = chat
    sid = await create(client, "codex")
    hostile = (
        "--zzz-injected-flag ; rm -rf / $(id) `uname` && echo pwnedMARK | cat\n"
        "--sandbox danger-full-access -c evil=1 'quote' \"dq\" > /etc/passwd"
    )
    await say(client, sid, hostile)
    evs = await wait_event(client, sid, "turn_completed", 1)
    assert evs
    launch = launches(log, "codex")[-1]
    argv_blob = " ".join(launch["argv"])
    for fragment in ("--zzz-injected-flag", "pwnedMARK", "rm -rf", "$(id)", "/etc/passwd", "evil=1"):
        assert fragment not in argv_blob, fragment
    assert launch["argv"][-1] == "-", "codex must read the prompt from stdin ('-')"
    # the fake echoes the first 60 characters of what it read from stdin; they must match exactly
    echoed = [e["payload"].get("text", "") for e in await events(client, sid) if e["kind"] == "assistant"]
    assert any(hostile[:60] in text for text in echoed), echoed


@pytest.mark.asyncio
async def test_codex_multiline_prompt_survives_stdin_verbatim(chat):
    app, client, _, _ = chat
    sid = await create(client, "codex")
    text = "LINEONE\nLINETWO\n\tindented \\n literal\nLINETHREE"
    await say(client, sid, text)
    await wait_event(client, sid, "turn_completed", 1)
    echoed = dumped([e["payload"] for e in await events(client, sid)])
    assert "LINETWO" in echoed and "LINETHREE" in echoed


# ---------------------------------------------------------------------------
# 7) agy: every launch carries --print-timeout=, including the argv fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_agy_launch_has_print_timeout_flag(chat):
    app, client, _, log = chat
    sid = await create(client, "gemini")
    await say(client, sid, "first agy turn")
    await wait_event(client, sid, "turn_completed", 1)
    await say(client, sid, "second agy turn")
    await wait_event(client, sid, "turn_completed", 2)
    agy = launches(log, "agy")
    assert len(agy) >= 2
    for launch in agy:
        argv = launch["argv"]
        assert any(a.startswith("--print-timeout=") for a in argv), argv
        assert "--print-timeout" not in argv


@pytest.mark.asyncio
async def test_agy_argv_fallback_still_carries_print_timeout(tmp_path, monkeypatch):
    log = use_fakes(monkeypatch, tmp_path)
    monkeypatch.setenv("FAKE_AGY_NO_STDIN", "1")
    app = make_app(tmp_path)
    async with app.router.lifespan_context(app):
        await configure(app, tmp_path)
        async with client_for(app) as client:
            sid = await create(client, "gemini")
            await say(client, sid, "fallback turn")
            await wait_event(client, sid, "turn_completed", 1)
            agy = launches(log, "agy")
            assert agy, "agy was never launched"
            for launch in agy:
                argv = launch["argv"]
                assert any(a.startswith("--print-timeout=") for a in argv), argv
                assert any(a.startswith("--print=") for a in argv), argv


# ---------------------------------------------------------------------------
# 8) session_seq is contiguous and paging never skips or repeats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_seq_is_contiguous_and_paging_is_lossless(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    for index in range(3):
        await say(client, sid, f"TOOL turn {index}")
        await wait_event(client, sid, "turn_completed", index + 1)
    full = await events(client, sid)
    seqs = [e["session_seq"] for e in full]
    assert seqs == list(range(1, len(seqs) + 1)), seqs
    paged, after = [], 0
    while True:
        page = (
            await client.get(f"/api/ai/sessions/{sid}/events", params={"after_seq": after, "limit": 2})
        ).json()["items"]
        if not page:
            break
        assert len(page) <= 2
        paged.extend(page)
        after = page[-1]["session_seq"]
    assert [e["session_seq"] for e in paged] == seqs
    tail = (await client.get(f"/api/ai/sessions/{sid}/events", params={"after_seq": seqs[-1] + 50})).json()
    assert tail["items"] == []


# ---------------------------------------------------------------------------
# 9) deleting an ended session removes its events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleted_ended_session_returns_404_for_view_and_events(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    await say(client, sid, "to delete")
    await wait_event(client, sid, "turn_completed", 1)
    await client.post(f"/api/ai/sessions/{sid}/close")
    deleted = await client.delete(f"/api/ai/sessions/{sid}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/ai/sessions/{sid}")).status_code == 404
    assert (await client.get(f"/api/ai/sessions/{sid}/events")).status_code == 404
    again = await client.delete(f"/api/ai/sessions/{sid}")
    assert again.status_code in (204, 404)
    assert (await client.post(f"/api/ai/sessions/{sid}/close")).status_code in (404, 409)
    assert (await client.get("/api/ai/sessions")).json()["items"] == []


# ---------------------------------------------------------------------------
# 10) two approvals in one Claude session are independent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_sequential_approvals_in_one_claude_session_are_independent(chat):
    app, client, _, log = chat
    sid = await create(client, "claude_code")
    await say(client, sid, 'APPROVE:Write:{"file_path":"/tmp/one"} go')
    async def pending(count):
        found = await wait_event(client, sid, "approval", count, state="pending")
        return found[-1]["payload"]["approval_id"]
    first = await pending(1)
    assert (await client.post(f"/api/ai/sessions/{sid}/approvals/{first}", json={"decision": "allow_once"})).status_code == 200
    await wait_event(client, sid, "turn_completed", 1)

    await say(client, sid, 'APPROVE:Edit:{"file_path":"/tmp/two"} go')
    second = await pending(2)
    assert second != first
    # replaying the first decision must not touch the second approval
    replay = await client.post(f"/api/ai/sessions/{sid}/approvals/{first}", json={"decision": "deny"})
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "approval_settled"
    still = await client.get(f"/api/ai/sessions/{sid}")
    assert still.json()["pending_approval"] is True
    assert (await client.post(f"/api/ai/sessions/{sid}/approvals/{second}", json={"decision": "deny"})).status_code == 200
    await wait_event(client, sid, "turn_completed", 2)
    decisions = [r["decision"]["behavior"] for r in records(log) if "decision" in r]
    assert decisions == ["allow", "deny"], decisions


@pytest.mark.asyncio
async def test_approval_id_from_another_session_is_not_settled(chat):
    app, client, _, _ = chat
    owner = await create(client, "claude_code")
    other = await create(client, "claude_code")
    await say(client, owner, 'APPROVE:Write:{"file_path":"/tmp/owner"} go')
    found = await wait_event(client, owner, "approval", 1, state="pending")
    aid = found[-1]["payload"]["approval_id"]
    stolen = await client.post(f"/api/ai/sessions/{other}/approvals/{aid}", json={"decision": "allow_once"})
    assert stolen.status_code == 404, stolen.text
    view = (await client.get(f"/api/ai/sessions/{owner}")).json()
    assert view["pending_approval"] is True
    await client.post(f"/api/ai/sessions/{owner}/close")
    await client.post(f"/api/ai/sessions/{other}/close")


# ---------------------------------------------------------------------------
# 11) faults that must not break the session or the server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_stdout_line_does_not_stop_a_claude_turn(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    await say(client, sid, "BADJSON then ok")
    await wait_event(client, sid, "turn_completed", 1)
    assert (await client.get("/api/ai")).status_code == 200
    await say(client, sid, "still alive")
    await wait_event(client, sid, "turn_completed", 2)


@pytest.mark.asyncio
async def test_claude_crash_ends_session_and_server_stays_usable(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    await say(client, sid, "CRASH now")
    view = await session_state(client, sid, "ended")
    assert view["ended_reason"] is not None
    assert (await send_raw(client, sid, "later")).status_code == 409
    fresh = await create(client, "claude_code")
    await say(client, fresh, "healthy")
    await wait_event(client, fresh, "turn_completed", 1)
    await client.post(f"/api/ai/sessions/{fresh}/close")


@pytest.mark.asyncio
async def test_session_limit_for_claude_is_enforced_and_released_on_close(chat):
    app, client, _, _ = chat
    sids = [await create(client, "claude_code") for _ in range(4)]
    fifth = await client.post("/api/ai/sessions", json=new_body("claude_code"))
    assert fifth.status_code == 409 and fifth.json()["detail"]["code"] == "ai_session_limit"
    await client.post(f"/api/ai/sessions/{sids[0]}/close")
    sixth = await client.post("/api/ai/sessions", json=new_body("claude_code"))
    assert sixth.status_code == 200, sixth.text
    for sid in sids[1:] + [sixth.json()["id"]]:
        await client.post(f"/api/ai/sessions/{sid}/close")


@pytest.mark.asyncio
async def test_interrupt_on_idle_session_is_a_noop(chat):
    app, client, _, _ = chat
    sid = await create(client, "claude_code")
    r = await client.post(f"/api/ai/sessions/{sid}/interrupt")
    assert r.status_code == 200 and r.json()["state"] == "idle"
    assert [e for e in await events(client, sid) if e["kind"] == "turn_failed"] == []
    await say(client, sid, "works after noop interrupt")
    await wait_event(client, sid, "turn_completed", 1)
