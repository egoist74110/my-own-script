"""Requirement tests: AI slots act only for the owner in a private chat; tokens are single-use and bound."""

import asyncio

from tests.independent.s5c.support import (
    buttons,
    find_button,
    records_of_fake,
    sent_count,
    sent_texts,
)
from tests.s5c_helpers import OWNER, callback, message, open_s5c, wait

STRANGER = 7777


async def _quiet(ctx, ai_id, before=0, grace=0.4):
    """True when nothing new was sent to the slot's bot during the grace period."""
    await asyncio.sleep(grace)
    return sent_count(ctx, ai_id) == before


async def test_stranger_private_chat_gets_no_reply_and_no_session(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu", chat=STRANGER, user=STRANGER))
        ctx.post("claude_code", message(ctx.uid(), "hello TOOLS3", chat=STRANGER, user=STRANGER))
        assert await _quiet(ctx, "claude_code")
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []


async def test_owner_in_group_gets_no_reply(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu", private=False))
        ctx.post("claude_code", message(ctx.uid(), "hello", private=False))
        assert await _quiet(ctx, "claude_code")


async def test_forged_callback_data_has_no_effect(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", callback(ctx.uid(), "A" * 22))
        ctx.post("claude_code", callback(ctx.uid(), "not-a-token"))
        ctx.post("claude_code", callback(ctx.uid(), "{\"kind\":\"ai_wiz\"}"))
        assert await _quiet(ctx, "claude_code")
        assert not records_of_fake(ctx)


async def test_slot_ignores_main_bot_commands(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        for text in ("/bind", "/run", "/wi", "/tasks", "/status"):
            ctx.post("claude_code", message(ctx.uid(), text))
        assert await _quiet(ctx, "claude_code")


async def test_stranger_cannot_replay_owner_token(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "claude_code"))
        token = find_button(ctx, "claude_code", "新建")
        before = sent_count(ctx, "claude_code")
        ctx.post("claude_code", callback(ctx.uid(), token, chat=STRANGER, user=STRANGER))
        assert await _quiet(ctx, "claude_code", before)


async def test_owner_token_replayed_in_group_chat_is_refused(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "claude_code"))
        token = find_button(ctx, "claude_code", "新建")
        before = sent_count(ctx, "claude_code")
        ctx.post("claude_code", callback(ctx.uid(), token, chat=OWNER, private=False))
        assert await _quiet(ctx, "claude_code", before)


async def test_token_is_single_use(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "claude_code"))
        token = find_button(ctx, "claude_code", "新建")
        ctx.post("claude_code", callback(ctx.uid(), token))
        await wait(lambda: any("选择本地仓库" in t for t in sent_texts(ctx, "claude_code")))
        before = sent_count(ctx, "claude_code")
        ctx.post("claude_code", callback(ctx.uid(), token))  # replay by the owner
        assert await _quiet(ctx, "claude_code", before)


async def test_owner_change_revokes_slot_access(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "claude_code"))
        before = sent_count(ctx, "claude_code")

        def revoke(c):
            c.telegram.owner.chat_id = "8888"
            c.telegram.owner.source = "bound"

        config = await ctx.app.state.config_store.read()
        await ctx.app.state.config_store.update(config.revision, revoke)
        ctx.post("claude_code", message(ctx.uid(), "/menu"))
        assert await _quiet(ctx, "claude_code", before)


async def test_wizard_offers_only_safe_permissions(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "/menu"))
        await wait(lambda: sent_texts(ctx, "claude_code"))
        for label in ("新建", "repo", "全新"):
            before = sent_count(ctx, "claude_code")
            await ctx.click("claude_code", label)
            await wait(lambda b=before: sent_count(ctx, "claude_code") > b)
        labels = [label for label, _ in buttons(ctx, "claude_code")]
        assert sorted(labels) == sorted(
            ["自动（默认）", "自动接受编辑", "仅规划", "每次审批", "不询问（拒绝未放行）"]
        )
        assert not any("bypass" in lab.lower() or "绕过" in lab or "危险" in lab for lab in labels)


async def test_forged_high_risk_claude_permission_is_refused(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        svc = ctx.slot("claude_code")
        for perm in ("bypassPermissions", "dontAsk-but-high"):
            token = await svc.store.action(
                svc.bot_id, OWNER, OWNER, "ai_wiz",
                {"w": "create", "a": {"repo_id": "repo", "permission": perm}},
            )
            ctx.post("claude_code", callback(ctx.uid(), token))
        assert await _quiet(ctx, "claude_code")
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []
        assert not records_of_fake(ctx)


async def test_forged_extra_keys_and_unknown_repo_are_refused(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        svc = ctx.slot("claude_code")
        extra = await svc.store.action(
            svc.bot_id, OWNER, OWNER, "ai_wiz",
            {"w": "create", "a": {"repo_id": "repo", "permission": "manual", "ack_high_risk": True}},
        )
        ghost = await svc.store.action(
            svc.bot_id, OWNER, OWNER, "ai_wiz",
            {"w": "create", "a": {"repo_id": "no-such-repo", "permission": "manual"}},
        )
        ctx.post("claude_code", callback(ctx.uid(), extra))
        ctx.post("claude_code", callback(ctx.uid(), ghost))
        await asyncio.sleep(0.4)
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []
        assert not records_of_fake(ctx)


async def test_forged_codex_danger_sandbox_is_refused(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        svc = ctx.slot("codex")
        token = await svc.store.action(
            svc.bot_id, OWNER, OWNER, "ai_wiz",
            {"w": "create", "a": {"repo_id": "repo", "sandbox": "danger-full-access", "effort": "low"}},
        )
        ctx.post("codex", callback(ctx.uid(), token))
        assert await _quiet(ctx, "codex")
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []
        assert not records_of_fake(ctx)


async def test_forged_agy_auto_mode_is_refused(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("gemini")
        svc = ctx.slot("gemini")
        token = await svc.store.action(
            svc.bot_id, OWNER, OWNER, "ai_wiz",
            {"w": "create", "a": {"repo_id": "repo", "mode": "auto"}},
        )
        ctx.post("gemini", callback(ctx.uid(), token))
        assert await _quiet(ctx, "gemini")
        assert (await ctx.client.get("/api/ai/sessions")).json()["items"] == []


async def test_slot_does_not_answer_when_main_bot_commands_sent_to_it(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        ctx.post("codex", message(ctx.uid(), "/bind 123456"))
        assert await _quiet(ctx, "codex")
