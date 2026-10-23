"""Requirement tests: session events project to Telegram; approvals; no blocking; redaction."""

import asyncio

from tests.independent.s5c.support import (
    bot_id,
    buttons,
    create_claude_session,
    find_button,
    sent_count,
    sent_texts,
    sessions,
)
from tests.s5c_helpers import TOKENS, callback, message, open_s5c, wait


async def _turn_done(ctx, ai_id, marker="完成", timeout=25):
    await wait(lambda: any(marker in t for t in sent_texts(ctx, ai_id)), timeout)


async def test_tool_calls_are_merged_into_one_summary(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx, "每次审批")
        ctx.post("claude_code", message(ctx.uid(), "hello TOOLS3 world"))
        await _turn_done(ctx, "claude_code")
        tool_msgs = [t for t in sent_texts(ctx, "claude_code") if t.startswith("🔧")]
        assert len(tool_msgs) == 1, tool_msgs
        assert "等" in tool_msgs[0]


async def test_turn_end_sends_single_completion_marker(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx)
        ctx.post("claude_code", message(ctx.uid(), "hello TOOLS3 world"))
        await _turn_done(ctx, "claude_code")
        await asyncio.sleep(0.3)
        done = [t for t in sent_texts(ctx, "claude_code") if t.startswith("✓ 完成")]
        assert len(done) == 1, sent_texts(ctx, "claude_code")


async def test_assistant_text_is_plain_and_thinking_is_not_forwarded(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx)
        ctx.post("claude_code", message(ctx.uid(), "plain words"))
        await wait(lambda: any("echo:plain words" in t for t in sent_texts(ctx, "claude_code")), 20)
        for m in ctx.bots.sent[int(bot_id("claude_code"))]:
            assert "parse_mode" not in m["payload"], m["payload"]


async def test_failed_turn_reports_error_category(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx)
        ctx.post("claude_code", message(ctx.uid(), "please FAIL now"))
        await wait(lambda: any("出错" in t for t in sent_texts(ctx, "claude_code")), 25)
        assert any(t.startswith("❌ 出错") for t in sent_texts(ctx, "claude_code"))


async def test_failed_tool_result_is_forwarded(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx)
        ctx.post("claude_code", message(ctx.uid(), "TOOLFAIL please"))
        # The fake also trips its FAIL branch, so the turn ends as an error after the tool failure.
        await wait(lambda: any("工具失败" in t for t in sent_texts(ctx, "claude_code")), 25)
        texts = sent_texts(ctx, "claude_code")
        failed = [t for t in texts if "工具失败" in t]
        assert failed and "command failed badly" in failed[0], texts
        assert not any(t.startswith("🔧 Bash: false") and "成功" in t for t in texts)


async def test_flood_is_bounded_and_turn_still_completes(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx)
        ctx.post("claude_code", message(ctx.uid(), "MANYLINES"))
        await _turn_done(ctx, "claude_code", timeout=60)
        assert len(sent_texts(ctx, "claude_code")) < 1500


async def test_hung_telegram_send_does_not_block_session(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx)
        sid = (await sessions(ctx))[0]["id"]
        ctx.bots.hang_send.add(int(bot_id("claude_code")))
        ctx.post("claude_code", message(ctx.uid(), "hello TOOLS3 hang"))
        for _ in range(200):
            state = (await ctx.client.get(f"/api/ai/sessions/{sid}")).json()["state"]
            if state in {"idle", "done"}:
                break
            await asyncio.sleep(0.1)
        assert state in {"idle", "done"}, state
        ctx.bots.hang_send.discard(int(bot_id("claude_code")))


async def test_bot_token_is_redacted_from_projected_text(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx)
        secret = TOKENS["claude_code"]
        ctx.post("claude_code", message(ctx.uid(), f"leak {secret} end"))
        await wait(lambda: any("echo" in t or "完成" in t for t in sent_texts(ctx, "claude_code")), 25)
        joined = "\n".join(sent_texts(ctx, "claude_code"))
        assert secret not in joined
        assert secret.split(":", 1)[1] not in joined


