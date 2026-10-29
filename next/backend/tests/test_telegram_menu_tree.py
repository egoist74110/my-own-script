"""Telegram 分层菜单：假 Bot API 下验证导航、权限和就地编辑。"""

import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.independent.s4a.conftest import BOT_TOKEN, open_telegram_app
from tests.independent.s4b.conftest import buttons, callback, message, outbox_texts
from toolbox_backend.adapters.fake_telegram import FakeTelegram
from toolbox_backend.adapters.telegram_http import TelegramHTTP
from toolbox_backend.domain.settings import ReleaseBranch, ReleaseConfig, ReleaseTarget, RunCommand
from toolbox_backend.domain.telegram import ACLGroup, ACLMember


def release(index=0, *, count=2, sort_order=0):
    """使用可读名称，标识只用于测试种子和伪造回调。"""
    return ReleaseConfig(
        id=f"config:{index}",
        name=f"仓库{index}",
        repo_name=f"仓库{index}",
        sort_order=sort_order,
        branches=[ReleaseBranch(id=f"branch:{index}", build_branch="main")],
        targets=[
            ReleaseTarget(id=f"target:{index}", name="生产目标", release_stage_names=["生产环境"])
        ],
        commands=[
            RunCommand(
                id=f"command:{index}:{n}",
                name=f"命令{index}-{n}",
                tg_command=f"ship_{index}_{n}",
                branch_id=f"branch:{index}",
                target_ids=[f"target:{index}"],
                sort_order=n,
            )
            for n in range(count)
        ],
    )


@asynccontextmanager
async def menu_app(tmp_path, *, configs=None, group=None):
    async with open_telegram_app(tmp_path) as ctx:
        config = await ctx.app.state.config_store.read()

        def seed(c):
            c.telegram.owner.chat_id = "6001"
            c.telegram.owner.source = "bound"
            c.tasks.release_configs = configs if configs is not None else [release()]
            if group is not None:
                c.telegram.acl_groups = [group]
                c.telegram.acl_members = [ACLMember(id="member", group_id=group.id, chat_id="6002")]

        await ctx.app.state.config_store.update(config.revision, seed)
        tg = ctx.app.state.telegram_service
        tg.bot_id = "123456789"
        await tg.store.bot(tg.bot_id)
        fake = FakeTelegram()
        tg.client = TelegramHTTP(BOT_TOKEN, transport=fake.transport)
        yield SimpleNamespace(ctx=ctx, tg=tg, fake=fake)


async def labels(app):
    return [button["text"] for button in await buttons(app.ctx)]


async def text(app):
    return (await outbox_texts(app.ctx))[-1]


async def tap(app, uid, label, *, chat=6001):
    matches = [button for button in await buttons(app.ctx) if button["text"] == label]
    assert len(matches) == 1, await labels(app)
    update = callback(uid, matches[0]["callback_data"], chat=chat)
    update["callback_query"]["message"]["message_id"] = 77
    await app.tg.process_updates([update])
    return matches[0]["callback_data"]


async def assert_navigation(app, *, deep=True):
    current = await labels(app)
    assert "⬅️ 返回" in current
    if deep:
        assert "🏠 主菜单" in current


async def plan(*args, **kwargs):
    return {
        "plan_id": str(uuid.uuid4()),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "targets": [],
        "warnings": [],
    }


@pytest.mark.parametrize("command", ["/start", "/menu", "/help"])
async def test_owner_main_menu_has_only_five_entries_and_status_summary(tmp_path, command):
    async with menu_app(tmp_path) as app:
        await app.tg.process_updates([message(1, text=command)])
        assert await labels(app) == ["🚀 发布", "🛠 系统操作", "📋 工单", "🔌 服务", "🧩 MCP"]
        rendered = await text(app)
        assert "🧰 代码工具箱" in rendered
        assert "运行中 0 个" in rendered and "VPN" in rendered and "远程控制" in rendered
        assert "⬅️ 返回" not in await labels(app)


