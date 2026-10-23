import json
import sqlite3
from types import SimpleNamespace

import pytest

from tests.independent.s4a.conftest import open_telegram_app
from tests.test_s4a_boundaries import message, prepare
from toolbox_backend.domain.settings import DynamicTask
from toolbox_backend.domain.telegram import ACLGroup, ACLMember


async def test_read_only_group_has_no_task_menu(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def save(c):
            c.telegram.acl_groups = [ACLGroup(id="readers", name="readers")]
            c.telegram.acl_members = [ACLMember(id="reader", group_id="readers", chat_id="6002")]

        await ctx.app.state.config_store.update(config.revision, save)
        await ctx.app.state.telegram_service.process_updates([message(1, 6002)])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            markup = json.loads(db.execute("SELECT reply_markup_json FROM tg_outbox").fetchone()[0])
        assert "任务" not in {b["text"] for row in markup["inline_keyboard"] for b in row}


async def test_poll_local_store_error_is_observable(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        tg = ctx.app.state.telegram_service

        async def broken(*_):
            raise OSError("local DB failure with sensitive detail")

        tg.store.bot = broken
        with pytest.raises(OSError):
            await tg._poll()
        assert tg.state in {"backoff", "store_unavailable"}
        assert "sensitive" not in (tg.last_error_category or "")


async def test_task_command_offers_modes_before_any_run(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)
        await ctx.app.state.config_store.update(
            config.revision,
            lambda c: c.tasks.items.append(
                DynamicTask(id="task:demo", name="Deploy", tg_command="deploy")
            ),
        )
        await ctx.app.state.telegram_service.process_updates([message(8, text="/deploy")])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            text, markup = db.execute("SELECT text,reply_markup_json FROM tg_outbox").fetchone()
        assert markup is not None
        buttons = [b["text"] for row in json.loads(markup)["inline_keyboard"] for b in row]
        assert "构建发布" in buttons and "仅发布" in buttons
        assert (await ctx.app.state.run_store.list())["items"] == []


async def test_task_picker_never_renders_evicted_action_tokens(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def many(c):
            c.tasks.items = [DynamicTask(id=f"task:{i}", name=f"Task {i}") for i in range(30)]

        await ctx.app.state.config_store.update(config.revision, many)
        await ctx.app.state.telegram_service.process_updates([message(9, text="/run")])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            markup = json.loads(db.execute("SELECT reply_markup_json FROM tg_outbox").fetchone()[0])
            tokens = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
            assert len(tokens) <= 16
            assert all(
                db.execute("SELECT 1 FROM tg_actions WHERE token=?", (t,)).fetchone()
                for t in tokens
            )


async def test_related_picker_keeps_every_visible_token_live(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)

        async def detail(*_):
            return SimpleNamespace(id=1, parent_id=None, child_ids=list(range(2, 32)), links=[])

        ctx.app.state.work_items_service.detail = detail
        tg = ctx.app.state.telegram_service
        await tg.dispatcher.work_items.related(message(1), {"project_id": "p", "id": 1})
        with sqlite3.connect(tg.store.path) as db:
            markup = json.loads(db.execute("SELECT reply_markup_json FROM tg_outbox").fetchone()[0])
            tokens = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
            assert len(tokens) <= 16
            assert all(
                db.execute("SELECT 1 FROM tg_actions WHERE token=?", (t,)).fetchone()
                for t in tokens
            )


async def test_owner_revoked_during_work_item_read_gets_no_reply(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service

        async def detail(*_):
            config = await ctx.app.state.config_store.read()
            await ctx.app.state.config_store.update(
                config.revision, lambda c: setattr(c.telegram.owner, "chat_id", None)
            )
            return SimpleNamespace(id=1)

        ctx.app.state.work_items_service.detail = detail
        await tg.dispatcher.work_items.callback(
            message(1), "wi_detail", {"project_id": "p", "id": 1}
        )
        with sqlite3.connect(tg.store.path) as db:
            assert db.execute("SELECT count(*) FROM tg_outbox").fetchone()[0] == 0
