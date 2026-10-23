"""S4-A poller, update accounting, owner binding, and outbox route contracts."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime

import httpx
import pytest

from toolbox_backend.adapters.credentials import MemoryCredentials

from .conftest import BOT_TOKEN, MockBot


async def _configure_token(ctx):
    current = await ctx.client.get("/api/telegram")
    assert current.status_code == 200, current.text
    response = await ctx.client.put(
        "/api/telegram/token",
        json={"revision": current.json()["revision"], "token": BOT_TOKEN},
    )
    assert response.status_code == 200, response.text
    return response.json()["revision"]


async def _wait_for(predicate, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


async def _wait_state(ctx, state, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        response = await ctx.client.get("/api/telegram")
        if response.status_code == 200 and response.json()["poller"]["state"] == state:
            return True
        await asyncio.sleep(0.01)
    return False


def _update_statuses(data_dir, update_ids):
    placeholders = ",".join("?" for _ in update_ids)
    with sqlite3.connect(data_dir / "telegram.sqlite3") as db:
        return dict(
            db.execute(
                f"SELECT update_id,status FROM tg_updates WHERE bot_id=? "
                f"AND update_id IN ({placeholders})",
                ("123456789", *update_ids),
            ).fetchall()
        )


def _outbox_row(data_dir, dedup_key):
    with sqlite3.connect(data_dir / "telegram.sqlite3") as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM tg_outbox WHERE dedup_key=?", (dedup_key,)
        ).fetchone()
    return dict(row) if row is not None else None


def _outbox_rows(data_dir):
    with sqlite3.connect(data_dir / "telegram.sqlite3") as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM tg_outbox").fetchall()]


def _baseline_done(data_dir):
    try:
        with sqlite3.connect(data_dir / "telegram.sqlite3") as db:
            row = db.execute(
                "SELECT baseline_done FROM tg_bots WHERE bot_id = ?", ("123456789",)
            ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None and row[0] == 1


async def _prepare_update_injection(ctx):
    await ctx.app.state.telegram_store.bot("123456789", "test_bot")
    ctx.app.state.telegram_service.bot_id = "123456789"


def _run_row(run_id, kind, chat_id=None):
    return {
        "run_id": run_id,
        "origin": {"kind": kind, "chat_id": chat_id, "user_id": "6001"},
        "operation": "sync_build_release",
        "task_snapshot": {
            "name": "Release task",
            "git_flow": {"build_branch": "main"},
            "targets": [{"name": "Production", "enabled": True}],
        },
        "steps": [{"status": "succeeded", "checkpoint": {"build_id": "12345"}}],
        "reason_code": "git_failed",
        "stderr": "PRIVATE_STDERR_MARKER",
        "url": "https://private.example/release",
    }


def _message(update_id, chat_id, text, *, date=None, user_id=None):
    return {
        "update_id": update_id,
        "message": {
            "date": date if date is not None else int(datetime.now(UTC).timestamp()),
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id if user_id is not None else chat_id},
            "text": text,
        },
    }


async def test_none_user_does_not_auto_bind_or_receive_a_reply(tmp_path, telegram_app_factory):
    async with telegram_app_factory(tmp_path) as ctx:
        await _prepare_update_injection(ctx)
        await ctx.app.state.telegram_service.process_updates([_message(10, 6001, "/help")])

        config = await ctx.app.state.config_store.read()
        assert config.telegram.owner.chat_id is None
        assert _update_statuses(ctx.data_dir, [10]) == {10: "ignored"}
        assert _outbox_rows(ctx.data_dir) == []


async def test_owner_private_chat_identity_does_not_grant_group_access(
    tmp_path, telegram_app_factory
):
    async with telegram_app_factory(tmp_path) as ctx:
        await _prepare_update_injection(ctx)
        revision = (await ctx.app.state.config_store.read()).revision

        def bind_owner(config):
            config.telegram.owner.chat_id = "6001"
            config.telegram.owner.source = "bound"

        await ctx.app.state.config_store.update(revision, bind_owner)
        group_message = _message(11, -100001, "/help", user_id=6001)
        group_message["message"]["chat"]["type"] = "supergroup"
        await ctx.app.state.telegram_service.process_updates([group_message])
        assert _update_statuses(ctx.data_dir, [11]) == {11: "ignored"}
        assert _outbox_rows(ctx.data_dir) == []


async def test_batch_exception_does_not_block_later_updates_and_replay_is_deduplicated(
    tmp_path, telegram_app_factory
):
    async with telegram_app_factory(tmp_path) as ctx:
        await _prepare_update_injection(ctx)
        revision = (await ctx.app.state.config_store.read()).revision

        def bind_owner(config):
            config.telegram.owner.chat_id = "6001"
            config.telegram.owner.source = "bound"

        await ctx.app.state.config_store.update(revision, bind_owner)
        updates = [
            _message(20, 6001, "/help"),
            _message(21, 6001, "/help"),
            _message(22, 6001, "/help"),
        ]
        service = ctx.app.state.telegram_service
        handle_update = service.handle_update

        async def fail_middle(update):
            if update["update_id"] == 21:
                raise RuntimeError("injected handler failure")
            return await handle_update(update)

        service.handle_update = fail_middle
        await service.process_updates(updates)

        assert _update_statuses(ctx.data_dir, [20, 21, 22]) == {
            20: "handled",
            21: "failed",
            22: "handled",
        }
        assert len(_outbox_rows(ctx.data_dir)) == 2

        await service.process_updates(updates)
        assert len(_outbox_rows(ctx.data_dir)) == 2
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            next_offset = db.execute(
                "SELECT next_offset FROM tg_bots WHERE bot_id = ?", ("123456789",)
            ).fetchone()[0]
        assert next_offset == 23


async def test_initial_baseline_discards_backlog_then_disable_cancels_long_poll(
    tmp_path, telegram_app_factory
):
    bot = MockBot()
    waiting = asyncio.Event()

    async def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getUpdates":
            payload = json.loads(request.read())
            if payload.get("offset") == -1:
                return httpx.Response(200, json={"ok": True, "result": [_message(30, 6001, "/help")]})
            await waiting.wait()
            raise asyncio.CancelledError
        return await bot._default(request)

    bot.handler = handler
    async with telegram_app_factory(tmp_path, bot=bot) as ctx:
        revision = await _configure_token(ctx)
        enabled = await ctx.client.post(
            "/api/telegram/control/enable",
            json={"revision": revision, "ack_old_bot_stopped": True},
        )
        assert enabled.status_code == 200, enabled.text
        state = await ctx.client.get("/api/telegram")
        assert state.json()["control"]["enabled"] is True
        assert await _wait_for(lambda: _baseline_done(ctx.data_dir))
        assert _update_statuses(ctx.data_dir, [30]) == {30: "expired"}
        assert not any(r.url.path.endswith("/sendMessage") for r in bot.requests)

        current_revision = state.json()["revision"]
        disabled = await ctx.client.post(
            "/api/telegram/control/disable", json={"revision": current_revision}
        )
        assert disabled.status_code == 200, disabled.text
        assert await _wait_state(ctx, "disabled")


async def test_service_close_releases_http_and_database_resources(tmp_path, telegram_app_factory):
    bot = MockBot()
    long_poll = asyncio.Event()

    async def handler(request):
        if request.url.path.endswith("/getUpdates"):
            payload = json.loads(request.read())
            if payload.get("offset") == -1:
                return httpx.Response(200, json={"ok": True, "result": []})
            await long_poll.wait()
            raise asyncio.CancelledError
        return await bot._default(request)

    bot.handler = handler
    async with telegram_app_factory(tmp_path, bot=bot) as ctx:
        revision = await _configure_token(ctx)
        enabled = await ctx.client.post(
            "/api/telegram/control/enable",
            json={"revision": revision, "ack_old_bot_stopped": True},
        )
        assert enabled.status_code == 200, enabled.text
        assert await _wait_state(ctx, "polling")
        service = ctx.app.state.telegram_service
        store = ctx.app.state.telegram_store
        assert service.client is not None
        assert store._db is not None

    assert service._closing is True
    assert service.client is None
    assert service.task is None
    assert service._poll_task is None
    assert service._notification_task is None
    assert store._db is None


async def test_409_stops_polling_without_delete_webhook_and_401_sets_token_invalid(
    tmp_path, telegram_app_factory
):
    conflict_bot = MockBot()

    async def conflict_handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getUpdates":
            return httpx.Response(409, json={"ok": False, "error_code": 409, "description": "Conflict"})
        return await conflict_bot._default(request)

    conflict_bot.handler = conflict_handler
    async with telegram_app_factory(tmp_path / "conflict", bot=conflict_bot) as ctx:
        revision = await _configure_token(ctx)
        enabled = await ctx.client.post(
            "/api/telegram/control/enable",
            json={"revision": revision, "ack_old_bot_stopped": True},
        )
        assert enabled.status_code == 502, enabled.text
        assert enabled.json()["detail"]["code"] == "telegram_request_failed"
        assert enabled.json()["detail"]["category"] == "conflict"
        assert await _wait_state(ctx, "conflict")
        assert not any(r.url.path.endswith("/deleteWebhook") for r in conflict_bot.requests)

    unauthorized_bot = MockBot()

    async def unauthorized_handler(request):
        if request.url.path.endswith("/getMe"):
            return httpx.Response(
                401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
            )
        return await unauthorized_bot._default(request)

    unauthorized_bot.handler = unauthorized_handler
    async with telegram_app_factory(tmp_path / "unauthorized", bot=unauthorized_bot) as ctx:
        revision = await _configure_token(ctx)
        enabled = await ctx.client.post(
            "/api/telegram/control/enable",
            json={"revision": revision, "ack_old_bot_stopped": True},
        )
        assert enabled.status_code == 502
        state = await ctx.client.get("/api/telegram")
        assert state.json()["poller"]["state"] == "token_invalid"


async def test_webhook_requires_explicit_delete_confirmation(tmp_path, telegram_app_factory):
    bot = MockBot()

    async def handler(request):
        if request.url.path.endswith("/getWebhookInfo"):
            return httpx.Response(
                200, json={"ok": True, "result": {"url": "https://secret.example/hook"}}
            )
        return await bot._default(request)

    bot.handler = handler
    async with telegram_app_factory(tmp_path, bot=bot) as ctx:
        revision = await _configure_token(ctx)
        denied = await ctx.client.post(
            "/api/telegram/control/enable",
            json={"revision": revision, "ack_old_bot_stopped": True},
        )
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "webhook_set"
        assert "secret.example" not in denied.text
        assert not any(r.url.path.endswith("/deleteWebhook") for r in bot.requests)

        bot.handler = bot._default
        accepted = await ctx.client.post(
            "/api/telegram/control/enable",
            json={
                "revision": revision,
                "ack_old_bot_stopped": True,
                "delete_webhook": True,
            },
        )
        assert accepted.status_code == 200, accepted.text
        delete_request = next(r for r in bot.requests if r.url.path.endswith("/deleteWebhook"))
        assert json.loads(delete_request.read())["drop_pending_updates"] is False


async def test_bind_code_is_one_time_private_and_owner_is_not_auto_bound(
    tmp_path, telegram_app_factory
):
    async with telegram_app_factory(tmp_path) as ctx:
        await _prepare_update_injection(ctx)
        state = await ctx.client.get("/api/telegram")
        generated = await ctx.client.post(
            "/api/telegram/owner/bind-code",
            json={"revision": state.json()["revision"]},
        )
        assert generated.status_code == 200, generated.text
        code = generated.json()["code"]
        assert len(code) == 6 and code.isdigit()

        service = ctx.app.state.telegram_service
        wrong_code = "000000" if code != "000000" else "000001"
        for update_id in range(40, 45):
            await service.process_updates([_message(update_id, 6002, f"/bind {wrong_code}")])
        config = await ctx.app.state.config_store.read()
        assert config.telegram.owner.chat_id is None

        regenerated = await ctx.client.post(
            "/api/telegram/owner/bind-code",
            json={"revision": (await ctx.client.get("/api/telegram")).json()["revision"]},
        )
        assert regenerated.status_code == 200, regenerated.text
        code = regenerated.json()["code"]
        service._bind_expiry = 0.0
        await service.process_updates([_message(46, 6001, f"/bind {code}")])
        config = await ctx.app.state.config_store.read()
        assert config.telegram.owner.chat_id is None

        regenerated = await ctx.client.post(
            "/api/telegram/owner/bind-code",
            json={"revision": (await ctx.client.get("/api/telegram")).json()["revision"]},
        )
        assert regenerated.status_code == 200, regenerated.text
        code = regenerated.json()["code"]
        await service.process_updates([_message(45, 6001, f"/bind {code}")])
        config = await ctx.app.state.config_store.read()
        assert config.telegram.owner.chat_id == "6001"
        assert config.telegram.owner.source == "bound"


async def test_notification_routes_ui_to_owner_and_telegram_to_trigger_chat_with_detail_policy(
    tmp_path, telegram_app_factory
):
    async with telegram_app_factory(tmp_path) as ctx:
        await _prepare_update_injection(ctx)
        revision = (await ctx.app.state.config_store.read()).revision

        def configure(config):
            config.telegram.control.enabled = True
            config.telegram.control.enabled_at = "2026-10-23T00:00:00+00:00"
            config.telegram.owner.chat_id = "5001"
            config.telegram.owner.source = "bound"
            config.telegram.notify.include_details = False

        config = await ctx.app.state.config_store.update(revision, configure)
        service = ctx.app.state.telegram_service
        ui_run = _run_row("run-ui-1", "ui")
        telegram_run = _run_row("run-tg-1", "telegram", "6001")
        await service.notify_run(ui_run, "failed", config)
        await service.notify_run(ui_run, "failed", config)
        await service.notify_run(telegram_run, "failed", config)

        ui_notice = _outbox_row(ctx.data_dir, "run:run-ui-1:failed")
        tg_notice = _outbox_row(ctx.data_dir, "run:run-tg-1:failed")
        assert ui_notice["chat_id"] == "5001"
        assert tg_notice["chat_id"] == "6001"
        assert ui_notice["text"].startswith("❌ 构建发布 · Release task")
        assert "PRIVATE_STDERR_MARKER" not in ui_notice["text"]
        assert "private.example" not in ui_notice["text"]
        assert "分支：" not in ui_notice["text"]

        revision = config.revision
        config = await ctx.app.state.config_store.update(
            revision, lambda c: setattr(c.telegram.notify, "include_details", True)
        )
        detailed = _run_row("run-ui-2", "ui")
        await service.notify_run(detailed, "succeeded", config)
        detail_notice = _outbox_row(ctx.data_dir, "run:run-ui-2:succeeded")
        assert "分支：main" in detail_notice["text"]
        assert "构建号：12345" in detail_notice["text"]
        assert "PRIVATE_STDERR_MARKER" not in detail_notice["text"]
        assert "private.example" not in detail_notice["text"]
        assert sum(
            row["dedup_key"] == "run:run-ui-1:failed"
            for row in _outbox_rows(ctx.data_dir)
        ) == 1


@pytest.mark.parametrize(
    ("response_kind", "expected_state", "expected_category"),
    [
        ("rate_limit", "pending", "rate_limited"),
        ("forbidden", "failed", "http_4xx"),
        ("timeout", "unknown", "timeout"),
    ],
)
async def test_outbox_429_timeout_and_403_delivery_states(
    tmp_path, telegram_app_factory, response_kind, expected_state, expected_category
):
    bot = MockBot()
    long_poll = asyncio.Event()

    async def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "sendMessage":
            if response_kind == "rate_limit":
                return httpx.Response(
                    429,
                    json={"ok": False, "error_code": 429, "description": "slow", "parameters": {"retry_after": 60}},
                )
            if response_kind == "forbidden":
                return httpx.Response(
                    403, json={"ok": False, "error_code": 403, "description": "blocked"}
                )
            raise httpx.ReadTimeout("private Bot API URL")
        if method == "getUpdates":
            payload = json.loads(request.read())
            if payload.get("offset") == -1:
                return httpx.Response(200, json={"ok": True, "result": []})
            await long_poll.wait()
            raise asyncio.CancelledError
        return await bot._default(request)

    bot.handler = handler
    async with telegram_app_factory(tmp_path, bot=bot) as ctx:
        revision = await _configure_token(ctx)
        await ctx.app.state.telegram_store.enqueue(
            "123456789", "6001", f"notification:{response_kind}", "summary only", kind="notify"
        )
        enabled = await ctx.client.post(
            "/api/telegram/control/enable",
            json={"revision": revision, "ack_old_bot_stopped": True},
        )
        assert enabled.status_code == 200, enabled.text
        assert await _wait_for(
            lambda: (
                (row := _outbox_row(ctx.data_dir, f"notification:{response_kind}"))
                and row["state"] == expected_state
                and row["attempts"] >= 1
            )
        )
        row = _outbox_row(ctx.data_dir, f"notification:{response_kind}")
        assert row["attempts"] == 1
        assert row["error_category"] == expected_category
        if response_kind == "rate_limit":
            assert row["text"] == "summary only"
            assert row["next_attempt_at"] > row["created_at"]
        if response_kind == "forbidden":
            assert row["text"] == "summary only"
        if response_kind == "timeout":
            assert row["text"] == "summary only"


async def test_outbox_pending_429_retries_after_restart_and_clears_text_when_sent(
    tmp_path, telegram_app_factory
):
    data_dir = tmp_path / "restarted-data"
    credentials = MemoryCredentials()
    first_bot = MockBot()
    first_wait = asyncio.Event()

    async def first_handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "sendMessage":
            return httpx.Response(
                429,
                json={"ok": False, "error_code": 429, "parameters": {"retry_after": 1}},
            )
        if method == "getUpdates":
            payload = json.loads(request.read())
            if payload.get("offset") == -1:
                return httpx.Response(200, json={"ok": True, "result": []})
            await first_wait.wait()
            raise asyncio.CancelledError
        return await first_bot._default(request)

    first_bot.handler = first_handler
    async with telegram_app_factory(
        tmp_path, data_dir=data_dir, bot=first_bot, credentials=credentials
    ) as first:
        revision = await _configure_token(first)
        await first.app.state.telegram_store.enqueue(
            "123456789", "6001", "restart:notify:failed", "will retry", kind="notify"
        )
        enabled = await first.client.post(
            "/api/telegram/control/enable",
            json={"revision": revision, "ack_old_bot_stopped": True},
        )
        assert enabled.status_code == 200, enabled.text
        assert await _wait_for(
            lambda: (
                (row := _outbox_row(data_dir, "restart:notify:failed"))
                and row["state"] == "pending"
                and row["attempts"] == 1
            )
        )
        row = _outbox_row(data_dir, "restart:notify:failed")
        assert row["next_attempt_at"] > row["created_at"]

    with sqlite3.connect(data_dir / "telegram.sqlite3") as db:
        db.execute(
            "UPDATE tg_outbox SET next_attempt_at=? WHERE dedup_key=?",
            ("1970-01-01T00:00:00+00:00", "restart:notify:failed"),
        )
        db.commit()

    second_bot = MockBot()
    second_wait = asyncio.Event()

    async def second_handler(request):
        if request.url.path.endswith("/getUpdates"):
            payload = json.loads(request.read())
            if payload.get("offset") == -1:
                return httpx.Response(200, json={"ok": True, "result": []})
            await second_wait.wait()
            raise asyncio.CancelledError
        return await second_bot._default(request)

    second_bot.handler = second_handler
    async with telegram_app_factory(
        tmp_path, data_dir=data_dir, bot=second_bot, credentials=credentials
    ):
        assert await _wait_for(
            lambda: (_outbox_row(data_dir, "restart:notify:failed") or {}).get("state") == "sent"
        )
        row = _outbox_row(data_dir, "restart:notify:failed")
        assert row["attempts"] == 2
        assert row["text"] == ""
        sends = [r for r in second_bot.requests if r.url.path.endswith("/sendMessage")]
        assert len(sends) == 1
