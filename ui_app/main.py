from __future__ import annotations

import sys
from dataclasses import asdict

from PySide6 import QtCore, QtWidgets

from ui_app.logging_setup import setup_app_logger
from ui_app.task_base import DemoSleepTask, TaskLogEvent
from ui_app.widgets import NavButton, TaskCard


class Worker(QtCore.QObject):
    log_event = QtCore.Signal(dict)
    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, task: DemoSleepTask) -> None:
        super().__init__()
        self.task = task

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self.task.execute()
            self.finished.emit(self.task.status)
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("my-own-script")
        self.resize(1100, 720)

        self.logger = setup_app_logger()

        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        root_layout = QtWidgets.QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Left sidebar
        sidebar = QtWidgets.QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("background: #0b1220; color: #e5e7eb;")
        side_layout = QtWidgets.QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(8)

        title = QtWidgets.QLabel("my-own-script")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")

        self.btn_settings = NavButton("设置")
        self.btn_tasks = NavButton("任务")

        self.btn_group = QtWidgets.QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.btn_group.addButton(self.btn_settings)
        self.btn_group.addButton(self.btn_tasks)
        self.btn_tasks.setChecked(True)

        side_layout.addWidget(title)
        side_layout.addSpacing(12)
        side_layout.addWidget(self.btn_settings)
        side_layout.addWidget(self.btn_tasks)
        side_layout.addStretch(1)

        # Right content
        self.stack = QtWidgets.QStackedWidget()

        self.page_tasks = self._build_tasks_page()
        self.page_settings = self._build_settings_page()

        self.stack.addWidget(self.page_tasks)
        self.stack.addWidget(self.page_settings)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)

        self.btn_tasks.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_tasks))
        self.btn_settings.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_settings))

    def _build_tasks_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("任务")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(12)

        self.card_demo = TaskCard("Demo Task", "Simulates a publish/build run")
        self.card_demo.run_btn.clicked.connect(self._run_demo_task)

        cards.addWidget(self.card_demo)
        cards.addStretch(1)

        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Task logs will appear here...")

        layout.addWidget(header)
        layout.addLayout(cards)
        layout.addWidget(QtWidgets.QLabel("日志"))
        layout.addWidget(self.log_box, 1)
        return page

    def _build_settings_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QtWidgets.QLabel("设置")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")

        note = QtWidgets.QLabel(
            "这里是最小模板的 Settings 页。后续可以放：tasks.yaml 路径、token 状态、通知开关等。"
        )
        note.setWordWrap(True)

        layout.addWidget(header)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _append_log(self, evt: TaskLogEvent) -> None:
        self.log_box.appendPlainText(f"[{evt.ts}] {evt.level.upper()} {evt.message}")

    def _run_demo_task(self) -> None:
        self.card_demo.set_status("running")
        self.log_box.clear()

        def emit(evt: TaskLogEvent) -> None:
            # hop to UI thread
            QtCore.QMetaObject.invokeMethod(
                self,
                "_append_log_slot",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(dict, asdict(evt)),
            )

        task = DemoSleepTask(seconds=2.0, logger=self.logger, emit=emit)
        worker = Worker(task)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        worker.finished.connect(lambda status: self.card_demo.set_status(status))
        worker.failed.connect(lambda err: self.card_demo.set_status(f"failed: {err}"))
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()

    @QtCore.Slot(dict)
    def _append_log_slot(self, d: dict) -> None:
        evt = TaskLogEvent(**d)
        self._append_log(evt)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
