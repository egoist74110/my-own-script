"""系统操作子菜单与历史遗留指令（/svc、/service、/cancelrollback、/cc）回归测试。"""

from pathlib import Path
from types import SimpleNamespace

from tests.independent.s4b.conftest import (
    buttons,
    callback,
    message,
    open_telegram_app,
    outbox_texts,
    prepare,
    tap,
)
from tests.test_s4b_execution import execution, latest
from tests.test_s4b_execution import tap as exec_tap
from toolbox_backend.domain.telegram import ACLGroup, ACLMember, VerifiedBot


def _button_texts(markup_buttons: list[dict]) -> list[str]:
    return [b["text"] for b in markup_buttons]


async def test_owner_system_menu_shows_all_buttons_and_navigates_to_existing_pages(tmp_path):
    """Owner 打开系统操作页，显示 回退 / 状态 / 停止 + 返回，且点击可进入对应已有页面。"""
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service

        # 主菜单进入“系统操作”
        await tg.process_updates([message(1, text="/help")])
        assert "🛠 系统操作" in _button_texts(await buttons(ctx))
        await tap(ctx, 2, "🛠 系统操作")
        texts = await outbox_texts(ctx)
        assert texts[-1] == "🛠 系统操作"
        sys_buttons = _button_texts(await buttons(ctx))
        assert sys_buttons == ["📊 运行状态", "⏹ 停止运行", "↩️ 回滚", "⬅️ 返回"]

        # 点击“回退”进入回滚任务选择页
        await tap(ctx, 3, "↩️ 回滚")
        assert (await outbox_texts(ctx))[-1] == "↩️ 回滚：请选择发布配置"
        assert any("S4-B task" in t for t in _button_texts(await buttons(ctx)))

        # 重新进入系统操作 → 点击“状态”
        await tg.process_updates([message(4, text="/menu")])
        await tap(ctx, 5, "🛠 系统操作")
        await tap(ctx, 6, "📊 运行状态")
        assert (await outbox_texts(ctx))[-1] == "当前可见范围内没有活动运行"

        # 重新进入系统操作 → 点击“停止”
        await tg.process_updates([message(7, text="/menu")])
        await tap(ctx, 8, "🛠 系统操作")
        await tap(ctx, 9, "⏹ 停止运行")
        assert "当前没有可停止的运行" in (await outbox_texts(ctx))[-1]

        # 重新进入系统操作 → 点击“⬅ 返回”回到主菜单
        await tg.process_updates([message(10, text="/menu")])
        await tap(ctx, 11, "🛠 系统操作")
        await tap(ctx, 12, "⬅️ 返回")
        assert (await outbox_texts(ctx))[-1].startswith("🧰 代码工具箱")
        assert "🛠 系统操作" in _button_texts(await buttons(ctx))


async def test_group_member_system_menu_respects_permissions_without_widening(tmp_path):
    """非 owner 组成员按 can_rollback/can_status/can_stop 显示系统操作及子按钮，不放宽权限。"""
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        config = await ctx.app.state.config_store.read()

        # 1) 仅有 can_status=True（默认）的组成员：只看到 状态 + 返回
        def set_status_only(c):
            c.telegram.acl_groups = [
                ACLGroup(
                    id="g_status",
                    name="status_only",
                    can_run=False,
                    can_rollback=False,
                    can_stop=False,
                    can_status=True,
                    task_ids=["task:s4b"],
                )
            ]
            c.telegram.acl_members = [ACLMember(id="m1", group_id="g_status", chat_id="6002")]

        await ctx.app.state.config_store.update(config.revision, set_status_only)
        await tg.process_updates([message(20, chat=6002, text="/help")])
        main_labels = _button_texts(await buttons(ctx))
        assert "🛠 系统操作" in main_labels
        assert "🔌 服务" not in main_labels
        assert "📋 工单" not in main_labels
        assert "🧩 MCP" not in main_labels

        await tap(ctx, 21, "🛠 系统操作", chat=6002)
        assert (await outbox_texts(ctx))[-1] == "🛠 系统操作"
        assert _button_texts(await buttons(ctx)) == ["📊 运行状态", "⬅️ 返回"]

        await tap(ctx, 22, "📊 运行状态", chat=6002)
        assert "没有活动运行" in (await outbox_texts(ctx))[-1]

        # 2) can_rollback=True, can_stop=True, can_status=False：只看到 回退、停止 + 返回
        config = await ctx.app.state.config_store.read()

        def set_rollback_and_stop(c):
            c.telegram.acl_groups[0].can_rollback = True
            c.telegram.acl_groups[0].can_stop = True
            c.telegram.acl_groups[0].can_status = False

        await ctx.app.state.config_store.update(config.revision, set_rollback_and_stop)
        await tg.process_updates([message(23, chat=6002, text="/help")])
        await tap(ctx, 24, "🛠 系统操作", chat=6002)
        assert _button_texts(await buttons(ctx)) == ["⏹ 停止运行", "↩️ 回滚", "⬅️ 返回"]

        # 3) 全部系统操作权限关闭时，主菜单不出现“系统操作”，且直接触发 system 令牌被忽略
        minted = await tg.store.action(tg.bot_id, "6002", "6002", "menu", {"page": "system"})
        config = await ctx.app.state.config_store.read()

        def set_no_sys_perms(c):
            c.telegram.acl_groups[0].can_run = True
            c.telegram.acl_groups[0].can_rollback = False
            c.telegram.acl_groups[0].can_stop = False
            c.telegram.acl_groups[0].can_status = False

        await ctx.app.state.config_store.update(config.revision, set_no_sys_perms)
        await tg.process_updates([message(25, chat=6002, text="/help")])
        assert "🛠 系统操作" not in _button_texts(await buttons(ctx))

        before_count = len(await outbox_texts(ctx))
        await tg.process_updates([callback(26, minted, chat=6002)])
        assert len(await outbox_texts(ctx)) == before_count


