from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, FluentIcon

from app_ado.ui.ado_tab import AdoReleaseTab
from app_ado.ui.tasks_tab import TasksTab


def main() -> None:
    app = QApplication(sys.argv)

    w = MSFluentWindow()
    w.setWindowTitle("my-own-script (QFluentWidgets)")

    tasks = TasksTab()
    ado = AdoReleaseTab()

    # Put "任务" first in the left navigation.
    w.addSubInterface(tasks, FluentIcon.BOOK_SHELF, "任务")

    # Rename ADO tab to be more intuitive.
    w.addSubInterface(ado, FluentIcon.APPLICATION, "配置")

    w.resize(1100, 760)
    w.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
