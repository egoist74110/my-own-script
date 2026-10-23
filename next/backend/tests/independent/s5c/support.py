"""Shared helpers for the independent S5-C tests (read-only views of the Telegram fakes)."""

import subprocess

from tests.s5c_helpers import OWNER, TOKENS, callback, message, wait  # noqa: F401


def bot_id(ai_id):
    return TOKENS[ai_id].split(":")[0]


def sent_texts(ctx, ai_id, chat=None):
    return ctx.bots.texts(bot_id(ai_id), chat)


def sent_count(ctx, ai_id):
    return len(ctx.bots.sent.get(int(bot_id(ai_id)), []))


def buttons(ctx, ai_id):
    """(label, callback_data) pairs of the most recent markup the bot sent."""
    markup = ctx.bots.last_markup(bot_id(ai_id))
    if not markup:
        return []
    return [(b["text"], b["callback_data"]) for row in markup["inline_keyboard"] for b in row]


def find_button(ctx, ai_id, fragment):
    matches = [data for label, data in buttons(ctx, ai_id) if fragment in label]
    assert matches, f"no button containing {fragment!r} in {buttons(ctx, ai_id)}"
    return matches[0]


def requests_to(ctx, ai_id, method):
    return [p for b, m, p in ctx.bots.requests if b == int(bot_id(ai_id)) and m == method]


async def sessions(ctx):
    response = await ctx.client.get("/api/ai/sessions")
    assert response.status_code == 200, response.text
    body = response.json()
    return body["items"] if isinstance(body, dict) else body


async def create_claude_session(ctx, permission_label="每次审批", ai_id="claude_code"):
    """Walk the Telegram wizard: menu -> new -> repo -> fresh -> permission."""
    ctx.post(ai_id, message(ctx.uid(), "/menu"))
    await wait(lambda: sent_texts(ctx, ai_id))
    for label in ("新建", "repo", "全新", permission_label):
        before = sent_count(ctx, ai_id)
        await ctx.click(ai_id, label)
        await wait(lambda b=before: sent_count(ctx, ai_id) > b)
    await wait(lambda: any("已创建会话" in t for t in sent_texts(ctx, ai_id)))
    return next(t for t in sent_texts(ctx, ai_id) if "已创建会话" in t)


def leftover_fake_cli_pids():
    out = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False
    ).stdout
    return {
        int(line.split(None, 1)[0])
        for line in out.splitlines()
        if "ai_fake" in line and line.strip()
    }


def records_of_fake(ctx):
    """Every fake CLI invocation recorded for this test (empty means no CLI was spawned)."""
    from tests.s5b_helpers import records

    return records(ctx.log)
