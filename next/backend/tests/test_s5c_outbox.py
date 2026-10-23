"""S5-C: outbox chunking, drop order, per-slot rate limits, projector isolation, reply routing."""

import asyncio
import time

from tests.s5c_helpers import message, open_s5c, wait


async def rows(store, bot_id, state="pending"):
    return await store.call(
        lambda: [
            dict(r)
            for r in store.require().execute(
                "SELECT * FROM tg_outbox WHERE bot_id=? AND state=? ORDER BY id", (bot_id, state)
            )
        ]
    )


async def test_assistant_text_chunks_at_4000_and_is_plain(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        slot = ctx.slot("codex")
        await slot.enqueue("6001", "ai:ais_" + "a" * 32 + ":1", "x" * 9000, kind="ai_text")
        await wait(lambda: len(ctx.texts("codex")) >= 3)
        assert [len(t) for t in ctx.texts("codex")] == [4000, 4000, 1000]
        assert all("parse_mode" not in m["payload"] for m in ctx.bots.sent[222222222])


async def test_drop_order_tools_then_notify_then_text(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        slot = ctx.slot("codex")
        store, bot = slot.store, slot.bot_id
        slot.task.cancel()  # keep rows pending: nothing is sent
        await asyncio.gather(slot.task, return_exceptions=True)
        for i in range(100):
            await store.enqueue(bot, "6001", f"t{i}", "tool", kind="ai_tool")
        for i in range(100):
            await store.enqueue(bot, "6001", f"n{i}", "note", kind="notify")
        for i in range(300):
            await store.enqueue(bot, "6001", f"x{i}", "text", kind="ai_text")
        await store.enqueue(bot, "6001", "over1", "text", kind="ai_text")
        kinds = [r["kind"] for r in await rows(store, bot)]
        assert len(kinds) == 500 and kinds.count("ai_tool") == 99 and kinds.count("notify") == 100
        for i in range(99):
            await store.enqueue(bot, "6001", f"y{i}", "text", kind="ai_text")
        assert [r["kind"] for r in await rows(store, bot)].count("ai_tool") == 0
        await store.enqueue(bot, "6001", "last", "text", kind="ai_text")
        kinds = [r["kind"] for r in await rows(store, bot)]
        assert kinds.count("notify") == 99
        # A tool summary never evicts text; it is itself dropped when full.
        for i in range(99):
            await store.enqueue(bot, "6001", f"w{i}", "text", kind="ai_text")
        await store.enqueue(bot, "6001", "late-tool", "tool", kind="ai_tool")
        assert "late-tool" not in [r["dedup_key"] for r in await rows(store, bot)]


async def test_dedup_key_is_idempotent(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        slot = ctx.slot("codex")
        key = "ai:ais_" + "b" * 32 + ":5"
        await slot.enqueue("6001", key, "once", kind="ai_text")
        await slot.enqueue("6001", key, "once", kind="ai_text")
        await wait(lambda: ctx.texts("codex"))
        await asyncio.sleep(0.3)
        assert ctx.texts("codex") == ["once"]


async def test_per_chat_and_per_bot_rate_limits(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch, fast_rate=False) as ctx:
        await ctx.ready("gemini", "codex")
        slot = ctx.slot("gemini")
        slot.rate_chat_s = 0.5
        for i in range(3):
            await slot.enqueue("6001", f"k{i}", f"m{i}", kind="ai_text")
        started = time.monotonic()
        await wait(lambda: len(ctx.texts("gemini")) == 3)
        assert time.monotonic() - started >= 0.9  # one message per 0.5 s per chat
        # Different chats are independent of the per-chat interval.
        slot.rate_chat_s = 5.0
        await slot.enqueue("7001", "a", "a", kind="ai_text")
        await slot.enqueue("7002", "b", "b", kind="ai_text")
        await wait(lambda: len(ctx.texts("gemini")) == 5, 5)
        # Per-bot budget is per slot.
        slot.rate_chat_s, slot.rate_bot_n = 0.0, 7
        for i in range(4):
            await slot.enqueue("6001", f"z{i}", f"z{i}", kind="ai_text")
        await asyncio.sleep(1.0)
        assert len(ctx.texts("gemini")) == 7
        await ctx.slot("codex").enqueue("6001", "c", "c", kind="ai_text")
        await wait(lambda: ctx.texts("codex"))


async def test_projector_offer_is_nonblocking_and_bounded(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.bots.hang_send.add(111111111)
        projector = ctx.app.state.ai_projector
        sid = "ais_" + "c" * 32
        projector.bind(sid, "claude_code", "6001", "6001", bot_id=ctx.slot("claude_code").bot_id)
        started = time.monotonic()
        for i in range(20000):
            projector.offer(
                dict(session_id=sid, session_seq=i + 1, kind="assistant", payload={"text": "t"})
            )
        assert time.monotonic() - started < 2.0
        assert projector.queue.qsize() <= projector.queue.maxsize


async def test_projector_ignores_unbound_and_thinking(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        projector = ctx.app.state.ai_projector
        projector.offer(dict(session_id="ais_x", session_seq=1, kind="assistant", payload={}))
        assert projector.queue.empty()
        sid = "ais_" + "d" * 32
        projector.bind(sid, "codex", "6001", "6001", bot_id="1")
        projector.offer(dict(session_id=sid, session_seq=1, kind="thinking", payload={}))
        assert projector.queue.empty()


async def test_reply_to_output_routes_to_that_session(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        ctx.post("codex", message(ctx.uid(), "/menu"))
        await wait(lambda: ctx.texts("codex"))
        for label in ("新建", "repo", "默认模型", "medium", "read-only"):
            before = await ctx.click("codex", label)
            await wait(lambda before=before: len(ctx.texts("codex")) > before)
        ctx.post("codex", message(ctx.uid(), "first"))
        await wait(lambda: any(t.startswith("echo:first") for t in ctx.texts("codex")))
        out = next(
            m for m in ctx.bots.sent[222222222] if m["payload"]["text"].startswith("echo:first")
        )
        session = (await ctx.client.get("/api/ai/sessions")).json()["items"][0]["id"]
        ctx.slot("codex").focus.clear()  # no focus: only the reply target names the session
        ctx.post("codex", message(ctx.uid(), "second", reply_to=out["message_id"]))
        await wait(lambda: any(t.startswith("echo:second") for t in ctx.texts("codex")))
        events = (await ctx.client.get(f"/api/ai/sessions/{session}/events")).json()["items"]
        texts = [e["payload"]["text"] for e in events if e["kind"] == "turn_started"]
        assert texts[-2:] == ["first", "second"]


async def test_reenable_drops_stale_ai_output(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        slot = ctx.slot("codex")
        ctx.bots.hang_send.add(222222222)
        await slot.enqueue("6001", "ai:ais_" + "e" * 32 + ":1", "stale", kind="ai_text")
        await ctx.disable("codex")
        ctx.bots.hang_send.clear()
        await ctx.enable("codex")
        await wait(lambda: slot.state == "polling")
        await asyncio.sleep(0.3)
        assert "stale" not in ctx.texts("codex")


async def test_agy_models_endpoint_uses_fake_cli(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        body = (await ctx.client.get("/api/ai/agy-models")).json()
        assert body["items"] == ["fake-agy-fast", "fake-agy-pro"] and body["category"] is None
