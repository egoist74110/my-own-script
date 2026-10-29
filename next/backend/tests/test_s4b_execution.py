"""Real RunService/ADO executor acceptance through Telegram, with in-memory remotes."""

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager

import httpx
import pytest

from tests.independent.s4a.conftest import BOT_TOKEN, MockBot
from tests.test_s3_git import repository as repository
from tests.test_s4a_boundaries import message
from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.adapters.fake_task_ado import FakeTaskADO
from toolbox_backend.adapters.telegram_http import TelegramHTTP
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import (
    DeployTarget,
    DynamicTask,
    GitFlow,
    Library,
    Project,
    ReleaseBranch,
)
from toolbox_backend.domain.telegram import ACLGroup, ACLMember
from toolbox_backend.settings import Settings


@asynccontextmanager
async def execution(tmp_path, *, task_git=None):
    fake, bot, credentials = FakeTaskADO(project="sample"), MockBot(), MemoryCredentials()
    credentials.set("ado_pat:lib:test", "fake-s4b-pat-never-remote")
    app = create_app(
        Settings(
            token="s4b-local-test",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=credentials,
        legacy_credentials=MemoryCredentials(),
        ado_read=AdoRead(httpx.MockTransport(fake)),
        telegram_transport=httpx.MockTransport(bot),
        task_git=task_git,
    )
    async with app.router.lifespan_context(app):

        def seed(c):
            from toolbox_backend.adapters.config_store import stamp

            c.telegram.owner.chat_id = "6001"
            c.telegram.owner.source = "bound"
            c.telegram.control.enabled = True
            c.telegram.control.enabled_at = stamp()
            c.telegram.control.bot_id = "123456789"
            c.ado.libraries = [Library(id="lib:test", name="test", base_url="https://ado.test")]
            c.ado.projects = [
                Project(id="proj:test", library_id="lib:test", collection="c", project="sample")
            ]
            c.tasks.items = [
                DynamicTask(
                    id="task:test",
                    name="Telegram task",
                    tg_command="deploy",
                    project_id="proj:test",
                    repo_id="demo-repo",
                    git_flow=GitFlow(build_branch="main"),
                    targets=[
                        DeployTarget(
                            name="target",
                            build_kind="build",
                            build_id="11",
                            release_id="11",
                            release_stage_ids=["1"],
                        )
                    ],
                )
            ]
            c.telegram.acl_groups = [
                ACLGroup(
                    id="ops",
                    name="ops",
                    can_run=True,
                    can_rollback=True,
                    can_stop=True,
                    task_ids=["task:test"],
                )
            ]
            c.telegram.acl_members = [ACLMember(id="member", group_id="ops", chat_id="6002")]

        await app.state.config_store.update(0, seed)
        tg = app.state.telegram_service
        tg.bot_id = "123456789"
        tg.client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(bot))
        await tg.store.bot(tg.bot_id)
        app.state.run_service.executor.build_interval = 0.001
        app.state.run_service.executor.release_interval = 0.001
        yield app, tg, fake, bot


