from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, FluentIcon

from app_ado.ui.ado_tab import AdoReleaseTab
from app_ado.ui.tasks_tab import TasksTab


def main() -> None:
    app = QApplication(sys.argv)
    # macOS menu bar app name
    app.setApplicationName("代码工具箱")

    w = MSFluentWindow()
    w.setWindowTitle("代码工具箱")

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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
