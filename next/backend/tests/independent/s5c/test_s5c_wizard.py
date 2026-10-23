"""Requirement tests: the Telegram wizard offers only the safe choices of each CLI."""

import asyncio

from tests.independent.s5c.support import buttons, sent_count, sent_texts, sessions
from tests.s5c_helpers import message, open_s5c, wait


async def _walk(ctx, ai_id, *labels):
    ctx.post(ai_id, message(ctx.uid(), "/menu"))
    await wait(lambda: sent_texts(ctx, ai_id))
    for label in labels:
        before = sent_count(ctx, ai_id)
        await ctx.click(ai_id, label)
        await wait(lambda b=before: sent_count(ctx, ai_id) > b)


async def test_codex_wizard_offers_only_read_only_and_workspace_write(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("codex")
        await _walk(ctx, "codex", "新建", "repo")
        # Codex skips the Claude fresh/resume question: the next step is model/effort/sandbox.
        labels_before = [lab for lab, _ in buttons(ctx, "codex")]
        assert labels_before, "wizard offered no model choices"
        await _walk_next(ctx, "codex", labels_before[0])
        effort = [lab for lab, _ in buttons(ctx, "codex")]
        await _walk_next(ctx, "codex", effort[0])
        sandbox = [lab for lab, _ in buttons(ctx, "codex")]
        joined = " ".join(sandbox).lower()
        assert "read-only" in joined or "只读" in joined, sandbox
        assert "workspace-write" in joined or "工作区" in joined or "写" in joined, sandbox
        assert "danger" not in joined and "full" not in joined and "完全" not in joined, sandbox


async def _walk_next(ctx, ai_id, label):
    before = sent_count(ctx, ai_id)
    await ctx.click(ai_id, label)
    await wait(lambda: sent_count(ctx, ai_id) > before)


async def test_agy_wizard_offers_only_sandbox_and_plan(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("gemini")
        await _walk(ctx, "gemini", "新建", "repo")
        models = [lab for lab, _ in buttons(ctx, "gemini")]
        assert models, "wizard offered no agy model choices"
        await _walk_next(ctx, "gemini", models[0])
        modes = [lab for lab, _ in buttons(ctx, "gemini")]
        joined = " ".join(modes).lower()
        assert "sandbox" in joined or "沙" in joined, modes
        assert "plan" in joined or "规划" in joined, modes
        assert "auto" not in joined and "自动" not in joined, modes


async def test_plain_text_without_focus_opens_menu_not_session(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        ctx.post("claude_code", message(ctx.uid(), "hello there"))
        await wait(lambda: any("会话" in t for t in sent_texts(ctx, "claude_code")))
        await asyncio.sleep(0.3)
        assert (await sessions(ctx)) == []
