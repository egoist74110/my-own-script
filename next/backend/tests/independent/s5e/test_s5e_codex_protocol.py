"""Independent S5-E1 protocol requirements, using only in-memory services and fake CLIs."""

# ruff: noqa: F811

import asyncio
import json
from uuid import UUID

import pytest

from tests.independent.s5c.support import sent_texts
from tests.s5b_helpers import chat, events, new_body, say, wait_event  # noqa: F401
from tests.s5c_helpers import callback, message, open_s5c, wait
from toolbox_backend.adapters.ai_cli import codex
from toolbox_backend.adapters.ai_process import SupervisedProcess


@pytest.mark.asyncio
async def test_http_codex_accepts_new_efforts_and_rejects_unknown(chat):
    _, client, _, _ = chat
    for effort in ("none", "xhigh", "max"):
        response = await client.post(
            "/api/ai/sessions", json=new_body("codex", effort=effort)
        )
        assert response.status_code == 200, (effort, response.text)
        sid = response.json()["id"]
        view = (await client.get(f"/api/ai/sessions/{sid}")).json()
        assert view["effort"] == effort
        await client.post(f"/api/ai/sessions/{sid}/close")

    invalid = await client.post(
        "/api/ai/sessions", json=new_body("codex", effort="unbounded")
    )
    assert invalid.status_code == 422, invalid.text


async def _walk_codex_wizard(ctx, effort):
    bot_id = int(ctx.bot_id("codex"))
    before = len(ctx.bots.sent.get(bot_id, []))
    ctx.post("codex", message(ctx.uid(), "/menu"))
    await wait(lambda: len(ctx.bots.sent.get(bot_id, [])) > before)
    for label in ("新建", "repo", "默认模型", effort, "read-only"):
        before = len(ctx.bots.sent.get(bot_id, []))
        await ctx.click("codex", label)
        try:
            await wait(lambda b=before: len(ctx.bots.sent.get(bot_id, [])) > b, timeout=3)
        except AssertionError:
            raise AssertionError(f"wizard stalled after {label!r}: {sent_texts(ctx, 'codex')[-3:]}") from None
    return next(text for text in reversed(sent_texts(ctx, "codex")) if "已创建会话" in text)


@pytest.mark.asyncio
async def test_telegram_codex_wizard_offers_and_accepts_new_efforts(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        for effort in ("none", "xhigh", "max"):
            before = {
                item["id"] for item in (await ctx.client.get("/api/ai/sessions")).json()["items"]
            }
            created = await _walk_codex_wizard(ctx, effort)
            assert "已创建会话" in created
            sessions = (await ctx.client.get("/api/ai/sessions")).json()["items"]
            session = next(item for item in sessions if item["id"] not in before)
            assert session["effort"] == effort
            await ctx.client.post(f"/api/ai/sessions/{session['id']}/close")


@pytest.mark.asyncio
async def test_telegram_codex_rejects_forged_unknown_effort(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        svc = ctx.slot("codex")
        token = await svc.store.action(
            svc.bot_id,
            "6001",
            "6001",
            "ai_wiz",
            {
                "w": "create",
                "a": {
                    "repo_id": "repo",
                    "effort": "unbounded",
                    "sandbox": "read-only",
                },
            },
        )
        ctx.post("codex", callback(ctx.uid(), token))
        await asyncio.sleep(0.25)
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "4", None, {}, []])
def test_codex_usage_rejects_non_nonnegative_integer_values(value):
    parsed = codex.parse(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": value,
                "output_tokens": value,
                "cached_input_tokens": value,
                "reasoning_output_tokens": value,
            },
        }
    )
    assert parsed[0].payload == {
        "is_error": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_output_tokens": 0,
    }