@pytest.mark.parametrize(
    "permissions,expected",
    [
        ({"can_run": True}, ["🚀 发布"]),
        ({"can_rollback": True}, ["🚀 发布", "🛠 系统操作"]),
        ({"can_stop": True}, ["🛠 系统操作"]),
        ({"can_status": True}, ["🛠 系统操作"]),
        ({}, []),
    ],
)
async def test_member_main_menu_is_permission_filtered(tmp_path, permissions, expected):
    group = ACLGroup(
        id="ops",
        name="运维",
        task_ids=["command:0:0"],
        **{
            name: permissions.get(name, False)
            for name in ("can_run", "can_rollback", "can_stop", "can_status")
        },
    )
    async with menu_app(tmp_path, group=group) as app:
        await app.tg.process_updates([message(1, text="/start", chat=6002)])
        assert await labels(app) == expected
        if not expected:
            assert "没有可用菜单" in await text(app) and "授权" in await text(app)


async def test_release_tree_confirmation_cancel_back_and_home_edit_same_panel(tmp_path):
    async with menu_app(tmp_path) as app:
        app.tg.runs.preflight = plan
        await app.tg.process_updates([message(1, text="/start")])
        await tap(app, 2, "🚀 发布")
        assert await labels(app) == ["📦 仓库0（2 个命令）", "⬅️ 返回"]
        await tap(app, 3, "📦 仓库0（2 个命令）")
        assert (await labels(app))[:2] == ["▶️ 命令0-0", "▶️ 命令0-1"]
        await assert_navigation(app)
        await tap(app, 4, "▶️ 命令0-0")
        await assert_navigation(app)
        detail = await text(app)
        assert all(value in detail for value in ("main", "生产目标", "生产环境"))
        assert {"🚀 构建并发布", "📤 只发布", "↩️ 回滚"} <= set(await labels(app))
        await tap(app, 5, "🚀 构建并发布")
        await assert_navigation(app)
        assert {"✅ 确认执行", "✖️ 取消"} <= set(await labels(app))
        confirm = next(
            b["callback_data"] for b in await buttons(app.ctx) if b["text"] == "✅ 确认执行"
        )
        await tap(app, 6, "✖️ 取消")
        assert "🚀 构建并发布" in await labels(app)
        assert (await app.tg.store.inspect_action(confirm, app.tg.bot_id, "6001", "6001"))[
            "consumed_at"
        ]
        await tap(app, 7, "⬅️ 返回")
        assert "▶️ 命令0-0" in await labels(app)
        await tap(app, 8, "⬅️ 返回")
        assert "📦 仓库0（2 个命令）" in await labels(app)
        await tap(app, 9, "⬅️ 返回")
        assert "🚀 发布" in await labels(app)
        while await app.tg.send_once():
            pass
        messages = [r for r in app.fake.sent if r["method"] in {"sendMessage", "editMessageText"}]
        assert [r["method"] for r in messages] == ["sendMessage"] + ["editMessageText"] * 8
        assert all(r["payload"]["message_id"] == 77 for r in messages[1:])


async def test_confirmation_back_and_home_have_correct_destinations(tmp_path):
    async with menu_app(tmp_path) as app:
        app.tg.runs.preflight = plan
        await app.tg.process_updates([message(1, text="/run ship_0_0")])
        await tap(app, 2, "📤 只发布")
        await tap(app, 3, "⬅️ 返回")
        assert "📤 只发布" in await labels(app)
        await tap(app, 4, "🏠 主菜单")
        assert "🚀 发布" in await labels(app) and "⬅️ 返回" not in await labels(app)


async def test_confirmation_executes_frozen_plan_once(tmp_path):
    async with menu_app(tmp_path) as app:
        app.tg.runs.preflight = plan
        starts = []

        async def start(tid, body, *, origin, authorize):
            config = await app.tg.config_store.read()
            assert authorize(config)
            starts.append((tid, body, origin))
            return {"run_id": "run-menu-confirmed"}

        app.tg.runs.start = start
        await app.tg.process_updates([message(1, text="/run ship_0_0")])
        await tap(app, 2, "📤 只发布")
        token = await tap(app, 3, "✅ 确认执行")
        await app.tg.process_updates([callback(4, token)])
        assert len(starts) == 1
        assert starts[0][0] == "command:0:0"
        assert starts[0][2]["chat_id"] == "6001"
        assert starts[0][2]["action_token"] == token
        assert "已开始" in await text(app)


