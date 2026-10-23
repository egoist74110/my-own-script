"""Independent S4-B behavior regressions; no real Telegram, ADO or credentials."""

import asyncio
import secrets
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from tests.independent.s4a.conftest import BOT_TOKEN, MockBot
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Library, Project
from toolbox_backend.domain.telegram import ACLGroup, ACLMember

from .conftest import (
    buttons,
    callback,
    message,
    open_telegram_app,
    outbox_texts,
    prepare,
    tap,
)


@pytest.mark.parametrize(
    ("can_run", "expected"),
    [(False, False), (True, True)],
)
async def test_task_menu_is_visible_only_to_members_with_run_permission(
    tmp_path, can_run, expected
):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx, owner="7001")
        config = await ctx.app.state.config_store.read()

        def save(c):
            c.telegram.acl_groups = [
                ACLGroup(id="ops", name="ops", can_run=can_run, task_ids=["task:s4b"])
            ]
            c.telegram.acl_members = [ACLMember(id="m", group_id="ops", chat_id="6002")]

        await ctx.app.state.config_store.update(config.revision, save)
        await ctx.app.state.telegram_service.process_updates(
            [message(1, chat=6002, text="/help")]
        )
        labels = {button["text"] for button in await buttons(ctx)}
        assert ("任务" in labels) is expected


