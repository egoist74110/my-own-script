import asyncio
import json
import sqlite3
import time

import httpx
import pytest

from tests.independent.s4a.conftest import BOT_TOKEN, MockBot, open_telegram_app
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.adapters.telegram_store import TelegramStore
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Config, DynamicTask
from toolbox_backend.domain.telegram import ACLGroup, ACLMember, acl_validity


def message(ident, chat=6001, *, un=None, user=None, text="/help", private=True, age=0):
    return {
        "update_id": ident,
        "message": {
            "date": int(time.time()) - age,
            "text": text,
            "chat": {"id": chat, "type": "private" if private else "group"},
            "from": {"id": chat if user is None else user, **({"username": un} if un else {})},
        },
    }


async def prepare(ctx, *, owner="6001"):
    config = await ctx.app.state.config_store.read()

    def save(c):
        c.telegram.owner.chat_id = owner
        c.telegram.owner.source = "bound" if owner else None

    config = await ctx.app.state.config_store.update(config.revision, save)
    await ctx.app.state.telegram_store.bot("123456789")
    ctx.app.state.telegram_service.bot_id = "123456789"
    return config


async def put_token(ctx):
    revision = (await ctx.app.state.config_store.read()).revision
    response = await ctx.client.put(
        "/api/telegram/token",
        json={
            "revision": revision,
            "token": BOT_TOKEN,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["revision"]


async def test_registered_then_crash_is_never_replayed(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service

        def crash(_):
            raise RuntimeError("simulated process death after commit")

        tg.checkpoint = crash
        with pytest.raises(RuntimeError):
            await tg.process_updates([message(101)])
        tg.checkpoint = lambda _: None
        await tg.process_updates([message(101)])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute("SELECT status FROM tg_updates WHERE update_id=101").fetchone() == (
                "received",
            )
            assert db.execute("SELECT next_offset FROM tg_bots").fetchone() == (102,)
            assert db.execute("SELECT count(*) FROM tg_outbox").fetchone() == (0,)


async def test_username_binds_once_and_cannot_transfer_or_match_a_group(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def save(c):
            c.telegram.acl_groups = [ACLGroup(id="ops", name="ops")]
            c.telegram.acl_members = [ACLMember(id="member", group_id="ops", username="@reader_1")]

        await ctx.app.state.config_store.update(config.revision, save)
        tg = ctx.app.state.telegram_service
        assert (await tg.resolve_acl(message(1, -99, un="reader_1", user=20, private=False)))[
            0
        ] == "none"
        assert (await tg.resolve_acl(message(2, 20, un="Reader_1")))[0] == "group"
        config = await ctx.app.state.config_store.read()
        assert config.telegram.acl_members[0].user_id == "20"
        assert (await tg.resolve_acl(message(3, 30, un="reader_1")))[0] == "none"
        assert (await tg.resolve_acl(message(4, 20, un="renamed_1")))[0] == "group"
        assert (await tg.resolve_acl(message(5, -99, un="renamed_1", user=20, private=False)))[
            0
        ] == "none"


async def test_detach_acl_is_one_atomic_write_and_preserves_permissions(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def save(c):
            c.tasks.items = [DynamicTask(id="task:test")]
            c.telegram.acl_groups = [
                ACLGroup(
                    id="ops", name="ops", can_run=True, can_rollback=True, task_ids=["task:test"]
                )
            ]

        config = await ctx.app.state.config_store.update(config.revision, save)
        response = await ctx.client.delete(
            "/api/tasks/task:test", params={"revision": config.revision}
        )
        assert (
            response.status_code == 409 and response.json()["detail"]["code"] == "task_referenced"
        )
        original = ctx.app.state.config_store.path.read_bytes()

        def fail(_):
            raise OSError("disk failure")

        ctx.app.state.config_store.checkpoint = fail
        response = await ctx.client.delete(
            "/api/tasks/task:test",
            params={
                "revision": config.revision,
                "detach_acl": True,
            },
        )
        assert response.status_code == 503
        assert ctx.app.state.config_store.path.read_bytes() == original
        ctx.app.state.config_store.checkpoint = lambda _: None
        response = await ctx.client.delete(
            "/api/tasks/task:test",
            params={
                "revision": config.revision,
                "detach_acl": True,
            },
        )
        assert response.status_code == 200
        updated = await ctx.app.state.config_store.read()
        group = updated.telegram.acl_groups[0]
        assert not updated.tasks.items and group.task_ids == []
        assert group.can_run and group.can_rollback
        assert updated.revision == config.revision + 1
        assert "该组已无可运行任务" in (await ctx.client.get("/api/telegram")).json()["warnings"]


@pytest.mark.parametrize("fault", ["higher", "corrupt", "symlink"])
async def test_telegram_database_fault_isolated_and_preserved(tmp_path, fault):
    directory = tmp_path / "data"
    directory.mkdir()
    db_path = directory / "telegram.sqlite3"
    if fault == "higher":
        with sqlite3.connect(db_path) as db:
            db.execute("PRAGMA user_version=99")
    elif fault == "corrupt":
        db_path.write_bytes(b"not a sqlite database")
    else:
        target = tmp_path / "outside"
        target.write_bytes(b"preserve this target")
        db_path.symlink_to(target)
    before = db_path.read_bytes()
    async with open_telegram_app(tmp_path, data_dir=directory) as ctx:
        view = await ctx.client.get("/api/telegram")
        assert view.status_code == 200 and view.json()["poller"]["state"] == "store_unavailable"
        assert (await ctx.client.get("/api/settings")).status_code == 200
        revision = await put_token(ctx)
        enable = await ctx.client.post(
            "/api/telegram/control/enable",
            json={
                "revision": revision,
                "ack_old_bot_stopped": True,
            },
        )
        assert enable.status_code == 503
    assert db_path.read_bytes() == before


async def test_migration_failure_keeps_original_and_private_snapshot(tmp_path):
    raw = Config().model_dump(by_alias=True)
    raw.pop("telegram")
    raw.update(schema_version=1, revision=3)
    raw["imported"]["telegram"] = {"control_enabled": True}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    store = ConfigStore(tmp_path)

    def fail(_):
        raise OSError("before replacement")

    store.checkpoint = fail
    with pytest.raises(SettingsError):
        await store.initialize()
    assert path.read_bytes() == before
    backups = list((tmp_path / "migrations").glob("config-v1-*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".config-*"))


def test_malformed_duplicate_and_over_limit_acl_entries_grant_nothing():
    config = Config()
    config.telegram.owner.chat_id = "1"
    config.telegram.acl_groups = [ACLGroup(id="ops", name="ops")]
    config.telegram.acl_members = [
        ACLMember(id=f"m:{i}", group_id="ops", chat_id=str(i)) for i in range(501)
    ]
    config.telegram.acl_members[0].chat_id = "same-invalid"
    config.telegram.acl_members[1].chat_id = "same-invalid"
    groups, members, warnings = acl_validity(config)
    assert len(groups) == 1
    assert len(members) == 498
    assert "m:500" not in {m.id for m in members}
    assert len(warnings) == 3
    config.telegram.acl_groups.append(ACLGroup(id="ops", name="ops"))
    assert acl_validity(config)[0:2] == ([], [])


async def test_token_import_is_explicit_read_only_and_indexed(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        missing = await ctx.client.post("/api/telegram/token/import-legacy", json={"revision": 0})
        assert missing.status_code == 404 and missing.json()["detail"]["code"] == "legacy_missing"
        ctx.legacy_credentials.set("telegram_bot_token", BOT_TOKEN)
        imported = await ctx.client.post("/api/telegram/token/import-legacy", json={"revision": 0})
        assert imported.status_code == 200
        assert ctx.legacy_credentials.get("telegram_bot_token") == BOT_TOKEN
        status = (await ctx.client.get("/api/credentials")).json()
        assert status[0]["kind"] == "telegram_bot"
        assert status[0]["state"] == "present" and status[0]["source"] == "imported"
        invalid = await ctx.client.put(
            "/api/telegram/token",
            json={
                "revision": imported.json()["revision"],
                "token": "this-is-not-a-valid-bot-token",
            },
        )
        assert invalid.status_code == 422 and "this-is-not" not in invalid.text
        revision = imported.json()["revision"]
        denied = await ctx.client.post(
            "/api/telegram/control/enable",
            json={
                "revision": revision,
                "ack_old_bot_stopped": False,
            },
        )
        assert denied.status_code == 409 and denied.json()["detail"]["code"] == "ack_required"


async def test_poll_registration_continues_while_handler_waits(tmp_path):
    bot = MockBot()
    handled = asyncio.Event()
    release = asyncio.Event()
    poll_wait = asyncio.Event()
    delivered = False

    async def response(request):
        nonlocal delivered
        if request.url.path.endswith("/getUpdates"):
            payload = json.loads(request.content)
            if payload["offset"] == -1:
                return httpx.Response(200, json={"ok": True, "result": []})
            if not delivered:
                delivered = True
                return httpx.Response(
                    200, json={"ok": True, "result": [message(1), message(2, 6002)]}
                )
            await poll_wait.wait()
        return await bot._default(request)

    bot.handler = response
    async with open_telegram_app(tmp_path, bot=bot) as ctx:
        tg = ctx.app.state.telegram_service

        async def slow(update):
            if update["update_id"] == 1:
                await release.wait()
            else:
                handled.set()
            return "handled"

        tg.handle_update = slow
        revision = await put_token(ctx)
        assert (
            await ctx.client.post(
                "/api/telegram/control/enable",
                json={
                    "revision": revision,
                    "ack_old_bot_stopped": True,
                },
            )
        ).status_code == 200
        try:
            await asyncio.wait_for(handled.wait(), timeout=1)
            assert (await ctx.app.state.telegram_store.bot("123456789"))["next_offset"] == 3
        finally:
            release.set()


async def test_baseline_conflict_can_retry_without_reenable_or_webhook_delete(tmp_path):
    bot = MockBot()
    conflict = True

    async def response(request):
        if request.url.path.endswith("/getUpdates") and conflict:
            return httpx.Response(409, json={"ok": False, "error_code": 409})
        return await bot._default(request)

    bot.handler = response
    async with open_telegram_app(tmp_path, bot=bot) as ctx:
        revision = await put_token(ctx)
        failed = await ctx.client.post(
            "/api/telegram/control/enable",
            json={
                "revision": revision,
                "ack_old_bot_stopped": True,
            },
        )
        assert failed.status_code == 502
        view = (await ctx.client.get("/api/telegram")).json()
        assert view["control"]["enabled"]
        assert view["poller"]["state"] == "conflict"
        conflict = False
        retry = await ctx.client.post(
            "/api/telegram/control/retry", json={"revision": view["revision"]}
        )
        assert retry.status_code == 200, retry.text
        assert not any(r.url.path.endswith("/deleteWebhook") for r in bot.requests)


async def test_run_origin_migration_and_atomic_creation_hide_external_identity(tmp_path):
    from toolbox_backend.adapters.config_store import stamp
    from toolbox_backend.api.task_schemas import RunResponse

    store = RunStore(tmp_path)
    await store.initialize()
    await store.close()
    with sqlite3.connect(tmp_path / "runs.sqlite3") as db:
        db.execute("ALTER TABLE runs DROP COLUMN origin_json")
        db.execute("PRAGMA user_version=1")
    await store.initialize()
    try:
        with sqlite3.connect(store.path) as db:
            assert db.execute("PRAGMA user_version").fetchone() == (2,)

        def fail(_):
            raise OSError("failed before run commit")

        store.checkpoint = fail
        args = dict(
            task_id="task:test",
            operation="sync_build_release",
            request_id="req:test",
            request_hash="hash",
            config_revision=1,
            snapshot={"id": "task:test", "name": "safe"},
            resources=[],
            deadline_at=stamp(),
            origin={
                "kind": "telegram",
                "bot_id": "123456789",
                "chat_id": "42",
                "user_id": "43",
                "username_snapshot": "@reader_1",
                "action_token": "server-action-token",
            },
        )
        with pytest.raises(OSError):
            await store.create(**args)
        assert (await store.list())["items"] == []
        store.checkpoint = lambda _: None
        run = await store.create(**args)
        assert run["origin"]["chat_id"] == "42"
        assert RunResponse.model_validate(run).model_dump()["origin"] == {"kind": "telegram"}
    finally:
        await store.close()


async def test_committed_run_events_recover_notification_gap_without_duplicates(tmp_path):
    from toolbox_backend.adapters.config_store import stamp

    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def enabled(c):
            c.telegram.control.enabled = True
            c.telegram.control.enabled_at = stamp()
            c.telegram.control.bot_id = "123456789"

        await ctx.app.state.config_store.update(config.revision, enabled)
        store = ctx.app.state.run_store
        # Simulate process death in the gap between run commit and outbox callback.
        store.on_event = None
        run = await store.create(
            task_id="task:test",
            operation="sync_build_release",
            request_id="req:recover",
            request_hash="recover",
            config_revision=1,
            snapshot={"id": "task:test", "name": "recover"},
            resources=[],
            deadline_at=stamp(),
        )
        run = await store.transition(run["run_id"], run["state_version"], "running")
        await store.transition(
            run["run_id"], run["state_version"], "failed", reason_code="local_failed"
        )
        tg = ctx.app.state.telegram_service
        await tg.recover_notifications()
        await tg.recover_notifications()
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            rows = db.execute("SELECT dedup_key,chat_id FROM tg_outbox ORDER BY id").fetchall()
        assert rows == [
            (f"run:{run['run_id']}:running", "6001"),
            (f"run:{run['run_id']}:failed", "6001"),
        ]
        config = await ctx.app.state.config_store.read()
        await ctx.app.state.config_store.update(
            config.revision, lambda c: setattr(c.telegram.control, "enabled", False)
        )
        await tg.notify_run({**run, "run_id": "disabled-run"}, "failed")
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute("SELECT count(*) FROM tg_outbox").fetchone() == (2,)


async def test_outbox_bounds_chunks_priority_and_sending_restart(tmp_path):
    store = TelegramStore(tmp_path)
    await store.initialize()
    try:
        await store.enqueue("bot", "chat", "chunked", "x" * 8001)
        with sqlite3.connect(store.path) as db:
            assert [r[0] for r in db.execute("SELECT length(text) FROM tg_outbox ORDER BY id")] == [
                4000,
                4000,
                1,
            ]
        first = await store.take("bot")
        assert first["dedup_key"] == "chunked" and first["attempts"] == 1
        await store.close()
        await store.initialize()
        with sqlite3.connect(store.path) as db:
            assert db.execute(
                "SELECT state FROM tg_outbox WHERE id=?", (first["id"],)
            ).fetchone() == ("unknown",)
        # Successful sends clear text, while an interrupted ambiguous send stays unknown.
        row = await store.take("bot")
        await store.sent(row["id"], "sent")
        with sqlite3.connect(store.path) as db:
            assert db.execute("SELECT text FROM tg_outbox WHERE id=?", (row["id"],)).fetchone() == (
                "",
            )
        for i in range(500):
            await store.enqueue("bot", "chat", f"notify:{i}", "notification", kind="notify")
        await store.enqueue("bot", "chat", "priority-reply", "reply")
        row = await store.take("bot")
        assert row["kind"] == "reply"
        with sqlite3.connect(store.path) as db:
            assert (
                db.execute("SELECT count(*) FROM tg_outbox WHERE state='pending'").fetchone()[0]
                <= 500
            )
            assert (
                db.execute("SELECT count(*) FROM tg_outbox WHERE state='dropped'").fetchone()[0]
                >= 1
            )
    finally:
        await store.close()


async def test_action_limits_expiry_and_atomic_identity_consumption(tmp_path):
    store = TelegramStore(tmp_path)
    await store.initialize()
    try:
        for i in range(18):
            await store.action("bot", "chat", "user", "menu", {"index": i})
        with sqlite3.connect(store.path) as db:
            assert db.execute("SELECT count(*) FROM tg_actions").fetchone() == (16,)
            token = db.execute(
                "SELECT token FROM tg_actions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()[0]
        assert await store.consume(token, "bot", "other-chat", "user") is None
        assert await store.consume(token, "bot", "chat", "other-user") is None
        assert await store.consume(token, "bot", "chat", "user") is not None
        assert await store.consume(token, "bot", "chat", "user") is None
        expired = await store.action("bot", "chat", "user", "menu", {}, ttl=-1)
        assert await store.consume(expired, "bot", "chat", "user") is None
        for i in range(270):
            await store.action("bot", f"chat:{i}", "user", "menu", {})
        with sqlite3.connect(store.path) as db:
            assert (
                db.execute("SELECT count(*) FROM tg_actions WHERE consumed_at IS NULL").fetchone()[
                    0
                ]
                <= 256
            )
    finally:
        await store.close()


async def test_http_cannot_spoof_origin_and_fake_routes_only_in_gated_mode(tmp_path, monkeypatch):
    async with open_telegram_app(tmp_path) as ctx:
        response = await ctx.client.post(
            "/api/tasks/task:any/runs",
            json={
                "plan_id": "00000000-0000-4000-8000-000000000000",
                "request_id": "00000000-0000-4000-8000-000000000001",
                "ack_old_app_idle": True,
                "origin": {"kind": "telegram", "chat_id": "owner"},
            },
        )
        assert response.status_code == 422
        assert (
            await ctx.client.post("/api/dev/telegram/inject", json={"update": {}})
        ).status_code == 404
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_TELEGRAM", "1")
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    with pytest.raises(ValueError):
        async with open_telegram_app(tmp_path / "denied"):
            pass
    async with open_telegram_app(tmp_path / "dev", dev=True) as ctx:
        response = await ctx.client.post("/api/dev/telegram/inject", json={"update": message(9)})
        assert response.status_code == 200
        assert (await ctx.client.get("/api/dev/telegram/sent")).json() == {"items": []}


async def test_details_only_builds_same_origin_links_and_never_sends_remote_urls(tmp_path):
    from toolbox_backend.domain.settings import Library, Project

    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def save(c):
            c.ado.libraries = [
                Library(id="lib:test", name="test", base_url="https://ado.example.test/tfs")
            ]
            c.ado.projects = [
                Project(id="proj:test", library_id="lib:test", collection="Default", project="Demo")
            ]
            c.telegram.control.enabled = True
            c.telegram.control.bot_id = "123456789"
            c.telegram.notify.include_details = True

        config = await ctx.app.state.config_store.update(config.revision, save)
        source = dict(
            project_id="proj:test",
            library_id="lib:test",
            base_url="https://ado.example.test/tfs",
            collection="Default",
            project="Demo",
        )
        run = dict(
            run_id="safe-links",
            operation="sync_build_release",
            origin={"kind": "ui"},
            task_snapshot={
                "name": "task",
                "git_flow": {"build_branch": "main"},
                "source": source,
                "targets": [],
            },
            steps=[
                {
                    "status": "succeeded",
                    "checkpoint": {
                        "build_id": "24",
                        "release_id": "25",
                        "url": "https://evil.example/secret",
                    },
                }
            ],
        )
        await ctx.app.state.telegram_service.notify_run(run, "succeeded", config)
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            text = db.execute("SELECT text FROM tg_outbox").fetchone()[0]
        assert "https://ado.example.test/tfs/Default/Demo/_build/results?buildId=24" in text
        assert "evil.example" not in text


async def test_notification_secrets_never_reach_db_wal_or_reply(tmp_path):
    from urllib.parse import quote

    from toolbox_backend.logging_setup import register_secret

    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        secret = "998877:" + "my_fake_secret_12345678901234567890"
        register_secret(secret)
        tg = ctx.app.state.telegram_service
        await tg.enqueue("6001", "secret-reply", "failure " + quote(secret, safe=""))
        await ctx.app.state.telegram_store.enqueue("123456789", "6001", "direct-secret", secret)
        for path in ctx.data_dir.glob("telegram.sqlite3*"):
            assert secret.encode() not in path.read_bytes()
            assert quote(secret, safe="").encode() not in path.read_bytes()
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute("SELECT DISTINCT error_category FROM tg_outbox").fetchall() == [
                ("redacted",)
            ]


async def test_help_menu_callbacks_use_bound_one_time_server_tokens(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        await tg.process_updates([message(501)])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            markup = db.execute("SELECT reply_markup_json FROM tg_outbox").fetchone()[0]
        assert markup is not None
        button = json.loads(markup)["inline_keyboard"][0][0]
        token = button["callback_data"]
        assert len(token) == 22 and "task:" not in token

        def callback(ident, data, chat=6001):
            return {
                "update_id": ident,
                "callback_query": {
                    "id": str(ident),
                    "data": data,
                    "from": {"id": chat},
                    "message": {"chat": {"id": chat, "type": "private"}},
                },
            }

        await tg.process_updates([callback(502, "run:task:forged"), callback(503, token, 6002)])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute("SELECT count(*) FROM tg_outbox").fetchone() == (1,)
        await tg.process_updates([callback(504, token), callback(505, token)])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            # 首次点击导航，重复点击只显示过期提示，不再次执行导航。
            assert db.execute("SELECT count(*) FROM tg_outbox").fetchone() == (3,)
            assert db.execute("SELECT text FROM tg_outbox ORDER BY id DESC LIMIT 1").fetchone() == (
                "菜单已过期，请重新 /start",
            )
            assert db.execute(
                "SELECT consumed_at FROM tg_actions WHERE token=?", (token,)
            ).fetchone()[0]


async def test_reply_dedup_isolated_for_two_bots_with_same_update_id(tmp_path):
    store = TelegramStore(tmp_path)
    await store.initialize()
    try:
        await store.enqueue("old-bot", "chat", "reply:1:0", "old reply")
        await store.enqueue("new-bot", "chat", "reply:1:0", "new reply")
        await store.enqueue("new-bot", "chat", "reply:1:0", "new reply")
        with sqlite3.connect(store.path) as db:
            rows = db.execute("SELECT bot_id,text FROM tg_outbox ORDER BY id").fetchall()
        assert rows == [("old-bot", "old reply"), ("new-bot", "new reply")]
    finally:
        await store.close()


async def test_s1_import_preserves_preexisting_telegram_credential_metadata(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "ui_settings.yaml").write_text("telegram_chat_id: '6001'\n")
    async with open_telegram_app(tmp_path) as ctx:
        await put_token(ctx)
        preview = await ctx.client.post("/api/settings/import/preview")
        response = await ctx.client.post(
            "/api/settings/import/execute",
            json={
                "fingerprint": preview.json()["fingerprint"],
            },
        )
        assert response.status_code == 200
        config = await ctx.app.state.config_store.read()
        assert config.credentials["telegram_bot_token"].kind == "telegram_bot"
        assert config.credentials["telegram_bot_token"].source == "manual"


async def test_stale_notification_snapshot_cannot_enqueue_after_disable(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)
        config = await ctx.app.state.config_store.update(
            config.revision, lambda c: setattr(c.telegram.control, "enabled", True)
        )
        await ctx.app.state.config_store.update(
            config.revision, lambda c: setattr(c.telegram.control, "enabled", False)
        )
        await ctx.app.state.telegram_service.notify_run(
            {
                "run_id": "stale",
                "origin": {"kind": "ui"},
                "operation": "deploy_only",
                "task_snapshot": {"name": "stale"},
                "steps": [],
            },
            "succeeded",
            config,
        )
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute("SELECT count(*) FROM tg_outbox").fetchone() == (0,)


async def test_non_ascii_wrong_bind_attempts_also_invalidate_code(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx, owner=None)
        tg = ctx.app.state.telegram_service
        config = await ctx.app.state.config_store.read()
        code = (await tg.bind_code(config.revision))["code"]
        for i in range(5):
            await tg.process_updates([message(1000 + i, text="/bind 错误代码")])
        await tg.process_updates([message(1006, text="/bind " + code)])
        assert (await ctx.app.state.config_store.read()).telegram.owner.chat_id is None


async def test_legacy_whitelist_has_no_new_limit_beyond_existing_body_limit(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)
        response = await ctx.client.put(
            "/api/telegram/acl/legacy-whitelist",
            json={
                "revision": config.revision,
                "legacy_whitelist": [str(i) for i in range(1, 502)],
            },
        )
        assert response.status_code == 200, response.text
        assert (await ctx.app.state.telegram_service.resolve_acl(message(1, 501)))[0] == "legacy"


async def test_invalid_legacy_acl_task_ids_do_not_break_task_deletion(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        config = await prepare(ctx)

        def save(c):
            c.tasks.items = [DynamicTask(id="task:remove")]
            c.telegram.acl_groups = [{"id": "bad", "name": "bad", "task_ids": 123}]

        config = await ctx.app.state.config_store.update(config.revision, save)
        response = await ctx.client.delete(
            "/api/tasks/task:remove", params={"revision": config.revision}
        )
        assert response.status_code == 200
        assert (await ctx.app.state.config_store.read()).telegram.acl_groups[0]["task_ids"] == 123


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/telegram"),
        ("PUT", "/api/telegram/token"),
        ("POST", "/api/telegram/token/import-legacy"),
        ("DELETE", "/api/telegram/token"),
        ("POST", "/api/telegram/control/enable"),
        ("POST", "/api/telegram/control/disable"),
        ("POST", "/api/telegram/control/retry"),
        ("POST", "/api/telegram/owner/bind-code"),
        ("DELETE", "/api/telegram/owner"),
        ("PATCH", "/api/telegram/settings"),
        ("POST", "/api/telegram/acl/groups"),
        ("PATCH", "/api/telegram/acl/groups/fake"),
        ("DELETE", "/api/telegram/acl/groups/fake"),
        ("POST", "/api/telegram/acl/members"),
        ("PATCH", "/api/telegram/acl/members/fake"),
        ("DELETE", "/api/telegram/acl/members/fake"),
        ("PUT", "/api/telegram/acl/legacy-whitelist"),
        ("POST", "/api/telegram/test-message"),
        ("GET", "/api/telegram/activity"),
    ],
)
async def test_all_telegram_routes_require_local_bearer(tmp_path, method, path):
    async with open_telegram_app(tmp_path) as ctx:
        ctx.client.headers.pop("Authorization")
        response = await ctx.client.request(method, path)
        assert response.status_code == 401
        assert not ctx.bot.requests
        assert not ctx.credentials.values


async def test_shutdown_cancels_poll_and_times_out_inflight_within_five_seconds(tmp_path):
    bot = MockBot()
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    forever = asyncio.Event()
    delivered = False

    async def response(request):
        nonlocal delivered
        if request.url.path.endswith("/getUpdates"):
            body = json.loads(request.content)
            if body["offset"] == -1:
                return httpx.Response(200, json={"ok": True, "result": []})
            if not delivered:
                delivered = True
                return httpx.Response(200, json={"ok": True, "result": [message(4)]})
            await forever.wait()
        return await bot._default(request)

    bot.handler = response
    async with open_telegram_app(tmp_path, bot=bot) as ctx:
        tg = ctx.app.state.telegram_service

        async def stuck(_):
            entered.set()
            try:
                await forever.wait()
            finally:
                cancelled.set()

        tg.handle_update = stuck
        revision = await put_token(ctx)
        assert (
            await ctx.client.post(
                "/api/telegram/control/enable",
                json={
                    "revision": revision,
                    "ack_old_bot_stopped": True,
                },
            )
        ).status_code == 200
        await asyncio.wait_for(entered.wait(), timeout=1)
        started = time.monotonic()
        await tg.close()
        assert time.monotonic() - started < 5.8
        assert cancelled.is_set()
        assert tg.client is None and tg.task is None and not tg._handlers
        assert ctx.app.state.telegram_store._db is None
        assert ctx.app.state.telegram_store._fd is None


async def test_last_bot_state_is_persisted_on_disable(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        revision = await put_token(ctx)
        response = await ctx.client.post(
            "/api/telegram/control/enable",
            json={
                "revision": revision,
                "ack_old_bot_stopped": True,
            },
        )
        assert response.status_code == 200
        response = await ctx.client.post(
            "/api/telegram/control/disable",
            json={
                "revision": response.json()["revision"],
            },
        )
        assert response.status_code == 200
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute("SELECT state FROM tg_bots").fetchone() == ("disabled",)


def test_legacy_blank_member_identities_are_not_duplicates():
    # Old app exports username-only members with chat_id "".
    config = Config.model_validate(
        {
            "telegram": {
                "acl_groups": [{"id": "ops", "name": "ops"}],
                "acl_members": [
                    {"id": "m:1", "group_id": "ops", "chat_id": "", "username": "@alice_ops"},
                    {"id": "m:2", "group_id": "ops", "chat_id": "", "username": "@bob_ops1"},
                ],
            }
        }
    )
    groups, members, warnings = acl_validity(config)
    assert [m.id for m in members] == ["m:1", "m:2"]
    assert all(m.chat_id is None for m in members)
    assert warnings == []
