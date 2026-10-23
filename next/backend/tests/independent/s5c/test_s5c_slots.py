"""Requirement tests: four Telegram slots (main + three AI bots) and their control plane."""

import asyncio

from tests.independent.s5c.support import bot_id, sent_count, sent_texts
from tests.s5c_helpers import message, open_s5c, wait

ALL_AI = ("claude_code", "codex", "gemini")


async def test_four_slots_start_independently(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready(*ALL_AI, main=True)
        for ai_id in ALL_AI:
            assert ctx.slot(ai_id).state == "polling"
        assert ctx.main.state == "polling"
        view = (await ctx.client.get("/api/telegram/ai-bots")).json()
        assert {item["ai_id"] for item in view["items"]} == set(ALL_AI)
        assert all(item["control"]["enabled"] for item in view["items"])
        ids = {bot_id(a) for a in ALL_AI} | {bot_id("main")}
        assert len(ids) == 4


async def test_disabling_one_slot_leaves_the_others_polling(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready(*ALL_AI, main=True)
        await ctx.disable("codex")
        assert ctx.slot("codex").state == "disabled"
        assert ctx.slot("claude_code").state == "polling"
        assert ctx.slot("gemini").state == "polling"
        assert ctx.main.state == "polling"
        ctx.post("gemini", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "gemini"))


async def test_conflict_on_one_slot_does_not_touch_others_or_delete_webhook(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code", "codex", main=True)
        before_deletes = [
            b for b, m, _ in ctx.bots.requests if m == "deleteWebhook" and b == int(bot_id("claude_code"))
        ]
        ctx.bots.conflict.add(int(bot_id("claude_code")))
        await wait(lambda: ctx.slot("claude_code").state == "conflict", 20)
        assert ctx.slot("codex").state == "polling"
        assert ctx.main.state == "polling"
        ctx.post("codex", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "codex"))
        # Let the conflicted poller retry a few times; it must never take over the bot.
        await asyncio.sleep(0.4)
        after_deletes = [
            b for b, m, _ in ctx.bots.requests if m == "deleteWebhook" and b == int(bot_id("claude_code"))
        ]
        assert after_deletes == before_deletes
        assert ctx.slot("claude_code").state == "conflict"


async def test_same_bot_id_on_second_slot_is_bot_in_use(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code", main=True)
        # Same numeric bot id as the main bot, different secret.
        clash = "123456789:ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        await ctx.put_token("codex", clash)
        response = await ctx.enable("codex", expect=409)
        assert "bot_in_use" in response.text
        assert ctx.slot("codex").state != "polling"
        assert ctx.main.state == "polling"


async def test_main_and_ai_slot_cannot_share_bot_even_after_reenable(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code", main=True)
        clash = "111111111:ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
        await ctx.disable("main")
        await ctx.put_token("main", clash)  # main would collide with claude_code's bot
        response = await ctx.client.post(
            "/api/telegram/control/enable",
            json={"revision": await ctx.revision(), "ack_old_bot_stopped": True},
        )
        assert response.status_code == 409, response.text
        assert "bot_in_use" in response.text


async def test_first_enable_drops_backlog_instead_of_replaying(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        ctx.post("claude_code", message(ctx.uid(), "/menu"))  # queued before enabling
        await ctx.put_token("claude_code")
        await ctx.enable("claude_code")
        await wait(lambda: ctx.slot("claude_code").state == "polling")
        await asyncio.sleep(0.5)
        assert sent_count(ctx, "claude_code") == 0


async def test_expired_slot_commands_are_refused_not_executed(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu", age=600))
        await wait(lambda: any("过期" in t for t in sent_texts(ctx, "claude_code")))
        assert not any("活动" in t for t in sent_texts(ctx, "claude_code"))


async def test_expired_plain_text_is_not_executed(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "claude_code"))
        before = sent_count(ctx, "claude_code")
        ctx.post("claude_code", message(ctx.uid(), "hello TOOLS3", age=600))
        await wait(lambda: sent_count(ctx, "claude_code") > before)
        assert any("过期" in t for t in sent_texts(ctx, "claude_code")[before:])
        assert await ctx.client.get("/api/ai/sessions") is not None
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []


async def test_enable_requires_ack_and_revision(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.put_token("claude_code")
        response = await ctx.client.post(
            "/api/telegram/ai-bots/claude_code/control/enable",
            json={"revision": await ctx.revision(), "ack_old_bot_cleared": False},
        )
        assert response.status_code in {400, 409, 422}, response.text
        assert ctx.slot("claude_code").state != "polling"
        stale = await ctx.client.post(
            "/api/telegram/ai-bots/claude_code/control/enable",
            json={"revision": 0, "ack_old_bot_cleared": True},
        )
        assert stale.status_code == 409, stale.text


async def test_active_slot_token_cannot_be_deleted(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        response = await ctx.client.delete(
            "/api/telegram/ai-bots/claude_code/token", params={"revision": await ctx.revision()}
        )
        assert response.status_code == 409, response.text
        assert "telegram_active" in response.text
        assert ctx.slot("claude_code").state == "polling"


async def test_retry_is_refused_while_polling(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        response = await ctx.client.post(
            "/api/telegram/ai-bots/claude_code/control/retry",
            json={"revision": await ctx.revision()},
        )
        assert response.status_code == 409, response.text
        assert "telegram_active" in response.text


async def test_close_releases_store_and_clients_of_every_slot(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready(*ALL_AI, main=True)
        slots = [ctx.main] + [ctx.slot(a) for a in ALL_AI]
        for ai_id in ALL_AI:
            await ctx.disable(ai_id)
        await ctx.disable("main")
        for svc in slots:
            assert svc.client is None, svc.slot
            assert svc.state == "disabled", svc.slot
        assert ctx.main.store._db is None
    # After the app lifespan closed, every store handle is gone too.
    for svc in slots:
        assert svc.client is None