def _install_codex_stream(monkeypatch):
    class Writer:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            return None

    class Proc:
        def __init__(self, code):
            self.code = code

        async def wait(self):
            return self.code

    class ProcessDouble:
        def __init__(self, identity, code):
            self.identity = identity
            self.proc = Proc(code)
            self.stdin = Writer()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()

        async def close_stdin(self):
            prompt = self.stdin.data.decode()
            def emit(obj):
                return json.dumps(obj).encode() + b"\n"
            common = [
                {"type": "thread.started", "thread_id": "b7c7dd44-1d28-48d8-bd19-48e205615e54"},
                {"type": "turn.started"},
            ]
            if "FAIL" in prompt:
                error_text = "authorization: Bearer S5E_FAKE_SECRET Invalid value: " + "x" * 700
                raw = json.dumps(
                    {
                        "type": "error",
                        "error": {
                            "message": error_text,
                            "type": "invalid_request_error",
                        },
                        "status": 400,
                    }
                )
                common += [
                    {"type": "error", "message": raw},
                    {"type": "turn.failed", "error": {"message": raw}},
                ]
                self.proc.code = 1
            else:
                usage = (
                    {
                        "input_tokens": 100,
                        "cached_input_tokens": 20,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 5,
                        "reasoning_output_tokens": 3,
                    }
                    if "first" in prompt
                    else {
                        "input_tokens": 7,
                        "output_tokens": 5,
                        "cached_input_tokens": 6,
                        "reasoning_output_tokens": 1,
                        "cache_write_input_tokens": 0,
                    }
                )
                common += [
                    {
                        "type": "item.started",
                        "item": {
                            "id": "cmd1",
                            "type": "command_execution",
                            "command": "pwd",
                            "aggregated_output": "",
                            "exit_code": None,
                            "status": "in_progress",
                        },
                    },
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "cmd1",
                            "type": "command_execution",
                            "command": "pwd",
                            "aggregated_output": "/tmp",
                            "exit_code": 0,
                            "status": "completed",
                        },
                    },
                    {"type": "item.completed", "item": {"id": "msg1", "type": "agent_message", "text": "ok"}},
                    {"type": "turn.completed", "usage": usage},
                ]
            self.stdout.feed_data(b"".join(emit(obj) for obj in common))
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        async def close(self):
            return None

    counter = 0

    async def fake_start(cls, argv, cwd, *, slave=None, stdio=False, path_extras=None):
        nonlocal counter
        counter += 1
        return ProcessDouble(
            {"pid": 900000 + counter, "pgid": 900000 + counter, "executable": "test-double"},
            0,
        )

    monkeypatch.setattr(SupervisedProcess, "start", classmethod(fake_start))


@pytest.mark.asyncio
async def test_codex_real_shape_stream_resumes_once_aggregates_and_redacts(chat, monkeypatch):
    app, client, _, _ = chat
    _install_codex_stream(monkeypatch)
    sid = (
        await client.post("/api/ai/sessions", json=new_body("codex", effort="medium"))
    ).json()["id"]

    await say(client, sid, "first turn")
    try:
        await wait_event(client, sid, "turn_completed", 1)
    except AssertionError:
        raise AssertionError(await events(client, sid)) from None
    await say(client, sid, "second turn")
    await wait_event(client, sid, "turn_completed", 2)

    stream_events = await events(client, sid)
    inits = [event for event in stream_events if event["kind"] == "init"]
    assert len(inits) == 1
    thread_id = inits[0]["payload"]["external_id"]
    assert str(UUID(thread_id)) == thread_id
    completed = [event for event in stream_events if event["kind"] == "turn_completed"]
    assert [
        {
            key: event["payload"][key]
            for key in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "reasoning_output_tokens",
            )
        }
        for event in completed
    ] == [
        {
            "input_tokens": 100,
            "output_tokens": 5,
            "cached_input_tokens": 20,
            "reasoning_output_tokens": 3,
        },
        {
            "input_tokens": 7,
            "output_tokens": 5,
            "cached_input_tokens": 6,
            "reasoning_output_tokens": 1,
        },
    ]
    assert any(event["kind"] == "assistant" and event["payload"]["text"] == "ok" for event in stream_events)
    assert sum(event["kind"] == "tool_use" for event in stream_events) == 2
    assert sum(event["kind"] == "tool_result" and not event["payload"]["is_error"] for event in stream_events) == 2
    view = (await client.get(f"/api/ai/sessions/{sid}")).json()
    assert view["has_external_id"] is True
    assert view["usage"] == {
        "turns": 2,
        "cost_usd": 0.0,
        "input_tokens": 107,
        "output_tokens": 10,
        "cached_input_tokens": 26,
        "reasoning_output_tokens": 4,
    }

    await say(client, sid, "FAIL now")
    failed = await wait_event(client, sid, "turn_failed", 1)
    assert failed[0]["payload"]["category"] == "cli_error"
    assert "Invalid value" in failed[0]["payload"]["message"]
    assert "S5E_FAKE_SECRET" not in json.dumps(failed)
    assert len(failed[0]["payload"]["message"]) <= 500
    assert "authorization: ***" in failed[0]["payload"]["message"]
    errors = [event for event in await events(client, sid) if event["kind"] == "error"]
    assert errors and "S5E_FAKE_SECRET" not in json.dumps(errors)
    await client.post(f"/api/ai/sessions/{sid}/close")