async def test_forged_callback_and_cross_chat_token_cannot_start_a_run(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        starts = []

        async def start(*args, **kwargs):
            starts.append((args, kwargs))
            return {"run_id": "forged-run"}

        tg.runs.start = start
        await tg.process_updates(
            [
                callback(10, secrets.token_urlsafe(16)[:22]),
                callback(11, secrets.token_urlsafe(16)[:22], chat=6002),
            ]
        )
        assert starts == []


async def test_menu_actions_are_server_tokens_and_single_use(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        preflights = []
        starts = []

        async def preflight(*args, **kwargs):
            preflights.append((args, kwargs))
            return {
                "plan_id": str(uuid.uuid4()),
                "expires_at": "2099-01-01T00:00:00+00:00",
                "revision": 1,
                "task_summary": {"id": "task:s4b", "name": "S4-B task"},
                "steps": [],
                "targets": [],
                "warnings": [],
            }

        async def start(*args, **kwargs):
            starts.append((args, kwargs))
            return {"run_id": "run-s4b"}

        tg.runs.preflight = preflight
        tg.runs.start = start
        await tg.process_updates([message(20)])
        assert all(len(button["callback_data"]) == 22 for button in await buttons(ctx))
        await tap(ctx, 21, "任务")
        await tap(ctx, 22, "S4-B task")
        await tap(ctx, 23, "构建发布")
        assert len(preflights) == 1
        assert starts == []
        confirm = next(button for button in await buttons(ctx) if "确认执行" in button["text"])
        token = confirm["callback_data"]
        assert len(token) == 22 and ":" not in token
        await tg.process_updates([callback(24, token), callback(25, token)])
        assert len(starts) == 1


async def test_non_owner_work_item_command_is_silent_and_does_not_read_ado(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        service = ctx.app.state.work_items_service
        calls = []

        async def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("non-owner reached work item service")

        service.list = forbidden
        tg = ctx.app.state.telegram_service
        await tg.process_updates([message(30, text="/wi 123", chat=6002)])
        assert calls == []


async def test_s4a_task_menu_database_failure_is_reflected_in_poller_state(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        await tg.store.baseline("123456789", 0)

        async def disk_failure(*args, **kwargs):
            raise SettingsError(
                "telegram_store_unavailable", "Telegram 数据库不可用", 503
            )

        class PollClient:
            async def request(self, method, payload):
                return [message(40)]

            async def close(self):
                return None

        tg.store.register = disk_failure
        tg.client = PollClient()
        await tg._session()
        assert tg.state == "store_unavailable"
        assert tg.last_error_category == "store_unavailable"


async def test_expired_confirmation_action_replans_without_starting(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        starts = []

        async def preflight(*args, **kwargs):
            return {
                "plan_id": str(uuid.uuid4()),
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "revision": 1,
                "task_summary": {"id": "task:s4b", "name": "S4-B task"},
                "steps": [],
                "targets": [],
                "warnings": [],
            }

        async def start(*args, **kwargs):
            starts.append((args, kwargs))
            return {"run_id": "run-should-not-start"}

        tg.runs.preflight = preflight
        tg.runs.start = start
        await tg.process_updates([message(100, text="/ship")])
        await tap(ctx, 101, "构建发布")
        confirm = next(button for button in await buttons(ctx) if "确认执行" in button["text"])
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            db.execute("UPDATE tg_actions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token=?", (confirm["callback_data"],))
        await tg.process_updates([callback(102, confirm["callback_data"])])
        assert starts == []
        assert any("计划已过期" in text for text in await outbox_texts(ctx))
        assert any(button["text"] == "重新预检" for button in await buttons(ctx))


async def test_deploy_only_requires_confirmation_and_starts_the_frozen_plan(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        plan_id = str(uuid.uuid4())
        preflights, starts = [], []

        async def preflight(*args, **kwargs):
            preflights.append((args, kwargs))
            return {
                "plan_id": plan_id,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "revision": 1,
                "task_summary": {"id": "task:s4b", "name": "S4-B task"},
                "steps": [],
                "targets": [
                    {
                        "name": "Production",
                        "definition_id": 4,
                        "release_definition_id": 5,
                        "stage_ids": [6],
                        "build_id": 42,
                        "commit": "abc123",
                    }
                ],
                "warnings": [],
            }

        async def start(*args, **kwargs):
            starts.append((args, kwargs))
            return {"run_id": "deploy-run"}

        tg.runs.preflight, tg.runs.start = preflight, start
        await tg.process_updates([message(105, text="/ship")])
        await tap(ctx, 106, "仅发布")
        assert len(preflights) == 1 and starts == []
        request = preflights[0][0][1]
        assert request.operation == "deploy_only"
        assert "精确制品" in next(text for text in await outbox_texts(ctx) if "精确制品" in text)
        await tap(ctx, 107, "确认执行")
        assert len(starts) == 1
        assert str(starts[0][0][1].plan_id) == plan_id


async def test_rollback_preflight_freezes_selected_offset_before_confirmation(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        plan_id = str(uuid.uuid4())
        preflights, starts = [], []

        async def preflight(*args, **kwargs):
            preflights.append((args, kwargs))
            return {
                "plan_id": plan_id,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "revision": 1,
                "task_summary": {"id": "task:s4b", "name": "S4-B task"},
                "steps": [],
                "targets": [
                    {
                        "name": "Production",
                        "definition_id": 4,
                        "release_definition_id": 5,
                        "stage_ids": [6],
                        "release_id": 11,
                        "created_at": "fixed",
                    }
                ],
                "warnings": [],
            }

        async def start(*args, **kwargs):
            starts.append((args, kwargs))
            return {"run_id": "rollback-run"}

        tg.runs.preflight, tg.runs.start = preflight, start
        await tg.process_updates([message(108, text="/rollback")])
        await tap(ctx, 109, "S4-B task")
        await tap(ctx, 110, "回滚偏移 3")
        assert len(preflights) == 1 and starts == []
        request = preflights[0][0][1]
        assert request.operation == "rollback" and request.rollback_offset == 3
        await tap(ctx, 111, "确认执行")
        assert len(starts) == 1
        assert str(starts[0][0][1].plan_id) == plan_id
        assert starts[0][0][1].ack_old_app_idle is True


async def test_expired_preflight_plan_never_starts_and_returns_fixed_replan(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        starts = []

        async def preflight(*args, **kwargs):
            return {
                "plan_id": str(uuid.uuid4()),
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "revision": 1,
                "task_summary": {"id": "task:s4b", "name": "S4-B task"},
                "steps": [],
                "targets": [],
                "warnings": [],
            }

        async def expired_start(*args, **kwargs):
            starts.append((args, kwargs))
            raise SettingsError("plan_expired", "private plan detail")

        tg.runs.preflight = preflight
        tg.runs.start = expired_start
        await tg.process_updates([message(110, text="/ship")])
        await tap(ctx, 111, "构建发布")
        await tap(ctx, 112, "确认执行")
        assert len(starts) == 1
        texts = await outbox_texts(ctx)
        assert any("计划已过期，请重新预检" in text for text in texts)
        assert all("private plan detail" not in text for text in texts)
        assert any(button["text"] == "重新预检" for button in await buttons(ctx))


@pytest.mark.parametrize("change", ["disabled", "deleted", "acl_revoked"])
async def test_confirmation_rechecks_task_and_acl_before_start(tmp_path, change):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx, owner="7001" if change == "acl_revoked" else "6001")
        config = await ctx.app.state.config_store.read()
        if change == "acl_revoked":
            await ctx.app.state.config_store.update(
                config.revision,
                lambda c: (
                    c.telegram.acl_groups.append(
                        ACLGroup(id="runner", name="runner", can_run=True, task_ids=["task:s4b"])
                    ),
                    c.telegram.acl_members.append(
                        ACLMember(id="member", group_id="runner", chat_id="6002")
                    ),
                ),
            )
        tg = ctx.app.state.telegram_service
        starts = []

        async def preflight(*args, **kwargs):
            return {
                "plan_id": str(uuid.uuid4()),
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "revision": 2,
                "task_summary": {"id": "task:s4b", "name": "S4-B task"},
                "steps": [],
                "targets": [],
                "warnings": [],
            }

        async def start(*args, **kwargs):
            starts.append((args, kwargs))
            return {"run_id": "unexpected-run"}

        tg.runs.preflight = preflight
        tg.runs.start = start
        chat = 6002 if change == "acl_revoked" else 6001
        await tg.process_updates([message(120, text="/ship", chat=chat)])
        await tap(ctx, 121, "构建发布", chat=chat)
        config = await ctx.app.state.config_store.read()

        def revoke(c):
            if change == "disabled":
                c.tasks.items[0].enabled = False
            elif change == "deleted":
                c.tasks.items.clear()
            else:
                c.telegram.acl_groups[0].can_run = False

        await ctx.app.state.config_store.update(config.revision, revoke)
        await tap(ctx, 122, "确认执行", chat=chat)
        assert starts == []
        texts = await outbox_texts(ctx)
        assert any(
            "操作失败" in text or "权限已变化" in text or "任务或运行已不存在" in text
            for text in texts
        )


async def test_non_owner_stop_menu_and_callback_are_limited_to_own_chat(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx, owner="7001")
        config = await ctx.app.state.config_store.read()
        await ctx.app.state.config_store.update(
            config.revision,
            lambda c: (
                c.telegram.acl_groups.append(ACLGroup(id="stopper", name="stopper", can_stop=True)),
                c.telegram.acl_members.append(
                    ACLMember(id="member", group_id="stopper", chat_id="6002")
                ),
            ),
        )
        own = {
            "run_id": "own00001",
            "task_id": "task:s4b",
            "status": "running",
            "task_snapshot": {"name": "Own run"},
            "origin": {"kind": "telegram", "chat_id": "6002"},
        }
        other = {
            "run_id": "other001",
            "task_id": "task:s4b",
            "status": "running",
            "task_snapshot": {"name": "Other run"},
            "origin": {"kind": "telegram", "chat_id": "6003"},
        }

        class FakeRunStore:
            async def call(self, fn, *args):
                return fn(*args)

            def active_snapshots(self):
                return [own, other]

            async def get(self, run_id):
                return own if run_id == own["run_id"] else other

            async def close(self):
                return None

        tg = ctx.app.state.telegram_service
        tg.runs.store = FakeRunStore()
        cancelled = []

        async def cancel(run_id, **kwargs):
            cancelled.append(run_id)
            return {"status": "cancelling"}

        tg.runs.cancel = cancel
        await tg.process_updates([message(130, text="/stop", chat=6002)])
        labels = {button["text"] for button in await buttons(ctx)}
        assert any("Own run" in label for label in labels)
        assert not any("Other run" in label for label in labels)
        await tap(ctx, 131, "Own run", chat=6002)
        assert cancelled == ["own00001"]
        assert any("停止不会回滚" in text for text in await outbox_texts(ctx))


async def test_run_origin_preserves_stop_ownership_after_backend_restart(tmp_path):
    data_dir = tmp_path / "restart-data"
    async with open_telegram_app(tmp_path, data_dir=data_dir) as first:
        await prepare(first, owner="7001")
        config = await first.app.state.config_store.read()

        def grant_stop(c):
            c.telegram.acl_groups = [ACLGroup(id="stopper", name="stopper", can_stop=True)]
            c.telegram.acl_members = [
                ACLMember(id="member", group_id="stopper", chat_id="6002")
            ]

        await first.app.state.config_store.update(config.revision, grant_stop)
        store = first.app.state.run_service.store
        run = await store.create(
            task_id="task:s4b",
            operation="sync_build_release",
            request_id=str(uuid.uuid4()),
            request_hash="restart-origin-hash",
            config_revision=(await first.app.state.config_store.read()).revision,
            snapshot={"id": "task:s4b", "name": "Restart-owned run"},
            resources=[],
            deadline_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            origin={"kind": "telegram", "bot_id": "123456789", "chat_id": "6002", "user_id": "6002"},
        )
        await store.transition(run["run_id"], run["state_version"], "running")

    async with open_telegram_app(tmp_path, data_dir=data_dir) as restarted:
        await restarted.app.state.telegram_store.bot("123456789")
        restarted.app.state.telegram_service.bot_id = "123456789"
        await restarted.app.state.telegram_service.process_updates(
            [message(170, text="/stop", chat=6002)]
        )
        labels = {button["text"] for button in await buttons(restarted)}
        own_label = next(label for label in labels if "Restart-owned run" in label)
        assert own_label
        await tap(restarted, 171, "Restart-owned run", chat=6002)
        texts = await outbox_texts(restarted)
        assert any("结果需要核实" in text for text in texts), texts


async def test_work_item_listing_paginates_eight_items_per_page(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        config = await ctx.app.state.config_store.read()

        def add_project(c):
            library = Library(id="lib:s4b", name="S4-B library", base_url="https://ado.example.test")
            project = Project(id="proj:s4b", library_id=library.id, collection="Collection", project="Project")
            c.ado.libraries.append(library)
            c.ado.projects.append(project)
            c.ado.active_project_id = project.id

        await ctx.app.state.config_store.update(config.revision, add_project)
        service = ctx.app.state.work_items_service

        async def listing(*args, **kwargs):
            return SimpleNamespace(
                items=[SimpleNamespace(id=i, title=f"Work item {i}") for i in range(1, 10)],
                truncated=False,
            )

        service.listing = listing
        tg = ctx.app.state.telegram_service
        await tg.process_updates([message(140, text="/wi")])
        await tap(ctx, 141, "Project")
        await tap(ctx, 142, "开发中")
        first_page = "\n".join(text for text in await outbox_texts(ctx) if text)
        assert "#1 Work item 1" in first_page and "#8 Work item 8" in first_page
        assert "#9 Work item 9" not in first_page
        await tap(ctx, 143, "下一页")
        second_page = next(text for text in reversed(await outbox_texts(ctx)) if text)
        assert "#9 Work item 9" in second_page
        assert "#1 Work item 1" not in second_page


async def test_work_item_full_text_applies_media_allowlist_and_ten_image_limit(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        config = await ctx.app.state.config_store.read()

        def add_project(c):
            library = Library(id="lib:s4b", name="S4-B library", base_url="https://ado.example.test")
            project = Project(id="proj:s4b", library_id=library.id, collection="Collection", project="Project")
            c.ado.libraries.append(library)
            c.ado.projects.append(project)
            c.ado.active_project_id = project.id

        await ctx.app.state.config_store.update(config.revision, add_project)
        service = ctx.app.state.work_items_service
        ids = [f"media-{i}" for i in range(12)]
        html = "".join(f'<img data-media-id="{ident}">' for ident in ids)
        field = SimpleNamespace(omitted=False, html=html)
        item = SimpleNamespace(
            id=77,
            title="Test item",
            state="Active",
            type="Bug",
            assigned_to=None,
            priority=2,
            area_path="Area",
            tags=[],
            web_url="https://ado.example.test/item/77",
            html=[("Description", field)],
            attachments=[],
        )

        async def detail(*args, **kwargs):
            return item

        async def fetch_media(ident):
            index = int(ident.rsplit("-", 1)[1])
            if index == 3:
                body = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024 + 1)
            else:
                body = b"\x89PNG\r\n\x1a\nimage" if index not in {1, 2} else b"not-an-image"
            entry = SimpleNamespace(project_id="proj:foreign" if index == 2 else "proj:s4b")
            return body, "application/octet-stream", entry

        service.detail = detail
        service.fetch_media = fetch_media
        sent = []

        class FakeTelegramClient:
            async def request(self, *args, **kwargs):
                return True

            async def upload_media(self, chat, files):
                sent.append((chat, files))

            async def close(self):
                return None

        tg = ctx.app.state.telegram_service
        tg.client = FakeTelegramClient()
        await tg.process_updates([message(150, text="/wi 77")])
        await tap(ctx, 151, "全文")
        assert len(sent) == 1
        chat, files = sent[0]
        assert chat == "6001"
        assert [name for name, _, _ in files] == [
            "image0.png",
            "image4.png",
            "image5.png",
            "image6.png",
            "image7.png",
            "image8.png",
            "image9.png",
        ]
        assert any("5 张图片未发送" in text for text in await outbox_texts(ctx))


async def test_work_item_error_uses_fixed_text_without_ado_exception_detail(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        config = await ctx.app.state.config_store.read()

        def add_project(c):
            library = Library(id="lib:s4b", name="S4-B library", base_url="https://ado.example.test")
            project = Project(id="proj:s4b", library_id=library.id, collection="Collection", project="Project")
            c.ado.libraries.append(library)
            c.ado.projects.append(project)
            c.ado.active_project_id = project.id

        await ctx.app.state.config_store.update(config.revision, add_project)
        service = ctx.app.state.work_items_service

        async def failed_listing(*args, **kwargs):
            raise SettingsError(
                "ado_request_failed",
                "leaked PAT FAKE_WORK_ITEM_SECRET and https://private.invalid/secret",
                502,
                category="network",
            )

        service.listing = failed_listing
        tg = ctx.app.state.telegram_service
        await tg.process_updates([message(160, text="/wi")])
        await tap(ctx, 161, "Project")
        await tap(ctx, 162, "开发中")
        texts = await outbox_texts(ctx)
        assert any("ADO 网络请求失败" in text for text in texts)
        assert all("FAKE_WORK_ITEM_SECRET" not in text for text in texts)
        assert all("private.invalid" not in text for text in texts)


async def test_telegram_media_uses_photo_for_one_and_media_group_for_multiple():
    from toolbox_backend.adapters.telegram_http import TelegramHTTP

    bot = MockBot()
    observed = []

    async def inspect_upload(request):
        observed.append((request.url.path.rsplit("/", 1)[-1], request.headers.get("content-type", ""), await request.aread()))
        method = observed[-1][0]
        result = [{}] if method == "sendMediaGroup" else {}
        return httpx.Response(200, json={"ok": True, "result": result})

    bot.handler = inspect_upload
    client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(bot))
    try:
        one = [("one.png", b"\x89PNG\r\n\x1a\nimage", "image/png")]
        many = one + [("two.jpg", b"\xff\xd8\xffimage", "image/jpeg")]
        await client.upload_media("6001", one)
        await client.upload_media("6001", many)
    finally:
        await client.close()
    assert [method for method, _, _ in observed] == ["sendPhoto", "sendMediaGroup"]
    assert all(content_type.startswith("multipart/form-data; boundary=") for _, content_type, _ in observed)
    assert b"chat_id" in observed[0][2] and b"one.png" in observed[0][2]
    assert b"chat_id" in observed[1][2] and b"two.jpg" in observed[1][2]


async def test_slow_telegram_handler_does_not_block_next_poll(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        await tg.store.baseline("123456789", 0)
        first_handler_started, release_handler, second_poll = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        class PollClient:
            def __init__(self):
                self.polls = 0

            async def request(self, method, payload):
                if method != "getUpdates":
                    return True
                self.polls += 1
                if self.polls == 1:
                    return [message(180)]
                second_poll.set()
                return []

            async def close(self):
                return None

        async def slow_handler(update):
            first_handler_started.set()
            await release_handler.wait()
            return "handled"

        client = PollClient()
        tg.client = client
        tg.handle_update = slow_handler
        session = asyncio.create_task(tg._session())
        try:
            await asyncio.wait_for(first_handler_started.wait(), timeout=1)
            await asyncio.wait_for(second_poll.wait(), timeout=1)
            assert client.polls >= 2
        finally:
            release_handler.set()
            session.cancel()
            await asyncio.gather(session, return_exceptions=True)


async def test_full_worker_queue_replies_busy_and_marks_update_failed(tmp_path):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        tg._work = asyncio.Queue(maxsize=64)
        for _ in range(64):
            tg._work.put_nowait(None)
        await tg.process_updates([message(190)], queued=True)
        assert any("忙，请稍后重试" in text for text in await outbox_texts(ctx))
        with sqlite3.connect(ctx.data_dir / "telegram.sqlite3") as db:
            assert db.execute("SELECT status,reason FROM tg_updates WHERE update_id=190").fetchone() == (
                "failed",
                "busy",
            )
