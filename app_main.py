from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, FluentIcon

from app_ado.ui.ado_tab import AdoReleaseTab
from app_ado.ui.tasks_tab import TasksTab


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
    ado = AdoReleaseTab()

    # Telegram control (polling thread) - only active while app runs
    from app_ado.tg_control import TelegramController

    tg = TelegramController(
        on_run=tasks.run_task,
        on_deploy_only=tasks.deploy_only_task,
        on_rollback=tasks.rollback_task,
        on_stop_menu=tasks.list_stoppable_tasks,
        on_stop_one=tasks.stop_one_task,
        on_status=tasks.status_text,
    )
    tg.start()

    w.addSubInterface(tasks, FluentIcon.BOOK_SHELF, "任务")
    w.addSubInterface(ado, FluentIcon.APPLICATION, "配置")

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