async def test_confirmation_rechecks_acl_after_permission_revoked(tmp_path):
    group = ACLGroup(id="ops", name="运维", task_ids=["command:0:0"], can_run=True)
    async with menu_app(tmp_path, group=group) as app:
        app.tg.runs.preflight = plan
        starts = []

        async def start(*args, **kwargs):
            starts.append((args, kwargs))
            return {"run_id": "must-not-start"}

        app.tg.runs.start = start
        await app.tg.process_updates([message(1, text="/run ship_0_0", chat=6002)])
        await tap(app, 2, "🚀 构建并发布", chat=6002)
        token = next(
            b["callback_data"] for b in await buttons(app.ctx) if b["text"] == "✅ 确认执行"
        )
        config = await app.tg.config_store.read()

        def revoke(c):
            c.telegram.acl_groups[0].can_run = False

        await app.tg.config_store.update(config.revision, revoke)
        await app.tg.process_updates([callback(3, token, chat=6002)])
        assert starts == []
        assert "权限" in await text(app) or "不可执行" in await text(app)


async def test_config_and_command_sorting_pagination_and_page_preserving_back(tmp_path):
    configs = [release(n, count=9 if n == 8 else 1, sort_order=8 - n) for n in range(9)]
    configs.append(release(99, count=0, sort_order=-1))
    configs[8].commands.reverse()
    async with menu_app(tmp_path, configs=configs) as app:
        await app.tg.process_updates([message(1, text="/start")])
        await tap(app, 2, "🚀 发布")
        current = await labels(app)
        assert current[0] == "📦 仓库8（9 个命令）"
        assert len([x for x in current if x.startswith("📦 ")]) == 8
        assert not any("仓库99" in x for x in current)
        assert "下一页 ➡️" in current and "⬅️ 上一页" not in current
        await tap(app, 3, "下一页 ➡️")
        assert "📦 仓库0（1 个命令）" in await labels(app)
        assert "⬅️ 上一页" in await labels(app)
        await tap(app, 4, "📦 仓库0（1 个命令）")
        await tap(app, 5, "⬅️ 返回")
        assert "📦 仓库0（1 个命令）" in await labels(app)
        await tap(app, 6, "⬅️ 上一页")
        await tap(app, 7, "📦 仓库8（9 个命令）")
        assert [x for x in await labels(app) if x.startswith("▶️ ")] == [
            f"▶️ 命令8-{n}" for n in range(8)
        ]
        await tap(app, 8, "下一页 ➡️")
        await tap(app, 9, "▶️ 命令8-8")
        await tap(app, 10, "⬅️ 返回")
        assert "▶️ 命令8-8" in await labels(app) and "⬅️ 上一页" in await labels(app)


async def test_expired_menu_token_provides_home_without_executing(tmp_path):
    async with menu_app(tmp_path) as app:
        await app.tg.process_updates([message(1, text="/start")])
        token = next(b["callback_data"] for b in await buttons(app.ctx) if b["text"] == "🚀 发布")
        with sqlite3.connect(app.tg.store.path) as db:
            db.execute(
                "UPDATE tg_actions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token=?",
                (token,),
            )
        update = callback(2, token)
        update["callback_query"]["message"]["message_id"] = 77
        await app.tg.process_updates([update])
        assert "菜单已过期，请重新 /start" in await text(app)
        assert "🏠 主菜单" in await labels(app)
        await tap(app, 3, "🏠 主菜单")
        assert "🚀 发布" in await labels(app)