def latest(app):
    with sqlite3.connect(app.state.telegram_store.path) as db:
        row = db.execute(
            "SELECT text,reply_markup_json FROM tg_outbox WHERE kind='reply' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row[0], json.loads(row[1]) if row[1] else {}


async def tap(app, tg, uid, label, *, chat=6002, token=None):
    if token is None:
        token = next(
            b["callback_data"]
            for r in latest(app)[1]["inline_keyboard"]
            for b in r
            if label in b["text"]
        )
    await tg.process_updates(
        [
            {
                "update_id": uid,
                "callback_query": {
                    "id": str(uid),
                    "data": token,
                    "from": {"id": chat},
                    "message": {"message_id": 45, "chat": {"id": chat, "type": "private"}},
                },
            }
        ]
    )
    return token


@pytest.mark.parametrize(
    "operation,label",
    [("sync_build_release", "构建并发布"), ("deploy_only", "只发布"), ("rollback", "回滚偏移 1")],
)
async def test_full_real_execution_and_duplicate_confirmation(tmp_path, operation, label):
    async with execution(tmp_path) as (app, tg, fake, bot):
        await tg.process_updates(
            [message(1, 6002, text="/rollback" if operation == "rollback" else "/deploy")]
        )
        if operation == "rollback":
            await tap(app, tg, 2, "Telegram task")
            await tap(app, tg, 20, "▶️")
        await tap(app, tg, 3, label)
        text, _ = latest(app)
        assert "确认" in text and "main" in text
        if operation != "sync_build_release":
            assert "精确制品" in text and "commit" in text
        assert (await app.state.run_store.list())["items"] == []
        token = await tap(app, tg, 4, "确认执行")
        await tap(app, tg, 5, "", token=token)
        for _ in range(200):
            rows = (await app.state.run_store.list())["items"]
            if rows and rows[0]["status"] in {"succeeded", "failed", "unknown"}:
                break
            await asyncio.sleep(0.01)
        assert len(rows) == 1 and rows[0]["status"] == "succeeded", rows
        assert rows[0]["origin"]["kind"] == "telegram"
        assert rows[0]["origin"]["chat_id"] == "6002"
        assert rows[0]["origin"]["action_token"] == token
        assert rows[0]["operation"] == operation
        for _ in range(100):
            with sqlite3.connect(tg.store.path) as db:
                notified = db.execute(
                    "SELECT chat_id FROM tg_outbox WHERE dedup_key=?",
                    (f"run:{rows[0]['run_id']}:succeeded",),
                ).fetchone()
            if notified:
                break
            await asyncio.sleep(0.01)
        assert notified == ("6002",)


async def test_cancel_button_invalidates_unconsumed_confirmation(tmp_path):
    async with execution(tmp_path) as (app, tg, _, _):
        await tg.process_updates([message(1, 6002, text="/deploy")])
        await tap(app, tg, 2, "构建并发布")
        confirm = next(
            b["callback_data"]
            for row in latest(app)[1]["inline_keyboard"]
            for b in row
            if b["text"] == "✅ 确认执行"
        )
        await tap(app, tg, 3, "取消")
        await tap(app, tg, 4, "", token=confirm)
        assert (await app.state.run_store.list())["items"] == []


async def test_confirmed_telegram_run_uses_only_temporary_bare_git(repository, tmp_path):
    adapter, local, remote, git = repository
    original = git(remote, "rev-parse", "main")
    async with execution(tmp_path, task_git=adapter) as (app, tg, fake, _):
        config = await app.state.config_store.read()

        def source(c):
            c.tasks.release_configs[0].local_repo_path = str(local)
            c.tasks.release_configs[0].branches[0] = ReleaseBranch(
                id=c.tasks.release_configs[0].branches[0].id,
                build_branch="main",
                update_branches=["main"],
                merges=[{"source": "source", "target": "main"}],
                push_branches=["main"],
            )

        handle = fake.handle

        def synced_remote(request):
            if request.url.path.endswith("/refs"):
                fake.commit = git(remote, "rev-parse", "main")
            return handle(request)

        fake.handle = synced_remote

        await app.state.config_store.update(config.revision, source)
        await tg.process_updates([message(1, 6002, text="/run deploy")])
        await tap(app, tg, 2, "构建并发布")
        assert fake.writes == []
        assert git(remote, "rev-parse", "main") == original
        await tap(app, tg, 3, "确认执行")
        # Real git plus fake ADO polling takes ~5s under load; wait on a deadline.
        for _ in range(3000):
            rows = (await app.state.run_store.list())["items"]
            if rows and rows[0]["status"] in {"succeeded", "failed", "unknown"}:
                break
            await asyncio.sleep(0.01)
        assert len(rows) == 1 and rows[0]["status"] == "succeeded", rows
        assert git(remote, "rev-parse", "main") != original
        assert git(local, "branch", "--show-current") == "main"
        assert not (local / ".git" / "index.lock").exists()