async def test_svc_and_service_commands_require_owner(tmp_path, monkeypatch):
    """/svc 与 /service 对 owner 打开服务面板，对非 owner 组成员静默忽略。"""
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service

        async def vpn_snapshot():
            return SimpleNamespace(connected=False, ip=None)

        monkeypatch.setattr(tg.vpn, "snapshot", vpn_snapshot)

        # 非 owner 发送 /svc 与 /service 均被忽略
        await tg.process_updates(
            [
                message(30, chat=6002, text="/svc"),
                message(31, chat=6002, text="/service"),
            ]
        )
        assert await outbox_texts(ctx) == []

        # owner 发送 /svc 与 /service 打开服务面板
        await tg.process_updates([message(32, chat=6001, text="/svc")])
        texts = await outbox_texts(ctx)
        assert len(texts) == 1
        assert "code-server" in texts[-1] and "全局隧道" in texts[-1]

        await tg.process_updates([message(33, chat=6001, text="/service")])
        texts = await outbox_texts(ctx)
        assert len(texts) == 2
        assert "code-server" in texts[-1] and "全局隧道" in texts[-1]


async def test_cancelrollback_with_and_without_pending_rollback(tmp_path):
    """/cancelrollback 在无待确认回滚时提示无进行中回滚；有待确认时取消并阻止旧确认执行。"""
    async with execution(tmp_path) as (app, tg, _, _):
        # 1) 当前没有待确认回滚
        await tg.process_updates([message(40, chat=6002, text="/cancelrollback")])
        text, _ = latest(app)
        assert text == "当前没有进行中的回滚"

        # 2) 发起 /rollback → 选择任务 → 选择偏移，生成 rollback_confirm 预检确认
        await tg.process_updates([message(41, chat=6002, text="/rollback")])
        await exec_tap(app, tg, 42, "Telegram task", chat=6002)
        await exec_tap(app, tg, 420, "▶️", chat=6002)
        await exec_tap(app, tg, 43, "回滚偏移 1", chat=6002)
        text, markup = latest(app)
        assert "确认" in text
        confirm_token = next(
            b["callback_data"]
            for row in markup["inline_keyboard"]
            for b in row
            if b["text"] == "✅ 确认执行"
        )

        # 发送 /cancelrollback 取消待确认回滚
        await tg.process_updates([message(44, chat=6002, text="/cancelrollback")])
        text, _ = latest(app)
        assert text == "已取消回滚"

        # 再次点击之前生成的“确认执行”按钮不会启动运行
        await exec_tap(app, tg, 45, "", chat=6002, token=confirm_token)
        assert (await app.state.run_store.list())["items"] == []

        # 紧接着再次发送 /cancelrollback 应提示没有进行中的回滚
        await tg.process_updates([message(46, chat=6002, text="/cancelrollback")])
        text, _ = latest(app)
        assert text == "当前没有进行中的回滚"


async def test_cc_command_when_disabled_and_enabled(tmp_path):
    """/cc 在未启用时提示桌面端开启路径，在已启用且有 username 时返回 @username 与 t.me 链接。"""
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service

        # 1) 默认未启用 Claude Code 专属机器人
        await tg.process_updates([message(50, chat=6001, text="/cc")])
        reply_disabled = (await outbox_texts(ctx))[-1]
        assert "尚未迁移" not in reply_disabled
        assert "设置 → Telegram → AI 专属机器人" in reply_disabled
        assert "Claude Code" in reply_disabled

        # 2) 启用 Claude Code 专属机器人并配置 username
        config = await ctx.app.state.config_store.read()

        def enable_claude_bot(c):
            c.ai.bots.claude_code.enabled = True
            c.ai.bots.claude_code.username = "my_claude_code_bot"
            c.ai.bots.claude_code.verified_bot = VerifiedBot(
                id="998877",
                username="my_claude_code_bot",
                first_name="ClaudeBot",
                verified_at="2026-10-28T00:00:00Z",
            )

        await ctx.app.state.config_store.update(config.revision, enable_claude_bot)
        await tg.process_updates([message(51, chat=6001, text="/cc")])
        reply_enabled = (await outbox_texts(ctx))[-1]
        assert "尚未迁移" not in reply_enabled
        assert "@my_claude_code_bot" in reply_enabled
        assert "https://t.me/my_claude_code_bot" in reply_enabled


def test_no_unmigrated_stubs_remain_in_telegram_sources():
    """静态检查：backend 的 telegram 相关模块中不再存在“尚未迁移/未迁移”桩文案。"""
    src_root = Path(__file__).resolve().parents[1] / "src" / "toolbox_backend"
    targets = [
        *src_root.glob("services/telegram*.py"),
        *src_root.glob("adapters/telegram*.py"),
    ]
    assert targets, "未找到 telegram 源码文件"
    for path in targets:
        content = path.read_text(encoding="utf-8")
        assert "尚未迁移" not in content, f"{path.name} 仍包含 '尚未迁移'"
        assert "未迁移" not in content, f"{path.name} 仍包含 '未迁移'"