async def test_member_cannot_see_other_config_or_forge_command_or_operation(tmp_path):
    group = ACLGroup(
        id="ops", name="运维", task_ids=["command:0:0"], can_run=True, can_rollback=False
    )
    async with menu_app(tmp_path, configs=[release(), release(1)], group=group) as app:
        calls = []

        async def preflight(*args, **kwargs):
            calls.append((args, kwargs))
            return await plan()

        app.tg.runs.preflight = preflight
        await app.tg.process_updates([message(1, text="/start", chat=6002)])
        await tap(app, 2, "🚀 发布", chat=6002)
        assert [x for x in await labels(app) if x.startswith("📦 ")] == ["📦 仓库0（1 个命令）"]
        await tap(app, 3, "📦 仓库0（1 个命令）", chat=6002)
        assert "▶️ 命令0-1" not in await labels(app)
        await tap(app, 4, "▶️ 命令0-0", chat=6002)
        assert "↩️ 回滚" not in await labels(app)
        for uid, payload in enumerate(
            (
                {"page": "task_page", "config_id": "config:1", "number": 0},
                {"page": "task", "task_id": "command:1:0"},
                {"page": "offsets", "task_id": "command:0:0"},
                {"page": "preflight", "task_id": "command:1:0", "operation": "sync_build_release"},
                {
                    "page": "preflight",
                    "task_id": "command:0:0",
                    "operation": "rollback",
                    "offset": 1,
                },
            ),
            10,
        ):
            token = await app.tg.store.action(app.tg.bot_id, "6002", "6002", "menu", payload)
            await app.tg.process_updates([callback(uid, token, chat=6002)])
            assert "权限" in await text(app) or "不可执行" in await text(app)
        assert calls == []
        assert (await app.tg.runs.store.list())["items"] == []


async def test_system_rollback_and_stop_are_nested_and_have_back(tmp_path):
    async with menu_app(tmp_path) as app:
        app.tg.runs.preflight = plan
        await app.tg.process_updates([message(1, text="/start")])
        assert "↩️ 回滚" not in await labels(app) and "⏹ 停止运行" not in await labels(app)
        await tap(app, 2, "🛠 系统操作")
        assert set(await labels(app)) == {"📊 运行状态", "⏹ 停止运行", "↩️ 回滚", "⬅️ 返回"}
        await tap(app, 3, "↩️ 回滚")
        await assert_navigation(app)
        await tap(app, 4, "📦 仓库0（2 个命令）")
        await tap(app, 5, "▶️ 命令0-0")
        await assert_navigation(app)
        await tap(app, 6, "↩️ 回滚偏移 1")
        await assert_navigation(app)
        assert "✅ 确认执行" in await labels(app)
        await tap(app, 7, "✖️ 取消")
        assert "命令0-0" in await text(app)
        await tap(app, 8, "🏠 主菜单")
        await tap(app, 9, "🛠 系统操作")
        await tap(app, 10, "⏹ 停止运行")
        assert "没有可停止" in await text(app)
        await assert_navigation(app)
        await tap(app, 11, "⬅️ 返回")
        assert "📊 运行状态" in await labels(app)


@pytest.mark.parametrize("command", ["/run ship_0_0", "/ship_0_0"])
async def test_text_command_goes_directly_to_details(tmp_path, command):
    async with menu_app(tmp_path) as app:
        await app.tg.process_updates([message(1, text=command)])
        assert "命令0-0" in await text(app)
        assert {"🚀 构建并发布", "📤 只发布", "↩️ 回滚"} <= set(await labels(app))
        await assert_navigation(app)
        await tap(app, 2, "⬅️ 返回")
        assert "▶️ 命令0-0" in await labels(app)


@pytest.mark.parametrize("command,fragment", [("/status", "没有活动运行"), ("/stop", "没有可停止")])
async def test_status_stop_text_commands_open_system_subpage(tmp_path, command, fragment):
    async with menu_app(tmp_path) as app:
        await app.tg.process_updates([message(1, text=command)])
        assert fragment in await text(app)
        await assert_navigation(app)
        await tap(app, 2, "⬅️ 返回")
        assert "📊 运行状态" in await labels(app)


async def create_run(app, tid="command:0:0", *, chat="6001"):
    config = await app.tg.config_store.read()
    task = next(t for t in config.tasks.items if t.id == tid)
    return await app.tg.runs.store.create(
        task_id=tid,
        operation="sync_build_release",
        request_id=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
        config_revision=config.revision,
        snapshot=task.model_dump(),
        resources=[],
        deadline_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        origin={"kind": "telegram", "bot_id": app.tg.bot_id, "chat_id": chat, "user_id": chat},
    )


