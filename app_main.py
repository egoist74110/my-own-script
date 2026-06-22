from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, FluentIcon

from app_ado.ui.ado_tab import AdoReleaseTab
from app_ado.ui.ai_config_tab import AiConfigTab
from app_ado.ui.ai_dev_tab import AiDevTab
from app_ado.ui.code_config_tab import CodeConfigTab
from app_ado.ui.communication_config_tab import CommunicationConfigTab
from app_ado.ui.mcp_config_tab import McpConfigTab
from app_ado.ui.services_tab import ServicesTab
from app_ado.ui.tasks_tab import TasksTab
from app_ado.ui.work_items_tab import WorkItemsTab


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("代码工具箱")

    base = Path(__file__).resolve().parent

    # Keep icon logic simple: prefer bundled icns when launched from .app wrapper.
    icon_path = Path(os.environ.get("TOOLBOX_APP_ICON") or (base / "logo.png"))
    if icon_path.exists():
        ico = QIcon(str(icon_path))
        app.setWindowIcon(ico)

    w = MSFluentWindow()
    w.setWindowTitle("代码工具箱")
    if icon_path.exists():
        w.setWindowIcon(QIcon(str(icon_path)))

    tasks = TasksTab()
    communication = CommunicationConfigTab()
    code = CodeConfigTab()
    settings = AdoReleaseTab()
    ai = AiConfigTab()
    mcp = McpConfigTab()
    services = ServicesTab()

    # AI 开发：本地终端（多会话 PTY），纯本地、不再镜像到 TG
    from app_ado.ai_dev_session import AiDevSessionManager
    from app_ado.secrets import get_ai_bot_token
    from app_ado.store import load_ui_settings as _load_ui_settings_for_dev

    ai_dev_manager = AiDevSessionManager()

    # Claude 对话走「专属 AI 机器人」（通讯配置里给 claude_code 绑定的 Bot Token），
    # 不再借用主机器人的 token —— 这样任务通知和 AI 对话各走各的机器人，互不打架。
    _CLAUDE_AI_ID = "claude_code"

    def _ai_bot_token() -> str | None:
        try:
            return get_ai_bot_token(_CLAUDE_AI_ID)
        except Exception:
            return None

    def _dev_owner_chat_id() -> str | None:
        try:
            s = _load_ui_settings_for_dev()
            return (s.telegram_chat_id or "").strip() or None
        except Exception:
            return None

    # Claude headless 结构化会话（CC Pocket 式）：经专属 AI 机器人收发
    from app_ado.ai_headless_session import HeadlessSessionManager
    from app_ado.ai_headless_tg_bridge import AiHeadlessTgBridge

    headless_manager = HeadlessSessionManager()
    headless_bridge = AiHeadlessTgBridge(
        manager=headless_manager,
        bot_token_fn=_ai_bot_token,
        owner_chat_id_fn=_dev_owner_chat_id,
    )
    headless_bridge.start()  # 启动审批落盘监听线程

    # Codex 对话走「专属 AI 机器人」（通讯配置里给 codex 绑定的 Bot Token）。
    # Codex 规则和 Claude 不同（每轮一个 codex exec 进程、模型/思考强度/沙箱审计各自配），
    # 所以单独一套 manager + bridge，不复用 Claude 的 headless。
    from app_ado.codex_headless_session import CodexSessionManager
    from app_ado.codex_headless_tg_bridge import CodexHeadlessTgBridge

    _CODEX_AI_ID = "codex"

    def _codex_bot_token() -> str | None:
        try:
            return get_ai_bot_token(_CODEX_AI_ID)
        except Exception:
            return None

    def _codex_command() -> str:
        """codex 可执行命令：取 AI 配置里 codex profile 的启动命令，缺省 "codex"。"""
        try:
            s = _load_ui_settings_for_dev()
            for p in (s.ai.tool.profiles or []):
                if p.id == _CODEX_AI_ID and (p.command or "").strip():
                    return p.command.strip()
        except Exception:
            pass
        return "codex"

    codex_manager = CodexSessionManager()
    codex_bridge = CodexHeadlessTgBridge(
        manager=codex_manager,
        bot_token_fn=_codex_bot_token,
        owner_chat_id_fn=_dev_owner_chat_id,
        command_fn=_codex_command,
    )
    codex_bridge.start()  # 占位（codex 无审批落盘线程）

    # Antigravity CLI（agy，谷歌废弃 Gemini CLI 的继任者）对话走「专属 AI 机器人」
    # （通讯配置里给内部 id "gemini" 绑的 Bot Token）。agy --print 只回纯文本、按 cwd 归档会话，
    # 规则和 Claude/Codex 都不同，所以单独一套 manager + bridge。
    from app_ado.antigravity_headless_session import AntigravitySessionManager
    from app_ado.antigravity_headless_tg_bridge import AntigravityHeadlessTgBridge

    _AGY_AI_ID = "gemini"  # 内部 id 仍叫 gemini（保住老用户的 Bot Token 绑定），命令是 agy

    def _agy_bot_token() -> str | None:
        try:
            return get_ai_bot_token(_AGY_AI_ID)
        except Exception:
            return None

    def _agy_command() -> str:
        """agy 可执行命令：取 AI 配置里 gemini profile 的启动命令，缺省 "agy"。"""
        try:
            s = _load_ui_settings_for_dev()
            for p in (s.ai.tool.profiles or []):
                if p.id == _AGY_AI_ID and (p.command or "").strip():
                    # profile.command 可能带参数（如 "agy --dangerously-skip-permissions"），
                    # 这里只取可执行名，沙箱/审批由会话按档位自己补，避免重复/冲突。
                    return p.command.strip().split()[0]
        except Exception:
            pass
        return "agy"

    agy_manager = AntigravitySessionManager()
    agy_bridge = AntigravityHeadlessTgBridge(
        manager=agy_manager,
        bot_token_fn=_agy_bot_token,
        owner_chat_id_fn=_dev_owner_chat_id,
        command_fn=_agy_command,
    )
    agy_bridge.start()  # 占位（agy 无审批落盘线程）

    ai_dev = AiDevTab(ai_dev_manager)

    # 工单页：MCP 分析按钮要能在 AI 开发 Tab 起会话并跳过去
    work_items = WorkItemsTab(
        ai_dev_tab=ai_dev,
        on_navigate_to_ai_dev=lambda: w.switchTo(ai_dev),
    )

    # Telegram control (polling thread) - only active while app runs
    from app_ado.tg_control import TelegramController
    from app_ado.tg_work_items_bridge import WorkItemsBridge

    # 工单 MCP 分析按需路由到对应 AI 的专属机器人：claude_code → Claude 桥，codex → Codex 桥。
    wi_bridge = WorkItemsBridge(
        headless_bridge=headless_bridge,
        bridges={"claude_code": headless_bridge, "codex": codex_bridge, "gemini": agy_bridge},
    )

    # 主机器人：任务/工单/服务/MCP。不传 headless_bridge → AI 对话（/cc、cc:*、🤖 Claude 会话）
    # 不在主机器人出现。工单 MCP 分析仍可用（wi_bridge 内部持有 headless_bridge），
    # 但会话收发走专属 AI 机器人。
    tg = TelegramController(
        on_run=tasks.run_task,
        on_deploy_only=tasks.deploy_only_task,
        on_rollback=tasks.rollback_task,
        on_stop_menu=tasks.list_stoppable_tasks,
        on_stop_one=tasks.stop_one_task,
        on_status=tasks.status_text,
        wi_bridge=wi_bridge,
        headless_bridge=None,
    )
    tg.start()

    # 专属 AI 机器人：只跑 Claude 会话（mode="ai"）。token 取通讯配置里给 claude_code 绑的
    # Bot Token；没配则该轮询线程空转，不影响主机器人。
    ai_tg = TelegramController(
        on_run=tasks.run_task,
        on_deploy_only=tasks.deploy_only_task,
        on_rollback=tasks.rollback_task,
        on_stop_menu=tasks.list_stoppable_tasks,
        on_stop_one=tasks.stop_one_task,
        on_status=tasks.status_text,
        wi_bridge=None,
        headless_bridge=headless_bridge,
        token_fn=_ai_bot_token,
        mode="ai",
        name="ai",
    )
    ai_tg.start()

    # Codex 专属机器人：只跑 Codex 会话（mode="ai"，headless_bridge=codex_bridge）。
    # token 取通讯配置里给 codex 绑的 Bot Token；没配则该轮询线程空转，不影响其它机器人。
    codex_tg = TelegramController(
        on_run=tasks.run_task,
        on_deploy_only=tasks.deploy_only_task,
        on_rollback=tasks.rollback_task,
        on_stop_menu=tasks.list_stoppable_tasks,
        on_stop_one=tasks.stop_one_task,
        on_status=tasks.status_text,
        wi_bridge=None,
        headless_bridge=codex_bridge,
        token_fn=_codex_bot_token,
        mode="ai",
        name="codex_ai",
    )
    codex_tg.start()

    # Antigravity 专属机器人：只跑 agy 会话（mode="ai"，headless_bridge=agy_bridge）。
    # token 取通讯配置里给内部 id "gemini" 绑的 Bot Token；没配则该轮询线程空转。
    agy_tg = TelegramController(
        on_run=tasks.run_task,
        on_deploy_only=tasks.deploy_only_task,
        on_rollback=tasks.rollback_task,
        on_stop_menu=tasks.list_stoppable_tasks,
        on_stop_one=tasks.stop_one_task,
        on_status=tasks.status_text,
        wi_bridge=None,
        headless_bridge=agy_bridge,
        token_fn=_agy_bot_token,
        mode="ai",
        name="antigravity_ai",
    )
    agy_tg.start()

    w.addSubInterface(tasks, FluentIcon.BOOK_SHELF, "任务")
    w.addSubInterface(work_items, FluentIcon.APPLICATION, "工单")
    w.addSubInterface(services, FluentIcon.GLOBE, "服务")
    w.addSubInterface(communication, FluentIcon.CHAT, "通讯配置")
    w.addSubInterface(code, FluentIcon.CODE, "代码配置")
    w.addSubInterface(settings, FluentIcon.SETTING, "设置")
    w.addSubInterface(ai, FluentIcon.APPLICATION, "AI配置")
    w.addSubInterface(mcp, FluentIcon.DEVELOPER_TOOLS, "MCP配置")
    w.addSubInterface(ai_dev, FluentIcon.COMMAND_PROMPT, "AI开发")

    # 退出时清理：终止所有 AI 开发会话
    app.aboutToQuit.connect(lambda: (ai_dev_manager.shutdown(), ai_dev.shutdown(), headless_bridge.shutdown(), codex_bridge.shutdown(), agy_bridge.shutdown()))

    w.resize(1100, 760)
    w.show()

    # Startup update check (git): if origin/main is ahead, ASK before pulling.
    from PySide6 import QtCore, QtWidgets

    from app_ado.updater import (
        check_git_clean,
        get_remote_version,
        get_update_status,
        pip_sync,
        pull_ff_only,
        repo_root,
        restart_self,
    )
    from app_ado.ui.dialogs import show_error_dialog

    import threading

    def _apply_update(root):
        try:
            pull_ff_only(root, branch="main")
            pip_sync(root)
            QtCore.QTimer.singleShot(500, restart_self)
        except Exception as e:
            QtCore.QTimer.singleShot(0, lambda: show_error_dialog(w, "更新失败", str(e)))

    def _prompt_update(root, new_ver: str):
        ok = QtWidgets.QMessageBox.question(
            w,
            "发现新版本",
            f"发现新版本：{new_ver}\n\n是否现在更新并重启？",
        )
        if ok == QtWidgets.QMessageBox.Yes:
            threading.Thread(target=lambda: _apply_update(root), daemon=True).start()

    def check_update():
        try:
            root = repo_root()
            clean, _dirty = check_git_clean(root)
            if not clean:
                # Local changes present: never auto-update, don't nag.
                return
            st = get_update_status(root, branch="main")
            if st.behind <= 0:
                return
            try:
                new_ver = get_remote_version(root, branch="main")
            except Exception:
                new_ver = f"{st.behind} 个新提交"
            QtCore.QTimer.singleShot(0, lambda: _prompt_update(root, new_ver))
        except Exception as e:
            QtCore.QTimer.singleShot(0, lambda: show_error_dialog(w, "检查更新失败", str(e)))

    threading.Thread(target=check_update, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