async def test_claude_approval_offers_only_allow_once_and_deny(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx, "每次审批")
        ctx.post("claude_code", message(ctx.uid(), 'APPROVE:Bash:{"command":"ls"} go'))
        await wait(lambda: any(lab == "✅ 允许一次" for lab, _ in buttons(ctx, "claude_code")), 25)
        labels = [lab for lab, _ in buttons(ctx, "claude_code")]
        assert "❌ 拒绝" in labels
        assert not any("始终" in lab for lab in labels)


async def test_approval_click_decides_once_then_reports_settled(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx, "每次审批")
        ctx.post("claude_code", message(ctx.uid(), 'APPROVE:Bash:{"command":"ls"} go'))
        await wait(lambda: any(lab == "✅ 允许一次" for lab, _ in buttons(ctx, "claude_code")), 25)
        token = find_button(ctx, "claude_code", "允许一次")
        ctx.post("claude_code", callback_update(ctx.uid(), token))
        await wait(lambda: any("已允许一次" in t for t in sent_texts(ctx, "claude_code")), 15)
        await _turn_done(ctx, "claude_code")
        mark = sent_count(ctx, "claude_code")
        ctx.post("claude_code", callback_update(ctx.uid(), token))  # replay
        await asyncio.sleep(0.4)
        assert sent_count(ctx, "claude_code") == mark


async def test_approval_settled_on_other_end_is_reported(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx, "每次审批")
        ctx.post("claude_code", message(ctx.uid(), 'APPROVE:Bash:{"command":"ls"} go'))
        await wait(lambda: any(lab == "✅ 允许一次" for lab, _ in buttons(ctx, "claude_code")), 25)
        token = find_button(ctx, "claude_code", "允许一次")
        sess = (await sessions(ctx))[0]
        pending = (await ctx.client.get(f"/api/ai/sessions/{sess['id']}/events")).json()
        aid = _approval_id(pending)
        r = await ctx.client.post(
            f"/api/ai/sessions/{sess['id']}/approvals/{aid}", json={"decision": "deny"}
        )
        assert r.status_code == 200, r.text
        ctx.post("claude_code", callback_update(ctx.uid(), token))
        await wait(lambda: any("已由另一端处理" in t for t in sent_texts(ctx, "claude_code")), 15)


async def test_approval_refused_after_owner_revoked(tmp_path, monkeypatch):
    async with open_s5c(tmp_path, monkeypatch) as ctx:
        await ctx.ready("claude_code")
        await create_claude_session(ctx, "每次审批")
        ctx.post("claude_code", message(ctx.uid(), 'APPROVE:Bash:{"command":"ls"} go'))
        await wait(lambda: any(lab == "✅ 允许一次" for lab, _ in buttons(ctx, "claude_code")), 25)
        token = find_button(ctx, "claude_code", "允许一次")
        sess = (await sessions(ctx))[0]
        config = await ctx.app.state.config_store.read()

        def revoke(c):
            c.telegram.owner.chat_id = "8888"

        await ctx.app.state.config_store.update(config.revision, revoke)
        mark = sent_count(ctx, "claude_code")
        ctx.post("claude_code", callback_update(ctx.uid(), token))
        await asyncio.sleep(0.4)
        assert not any("已允许一次" in t for t in sent_texts(ctx, "claude_code"))
        assert sent_count(ctx, "claude_code") == mark
        state = (await ctx.client.get(f"/api/ai/sessions/{sess['id']}")).json()
        assert state["state"] == "awaiting_approval", state["state"]


def callback_update(ident, data):
    return callback(ident, data)


def _approval_id(events):
    items = events.get("items", events) if isinstance(events, dict) else events
    for item in items:
        payload = item.get("payload") or item.get("data") or {}
        if isinstance(payload, dict) and payload.get("approval_id"):
            return payload["approval_id"]
    raise AssertionError(f"no approval id in events: {events}")