@pytest.mark.parametrize("status,expected", [("succeeded", "✅ 成功"), ("failed", "❌ 失败")])
async def test_detail_shows_last_result_and_relative_time(tmp_path, status, expected):
    async with menu_app(tmp_path) as app:
        run = await create_run(app)
        run = await app.tg.runs.store.transition(run["run_id"], run["state_version"], "running")
        await app.tg.runs.store.transition(run["run_id"], run["state_version"], status)
        await app.tg.process_updates([message(1, text="/run ship_0_0")])
        detail = await text(app)
        assert expected in detail and "刚刚" in detail
        assert "🚀 构建并发布" in await labels(app)
        assert run["run_id"] not in detail and "command:0:0" not in detail


async def test_active_run_replaces_actions_with_stop_and_progress(tmp_path):
    async with menu_app(tmp_path) as app:
        run = await create_run(app)
        await app.tg.process_updates([message(1, text="/run ship_0_0")])
        assert "⏳ 运行中" in await text(app)
        current = await labels(app)
        assert {"⏹ 停止这次运行", "📄 查看进度"} <= set(current)
        assert not {"🚀 构建并发布", "📤 只发布", "↩️ 回滚"} & set(current)
        await tap(app, 2, "📄 查看进度")
        await assert_navigation(app)
        assert run["run_id"] not in await text(app)
        await tap(app, 3, "⬅️ 返回")
        assert "⏹ 停止这次运行" in await labels(app)


async def test_stop_and_status_callbacks_recheck_task_scope_even_for_same_chat_origin(tmp_path):
    group = ACLGroup(
        id="ops",
        name="运维",
        task_ids=["command:0:0"],
        can_run=True,
        can_stop=True,
        can_status=True,
    )
    async with menu_app(tmp_path, group=group) as app:
        visible = await create_run(app, "command:0:0", chat="6002")
        hidden = await create_run(app, "command:0:1", chat="6002")
        await app.tg.process_updates([message(1, text="/stop", chat=6002)])
        assert "命令0-0" in await text(app) or any("命令0-0" in x for x in await labels(app))
        assert not any("命令0-1" in x for x in await labels(app))
        calls = []

        async def cancel(*args, **kwargs):
            calls.append((args, kwargs))
            return {"status": "cancelled"}

        app.tg.runs.cancel = cancel
        token = await app.tg.store.action(
            app.tg.bot_id, "6002", "6002", "stop", {"run_id": hidden["run_id"]}
        )
        await app.tg.process_updates([callback(2, token, chat=6002)])
        assert calls == []
        assert "权限" in await text(app)
        token = await app.tg.store.action(
            app.tg.bot_id, "6002", "6002", "menu", {"page": "progress", "run_id": hidden["run_id"]}
        )
        await app.tg.process_updates([callback(3, token, chat=6002)])
        assert "权限" in await text(app) or "不可执行" in await text(app)
        assert hidden["run_id"] not in await text(app)
        assert (await app.tg.runs.store.get(visible["run_id"]))["status"] == "queued"
        assert (await app.tg.runs.store.get(hidden["run_id"]))["status"] == "queued"


async def test_work_item_subpages_return_to_their_parent(tmp_path):
    from toolbox_backend.domain.settings import Library, Project

    async with menu_app(tmp_path) as app:
        store = app.ctx.app.state.config_store
        config = await store.read()

        def seed(c):
            c.ado.libraries = [Library(id="lib:menu", name="测试库", base_url="https://ado.test")]
            c.ado.projects = [
                Project(
                    id="project:menu", library_id="lib:menu", collection="c", project="测试项目"
                )
            ]

        await store.update(config.revision, seed)
        wi = app.tg.dispatcher.work_items
        item = SimpleNamespace(
            id=1,
            title="测试工单",
            state="开发中",
            type="需求",
            assigned_to="小明",
            priority=1,
            area_path="项目",
            tags=[],
            web_url="https://ado.test/item/1",
            html=[],
            attachments=[],
            parent_id=2,
            child_ids=[],
            links=[],
        )

        async def listing(*args):
            return SimpleNamespace(items=[item], truncated=False)

        async def detail(*args):
            return item

        wi.service = SimpleNamespace(listing=listing, detail=detail)
        await app.tg.process_updates([message(1, text="/wi")])
        assert await labels(app) == ["📁 测试项目", "⬅️ 返回"]
        await tap(app, 2, "📁 测试项目")
        await assert_navigation(app)
        await tap(app, 3, "📋 开发中")
        await assert_navigation(app)
        await tap(app, 4, "📋 #1 测试工单")
        await assert_navigation(app)
        await tap(app, 5, "🔗 关联项")
        await assert_navigation(app)
        await tap(app, 6, "📋 工单 #2")
        await tap(app, 7, "⬅️ 返回")
        assert "关联项" in await text(app)
        await tap(app, 8, "⬅️ 返回")
        assert "📄 全文" in await labels(app)
        await tap(app, 9, "📄 全文")
        await assert_navigation(app)
        await tap(app, 10, "⬅️ 返回")
        assert "📄 全文" in await labels(app)
        await tap(app, 11, "⬅️ 返回")
        assert "📋 #1 测试工单" in await labels(app)
        await tap(app, 12, "⬅️ 返回")
        assert "📋 开发中" in await labels(app)
        await tap(app, 13, "⬅️ 返回")
        assert "📁 测试项目" in await labels(app)
        await tap(app, 14, "⬅️ 返回")
        assert "🚀 发布" in await labels(app)


