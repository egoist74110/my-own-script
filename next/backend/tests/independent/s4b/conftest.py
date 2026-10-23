"""S4-B Telegram tests reuse the S4-A isolated app and fake Bot API."""

import json
import sqlite3
import time

from tests.independent.s4a.conftest import open_telegram_app
from toolbox_backend.domain.settings import DynamicTask


def message(update_id, *, text="/help", chat=6001, user=None):
    return {
        "update_id": update_id,
        "message": {
            "date": int(time.time()),
            "text": text,
            "chat": {"id": chat, "type": "private"},
            "from": {"id": chat if user is None else user},
        },
    }


def callback(update_id, token, *, chat=6001, user=None):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": str(update_id),
            "data": token,
            "from": {"id": chat if user is None else user},
            "message": {"chat": {"id": chat, "type": "private"}},
        },
    }


async def prepare(ctx, *, owner="6001", task_id="task:s4b", command="ship"):
    config = await ctx.app.state.config_store.read()

    def save(c):
        c.telegram.owner.chat_id = owner
        c.telegram.owner.source = "bound" if owner else None
        c.tasks.items = [DynamicTask(id=task_id, tg_command=command, name="S4-B task")]

    await ctx.app.state.config_store.update(config.revision, save)
    await ctx.app.state.telegram_store.bot("123456789")
    ctx.app.state.telegram_service.bot_id = "123456789"


async def latest_markup(ctx):
    with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
        row = db.execute(
            "SELECT reply_markup_json FROM tg_outbox ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


async def buttons(ctx):
    markup = await latest_markup(ctx)
    return [button for row in (markup or {}).get("inline_keyboard", []) for button in row]


async def outbox_texts(ctx):
    with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
        return [row[0] for row in db.execute("SELECT text FROM tg_outbox ORDER BY id")]


async def tap(ctx, update_id, label, *, chat=6001):
    matches = [b for b in await buttons(ctx) if label.casefold() in b["text"].casefold()]
    assert matches, f"button containing {label!r} not found: {await buttons(ctx)!r}"
    await ctx.app.state.telegram_service.process_updates(
        [callback(update_id, matches[0]["callback_data"], chat=chat)]
    )


__all__ = [
    "callback",
    "message",
    "open_telegram_app",
    "prepare",
    "buttons",
    "outbox_texts",
    "tap",
]
