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
    work_items = WorkItemsTab()
    services = ServicesTab()

    # AI 开发：本地终端（多会话 PTY），纯本地、不再镜像到 TG
    from app_ado.ai_dev_session import AiDevSessionManager
    from app_ado.secrets import get_telegram_token
    from app_ado.store import load_ui_settings as _load_ui_settings_for_dev

    ai_dev_manager = AiDevSessionManager()

    def _dev_bot_token() -> str | None:
        try:
            return get_telegram_token()
        except Exception:
            return None

    def _dev_owner_chat_id() -> str | None:
        try:
            s = _load_ui_settings_for_dev()
            return (s.telegram_chat_id or "").strip() or None
        except Exception:
            return None

    # Claude headless 结构化会话（CC Pocket 式）：TG 端的 AI 开发入口
    from app_ado.ai_headless_session import HeadlessSessionManager
    from app_ado.ai_headless_tg_bridge import AiHeadlessTgBridge

    headless_manager = HeadlessSessionManager()
    headless_bridge = AiHeadlessTgBridge(
        manager=headless_manager,
        bot_token_fn=_dev_bot_token,
        owner_chat_id_fn=_dev_owner_chat_id,
    )
    headless_bridge.start()  # 启动审批落盘监听线程

    ai_dev = AiDevTab(ai_dev_manager)

    # Telegram control (polling thread) - only active while app runs
    from app_ado.tg_control import TelegramController
    from app_ado.tg_work_items_bridge import WorkItemsBridge

    wi_bridge = WorkItemsBridge()

    tg = TelegramController(
        on_run=tasks.run_task,
        on_deploy_only=tasks.deploy_only_task,
        on_rollback=tasks.rollback_task,
        on_stop_menu=tasks.list_stoppable_tasks,
        on_stop_one=tasks.stop_one_task,
        on_status=tasks.status_text,
        wi_bridge=wi_bridge,
        headless_bridge=headless_bridge,
    )
    tg.start()

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
    app.aboutToQuit.connect(lambda: (ai_dev_manager.shutdown(), ai_dev.shutdown(), headless_bridge.shutdown()))

    w.resize(1100, 760)
    w.show()

    # Auto-update on startup (GitHub): check -> pull(main) -> pip -> restart
    from PySide6 import QtCore

    from app_ado.updater import check_git_clean, get_update_status, pip_sync, pull_ff_only, repo_root, restart_self
    from app_ado.ui.dialogs import show_error_dialog

    import threading

    def do_update():
        try:
            root = repo_root()
            clean, _dirty = check_git_clean(root)
            if not clean:
                return
            st = get_update_status(root, branch="main")
            if st.behind <= 0:
                return
            pull_ff_only(root, branch="main")
            pip_sync(root)
            QtCore.QTimer.singleShot(500, restart_self)
        except Exception as e:
            QtCore.QTimer.singleShot(0, lambda: show_error_dialog(w, "自动更新失败", str(e)))

    threading.Thread(target=do_update, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