async def test_services_and_mcp_actions_keep_parent_navigation(tmp_path):
    async with menu_app(tmp_path) as app:
        app.tg.vpn = None
        service_snapshot = SimpleNamespace(
            code_server=SimpleNamespace(state="stopped", port=None),
            cloudflared=SimpleNamespace(
                global_=SimpleNamespace(state="stopped", url=None), tunnels=[]
            ),
            settings=SimpleNamespace(cloudflared=SimpleNamespace(protocol="http2")),
            network=SimpleNamespace(lan_ip=None),
        )
        mcp_snapshot = SimpleNamespace(
            ado=SimpleNamespace(allow_create_work_item=False),
            figma=SimpleNamespace(token_configured=False),
            lark=SimpleNamespace(
                state="stopped",
                port=9876,
                owner_confirmed_at=None,
                token_status=SimpleNamespace(state="missing"),
            ),
        )
        actions = []

        async def snapshot():
            return service_snapshot

        async def start(name, request):
            actions.append(name)

        async def mcp_snapshot_fn():
            return mcp_snapshot

        async def start_lark(request):
            actions.append("lark")
            return mcp_snapshot

        app.tg.services = SimpleNamespace(snapshot=snapshot, start=start)
        app.tg.mcp = SimpleNamespace(snapshot=mcp_snapshot_fn, start_lark=start_lark)
        await app.tg.process_updates([message(1, text="/services")])
        assert "⬅️ 返回" in await labels(app) and "🏠 主菜单" not in await labels(app)
        await tap(app, 2, "▶️ 启动 code-server")
        assert actions == ["code-server"]
        await tap(app, 3, "⬅️ 返回")
        assert "🚀 发布" in await labels(app)
        await tap(app, 4, "🔌 服务")
        await tap(app, 5, "▶️ 启动 全局隧道")
        await assert_navigation(app)
        await tap(app, 6, "⬅️ 返回")
        assert "▶️ 启动 code-server" in await labels(app)
        await tap(app, 7, "⬅️ 返回")
        await tap(app, 8, "🧩 MCP")
        await tap(app, 9, "▶️ 启动 Lark MCP")
        assert actions == ["code-server", "lark"]
        await tap(app, 10, "⬅️ 返回")
        assert "🧰 代码工具箱" in await text(app)


async def test_edit_failure_does_not_send_another_menu_message(tmp_path):
    import httpx

    async with menu_app(tmp_path) as app:
        await app.tg.process_updates([message(1, text="/start")])
        while await app.tg.send_once():
            pass
        await tap(app, 2, "🚀 发布")
        attempted = []

        async def reject(request):
            method = request.url.path.rsplit("/", 1)[-1]
            attempted.append(method)
            return httpx.Response(400, json={"ok": False, "description": "message is not modified"})

        await app.tg.client.close()
        app.tg.client = TelegramHTTP(BOT_TOKEN, transport=httpx.MockTransport(reject))
        while await app.tg.send_once():
            pass
        assert attempted == ["editMessageText"]
        assert len([r for r in app.fake.sent if r["method"] == "sendMessage"]) == 1
