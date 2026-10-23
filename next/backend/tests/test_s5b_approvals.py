# ruff: noqa: F811
"""S5-B: Claude tool approvals over the stdio permission protocol."""

import asyncio
import hashlib
import json
import sqlite3

import pytest

from tests.s5b_helpers import (
    chat,  # noqa: F401  (fixture)
    events,
    new_body,
    records,
    say,
    session_state,
    wait_event,
    wait_for,
)


def tool_prompt(tool, **data):
    return "APPROVE:%s:%s go" % (tool, json.dumps(data, separators=(",", ":")))


async def new_session(client, **extra):
    return (await client.post("/api/ai/sessions", json=new_body(**extra))).json()["id"]


async def pending(client, sid, count=1):
    found = await wait_event(client, sid, "approval", count, state="pending")
    return found[-1]["payload"]["approval_id"]


async def decide(client, sid, aid, decision):
    return await client.post(
        f"/api/ai/sessions/{sid}/approvals/{aid}", json=dict(decision=decision)
    )


def decisions(log):
    return [r["decision"] for r in records(log) if "decision" in r]


@pytest.mark.asyncio
async def test_allow_once_deny_and_input_not_stored(chat):
    app, client, _, log = chat
    sid = await new_session(client)
    await say(client, sid, tool_prompt("Write", file_path="/tmp/x"))
    aid = await pending(client, sid)
    view = await session_state(client, sid, "awaiting_approval")
    assert view["pending_approval"] is True
    assert (await decide(client, sid, aid, "allow_once")).json()["state"] == "allowed"
    await wait_event(client, sid, "turn_completed", 1)
    allow = decisions(log)[-1]
    assert allow["behavior"] == "allow"
    assert allow["updatedInput"] == {"file_path": "/tmp/x", "content": "MARKERXYZ-CONTENT"}
    await say(client, sid, tool_prompt("Edit", file_path="/tmp/y"))
    aid2 = await pending(client, sid, 2)
    assert (await decide(client, sid, aid2, "deny")).json()["state"] == "denied"
    await wait_event(client, sid, "turn_completed", 2)
    assert decisions(log)[-1]["behavior"] == "deny" and decisions(log)[-1]["message"]
    rows = sqlite3.connect(app.state.ai_store.path).execute(
        "SELECT state,input_digest,summary FROM ai_approvals ORDER BY requested_at"
    ).fetchall()
    assert [r[0] for r in rows] == ["allowed", "denied"]
    expected = hashlib.sha256(
        json.dumps(
            {"file_path": "/tmp/x", "content": "MARKERXYZ-CONTENT"}, sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()
    assert rows[0][1] == expected and rows[0][2] == "/tmp/x"
    raw = b"".join(p.read_bytes() for p in app.state.ai_store.path.parent.glob("ai.sqlite3*"))
    assert b"MARKERXYZ-CONTENT" not in raw
    assert "MARKERXYZ-CONTENT" not in repr(await events(client, sid))
    assert (await client.get(f"/api/ai/sessions/{sid}")).json()["state"] == "idle"
    missing = await decide(client, sid, "apr_none", "deny")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_session_rule_matches_plain_commands_only(chat):
    app, client, _, log = chat
    sid = await new_session(client)
    await say(client, sid, tool_prompt("Bash", command="ls -la"))
    aid = await pending(client, sid)
    await decide(client, sid, aid, "allow_session")
    await wait_event(client, sid, "turn_completed", 1)
    # same first word, plain command: auto allowed without a pending approval
    await say(client, sid, tool_prompt("Bash", command="ls /tmp"))
    await wait_event(client, sid, "turn_completed", 2)
    auto = await wait_event(client, sid, "approval", 1, auto=True)
    assert auto[0]["payload"]["state"] == "allowed" and decisions(log)[-1]["behavior"] == "allow"
    # compound commands are never covered by the rule
    for number, command in enumerate(
        ["ls; rm -rf x", "ls && id", "ls | cat", "ls `id`", "ls $(id)", "ls\nid", "ls > f"], start=2
    ):
        await say(client, sid, tool_prompt("Bash", command=command))
        got = await pending(client, sid, number)
        view = await session_state(client, sid, "awaiting_approval")
        assert view["pending_approval"]
        await decide(client, sid, got, "deny")
        await wait_event(client, sid, "turn_completed", number + 1)
    # a different tool and a different first word still ask
    await say(client, sid, tool_prompt("Bash", command="rm x"))
    await pending(client, sid, 9)
    await client.post(f"/api/ai/sessions/{sid}/close")


@pytest.mark.asyncio
async def test_double_decision_only_one_wins(chat):
    app, client, _, log = chat
    sid = await new_session(client)
    await say(client, sid, tool_prompt("Bash", command="id"))
    aid = await pending(client, sid)
    first, second = await asyncio.gather(
        decide(client, sid, aid, "allow_once"), decide(client, sid, aid, "deny")
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [200, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["detail"]["code"] == "approval_settled"
    await wait_event(client, sid, "turn_completed")
    assert len(decisions(log)) == 1
    again = await decide(client, sid, aid, "allow_once")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "approval_settled"


@pytest.mark.asyncio
async def test_timeout_denies_and_late_decision_is_expired(chat):
    app, client, _, log = chat
    app.state.ai_service.approval_ttl_s = 0.4
    sid = await new_session(client)
    await say(client, sid, tool_prompt("Bash", command="id"))
    aid = await pending(client, sid)
    await wait_event(client, sid, "approval", 1, state="expired")
    await wait_event(client, sid, "turn_completed")
    assert decisions(log)[-1]["behavior"] == "deny"
    late = await decide(client, sid, aid, "allow_once")
    assert late.status_code == 409 and late.json()["detail"]["code"] == "approval_expired"


@pytest.mark.asyncio
async def test_interrupt_and_close_expire_pending(chat):
    app, client, _, log = chat
    sid = await new_session(client)
    await say(client, sid, tool_prompt("Bash", command="id"))
    aid = await pending(client, sid)
    await client.post(f"/api/ai/sessions/{sid}/interrupt")
    await wait_event(client, sid, "approval", 1, state="expired")
    await wait_for(lambda: asyncio.sleep(0, result=bool(decisions(log))))
    assert decisions(log)[0]["behavior"] == "deny"
    gone = await decide(client, sid, aid, "allow_once")
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "approval_expired"
    await session_state(client, sid, "idle")
    await say(client, sid, tool_prompt("Bash", command="id2"))
    aid2 = await pending(client, sid, 2)
    await client.post(f"/api/ai/sessions/{sid}/close")
    row = sqlite3.connect(app.state.ai_store.path).execute(
        "SELECT state FROM ai_approvals WHERE id=?", (aid2,)
    ).fetchone()
    assert row[0] == "expired"
    ended = await decide(client, sid, aid2, "allow_once")
    assert ended.status_code == 409 and ended.json()["detail"]["code"] == "approval_expired"
