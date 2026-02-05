from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, FluentIcon

from app_ado.ui.ado_tab import AdoReleaseTab
from app_ado.ui.tasks_tab import TasksTab


def main() -> None:
    app = QApplication(sys.argv)
    # macOS menu bar app name
    app.setApplicationName("代码工具箱")

    base = Path(__file__).resolve().parent

    # Prefer icns when launched from our .app wrapper (so Dock icon matches app bundle icon)
    import os

    icon_path_str = os.environ.get("TOOLBOX_APP_ICON")
    icon_path = Path(icon_path_str) if icon_path_str else None

    if not icon_path or not icon_path.exists():
        # fallback to repo assets
        p1 = base / "logo" / "Assets.xcassets" / "AppIcon.appiconset" / "256.png"
        p2 = base / "logo" / "Assets.xcassets" / "AppIcon.appiconset" / "512.png"
        p3 = base / "logo.jpg"
        icon_path = p1 if p1.exists() else (p2 if p2.exists() else p3)

    if icon_path and icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    w = MSFluentWindow()
    w.setWindowTitle("代码工具箱")
    if icon_path.exists():
        w.setWindowIcon(QIcon(str(icon_path)))

    tasks = TasksTab()
    ado = AdoReleaseTab()

    # Telegram control (polling thread) - only active while app runs
    from app_ado.tg_control import TelegramController

    tg = TelegramController(on_run=tasks.run_task, on_stop=tasks.stop_task, on_status=tasks.status_text)
    tg.start()

    # Put "任务" first in the left navigation.
    w.addSubInterface(tasks, FluentIcon.BOOK_SHELF, "任务")

    # Rename ADO tab to be more intuitive.
    w.addSubInterface(ado, FluentIcon.APPLICATION, "配置")

    w.resize(1100, 760)
    w.show()

    # Some frameworks may override the icon after UI init; re-apply to keep Dock icon correct.
    from PySide6 import QtCore

    def reapply_icon():
        if icon_path and icon_path.exists():
            ico = QIcon(str(icon_path))
            app.setWindowIcon(ico)
            w.setWindowIcon(ico)

    QtCore.QTimer.singleShot(200, reapply_icon)
    QtCore.QTimer.singleShot(2000, reapply_icon)

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
