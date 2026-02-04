from __future__ import annotations

import sys
from dataclasses import asdict

from PySide6 import QtCore, QtWidgets

from ui_app.logging_setup import setup_app_logger
from ui_app.task_base import DemoSleepTask, TaskLogEvent
from ui_app.widgets import NavButton, TaskRowCard
from ui_app.settings_store import load_ui_settings, save_ui_settings, UiSettings
from ui_app.dialogs import AddRepoDialog


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
        self.resize(1180, 760)

        self.logger = setup_app_logger()
        self.ui_settings: UiSettings = load_ui_settings()
        self._apply_style()

    def _apply_style(self) -> None:
        # minimal dark theme + rounded cards
        self.setStyleSheet(
            """
            #Root { background: #111315; }
            #Sidebar { background: #0c111b; }
            #SidebarTitle { color: #e5e7eb; font-size: 16px; font-weight: 700; padding: 6px 6px; }

            QPushButton#NavButton {
              text-align: left;
              padding: 10px 10px;
              border-radius: 10px;
              color: #cbd5e1;
              background: transparent;
              border: 1px solid transparent;
            }
            QPushButton#NavButton:hover { background: rgba(255,255,255,0.06); }
            QPushButton#NavButton:checked {
              background: rgba(56,189,248,0.10);
              border: 1px solid rgba(56,189,248,0.20);
              color: #e5e7eb;
            }

            #Stack { background: #111315; }
            QLabel#PageHeader { color: #e5e7eb; font-size: 20px; font-weight: 700; }
            QLabel#Muted { color: #94a3b8; }

            QScrollArea#TaskScroll { border: none; background: transparent; }
            QWidget#TaskList { background: transparent; }

            QFrame#TaskRowCard {
              background: #1b1f24;
              border: 1px solid rgba(255,255,255,0.06);
              border-radius: 14px;
            }
            QFrame#TaskRowCard:hover { border: 1px solid rgba(56,189,248,0.22); }

            QFrame#RepoCard {
              background: #15181d;
              border: 1px solid rgba(255,255,255,0.06);
              border-radius: 14px;
            }
            QFrame#RepoCard QLabel { color: #e5e7eb; }
            QLabel#TaskTitle { color: #e5e7eb; font-size: 15px; font-weight: 650; }
            QLabel#TaskSubtitle { color: #94a3b8; }
            QLabel#TaskStatus { color: #cbd5e1; }

            QPushButton#PrimaryButton {
              background: #2a313a;
              color: #e5e7eb;
              padding: 9px 16px;
              border-radius: 12px;
              border: 1px solid rgba(255,255,255,0.10);
            }
            QPushButton#PrimaryButton:hover { background: #334155; }
            QPushButton#PrimaryButton:pressed { background: #1f2937; }

            QToolButton#MenuButton {
              background: transparent;
              color: #cbd5e1;
              border-radius: 10px;
              padding: 6px 10px;
              border: 1px solid rgba(255,255,255,0.10);
            }
            QToolButton#MenuButton:hover { background: rgba(255,255,255,0.06); }

            QTabWidget::pane {
              border: 1px solid rgba(255,255,255,0.06);
              border-radius: 12px;
              top: -1px;
              background: #0f1115;
            }
            QTabBar::tab {
              background: #15181d;
              color: #94a3b8;
              padding: 8px 12px;
              border-top-left-radius: 10px;
              border-top-right-radius: 10px;
              margin-right: 6px;
            }
            QTabBar::tab:selected { color: #e5e7eb; background: #0f1115; }

            QPlainTextEdit#TaskLogBox, QPlainTextEdit#ScriptLogBox {
              background: #0f1115;
              color: #e5e7eb;
              border: none;
              padding: 10px;
            }
            """
        )

        root = QtWidgets.QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        root_layout = QtWidgets.QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Left sidebar
        sidebar = QtWidgets.QFrame()
        sidebar.setFixedWidth(230)
        sidebar.setObjectName("Sidebar")
        side_layout = QtWidgets.QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        title = QtWidgets.QLabel("my-own-script")
        title.setObjectName("SidebarTitle")

        self.btn_tasks = NavButton("任务")
        self.btn_settings = NavButton("设置")

        self.btn_group = QtWidgets.QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.btn_group.addButton(self.btn_tasks)
        self.btn_group.addButton(self.btn_settings)
        self.btn_tasks.setChecked(True)

        side_layout.addWidget(title)
        side_layout.addSpacing(10)
        side_layout.addWidget(self.btn_tasks)
        side_layout.addWidget(self.btn_settings)
        side_layout.addStretch(1)

        # Right content
        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("Stack")

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
        page.setObjectName("PageTasks")
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QtWidgets.QLabel("任务")
        header.setObjectName("PageHeader")

        # scroll area for cards
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("TaskScroll")

        container = QtWidgets.QWidget()
        container.setObjectName("TaskList")
        v = QtWidgets.QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        self.card_demo_1 = TaskRowCard(
            "自动发布（Demo）",
            "模拟一次 publish / build 的执行与日志输出。",
        )
        self.card_demo_1.start_clicked.connect(self._run_demo_task)
        self.card_demo_1.view_task_log.connect(lambda: self._show_logs("task"))
        self.card_demo_1.view_script_log.connect(lambda: self._show_logs("script"))

        self.card_demo_2 = TaskRowCard(
            "同步状态（Demo）",
            "模拟从 storage 读取 job 状态（目前只是 UI demo）。",
        )
        self.card_demo_2.start_clicked.connect(
            lambda: self._append_log(
                TaskLogEvent(ts=self._now(), level="info", message="status demo: TODO", channel="task")
            )
        )

        v.addWidget(self.card_demo_1)
        v.addWidget(self.card_demo_2)
        v.addStretch(1)

        scroll.setWidget(container)

        self.logs_tabs = QtWidgets.QTabWidget()
        self.logs_tabs.setObjectName("LogsTabs")

        self.task_log_box = QtWidgets.QPlainTextEdit()
        self.task_log_box.setReadOnly(True)
        self.task_log_box.setObjectName("TaskLogBox")
        self.task_log_box.setPlaceholderText("主日志：展示任务大类事件（开始/成功/失败/超时/拒绝等）")

        self.script_log_box = QtWidgets.QPlainTextEdit()
        self.script_log_box.setReadOnly(True)
        self.script_log_box.setObjectName("ScriptLogBox")
        self.script_log_box.setPlaceholderText("脚本日志：展示脚本/子任务输出细节")

        self.logs_tabs.addTab(self.task_log_box, "主日志")
        self.logs_tabs.addTab(self.script_log_box, "脚本日志")

        layout.addWidget(header)
        layout.addWidget(scroll, 2)
        layout.addWidget(self.logs_tabs, 1)
        return page

    def _build_settings_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        page.setObjectName("PageSettings")
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("设置")
        header.setObjectName("PageHeader")

        # Settings: repo selector + add
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.repo_combo = QtWidgets.QComboBox()
        self.repo_combo.setMinimumWidth(360)
        self.repo_combo.currentIndexChanged.connect(self._on_repo_selected)

        self.repo_add_btn = QtWidgets.QPushButton("新增")
        self.repo_add_btn.setObjectName("PrimaryButton")
        self.repo_add_btn.clicked.connect(self._add_repo)

        self.repo_edit_btn = QtWidgets.QPushButton("编辑")
        self.repo_edit_btn.clicked.connect(self._edit_repo)

        self.repo_del_btn = QtWidgets.QPushButton("删除")
        self.repo_del_btn.clicked.connect(self._delete_repo)

        row.addWidget(QtWidgets.QLabel("代码仓库"))
        row.addWidget(self.repo_combo, 1)
        row.addWidget(self.repo_add_btn, 0)
        row.addWidget(self.repo_edit_btn, 0)
        row.addWidget(self.repo_del_btn, 0)

        self.repo_card = QtWidgets.QFrame()
        self.repo_card.setObjectName("RepoCard")
        card_layout = QtWidgets.QFormLayout(self.repo_card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(8)

        self.repo_name_v = QtWidgets.QLabel("-")
        self.repo_base_v = QtWidgets.QLabel("-")
        self.repo_coll_v = QtWidgets.QLabel("-")
        self.repo_proj_v = QtWidgets.QLabel("-")

        from PySide6 import QtCore

        for w in (self.repo_base_v, self.repo_coll_v, self.repo_proj_v):
            w.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        card_layout.addRow("名称", self.repo_name_v)
        card_layout.addRow("Server", self.repo_base_v)
        card_layout.addRow("Collection", self.repo_coll_v)
        card_layout.addRow("Project", self.repo_proj_v)

        hint = QtWidgets.QLabel(
            "提示：点击【编辑】可以修改信息并手动验证；token 会安全存储在系统钥匙串(Keychain)，不会写入仓库文件。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")

        layout.addWidget(header)
        layout.addLayout(row)
        layout.addWidget(self.repo_card)
        layout.addWidget(hint)
        layout.addStretch(1)

        self._refresh_repo_combo()
        return page

    def _refresh_repo_combo(self) -> None:
        self.repo_combo.blockSignals(True)
        self.repo_combo.clear()

        if not self.ui_settings.repos:
            self.repo_combo.addItem("（暂无，点击右侧新增）", userData=None)
            self.repo_combo.setEnabled(False)
        else:
            self.repo_combo.setEnabled(True)
            active_id = self.ui_settings.active_repo_id
            active_index = 0
            for i, r in enumerate(self.ui_settings.repos):
                # B: name · collection · project
                c = r.collection or r.org or "-"
                p = r.project or "-"
                self.repo_combo.addItem(f"{r.display_name}  ·  {c}  ·  {p}", userData=r.id)
                if active_id and r.id == active_id:
                    active_index = i
            self.repo_combo.setCurrentIndex(active_index)

        self.repo_combo.blockSignals(False)
        self._update_repo_status()

    def _active_repo(self):
        if not self.ui_settings.repos:
            return None
        rid = self.ui_settings.active_repo_id or self.ui_settings.repos[0].id
        return next((r for r in self.ui_settings.repos if r.id == rid), None)

    def _update_repo_status(self) -> None:
        repo = self._active_repo()
        has = repo is not None
        self.repo_edit_btn.setEnabled(has)
        self.repo_del_btn.setEnabled(has)
        self.repo_card.setEnabled(has)

        if not repo:
            self.repo_name_v.setText("未配置")
            self.repo_base_v.setText("-")
            self.repo_coll_v.setText("-")
            self.repo_proj_v.setText("-")
            return

        self.repo_name_v.setText(repo.display_name)
        self.repo_base_v.setText(repo.base_url or "-")
        self.repo_coll_v.setText(repo.collection or repo.org or "-")
        self.repo_proj_v.setText(repo.project or "-")

    def _on_repo_selected(self, idx: int) -> None:
        rid = self.repo_combo.currentData()
        if rid:
            self.ui_settings.active_repo_id = rid
            save_ui_settings(self.ui_settings)
        self._update_repo_status()

    def _add_repo(self) -> None:
        dlg = AddRepoDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        repo = dlg.repo()
        if not repo:
            return
        self.ui_settings.repos.append(repo)
        self.ui_settings.active_repo_id = repo.id
        save_ui_settings(self.ui_settings)
        self._refresh_repo_combo()

    def _edit_repo(self) -> None:
        repo = self._active_repo()
        if not repo:
            return
        dlg = AddRepoDialog(self, existing=repo)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        updated = dlg.repo()
        if not updated:
            return
        # replace in list
        self.ui_settings.repos = [updated if r.id == updated.id else r for r in self.ui_settings.repos]
        self.ui_settings.active_repo_id = updated.id
        save_ui_settings(self.ui_settings)
        self._refresh_repo_combo()

    def _delete_repo(self) -> None:
        repo = self._active_repo()
        if not repo:
            return
        ok = QtWidgets.QMessageBox.question(
            self,
            "确认删除",
            f"确定删除仓库配置：{repo.display_name} ?\n(不会自动删除钥匙串里的 token；后续可再加清理按钮)",
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self.ui_settings.repos = [r for r in self.ui_settings.repos if r.id != repo.id]
        self.ui_settings.active_repo_id = self.ui_settings.repos[0].id if self.ui_settings.repos else None
        save_ui_settings(self.ui_settings)
        self._refresh_repo_combo()

    def _now(self) -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()

    def _append_log(self, evt: TaskLogEvent) -> None:
        line = f"[{evt.ts}] {evt.level.upper()} {evt.message}"
        if evt.channel == "script":
            self.script_log_box.appendPlainText(line)
        else:
            self.task_log_box.appendPlainText(line)

    def _show_logs(self, which: str) -> None:
        # focus the right tab
        if which == "script":
            self.logs_tabs.setCurrentWidget(self.script_log_box)
        else:
            self.logs_tabs.setCurrentWidget(self.task_log_box)

    def _run_demo_task(self) -> None:
        self.card_demo_1.set_status("running")
        self.task_log_box.clear()
        self.script_log_box.clear()
        self._show_logs("task")

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

        worker.finished.connect(lambda status: self.card_demo_1.set_status(status))
        worker.failed.connect(lambda err: self.card_demo_1.set_status(f"failed: {err}"))
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

        # auto-switch to script tab if script output is coming in and user asked for it
        # (we keep it simple: do nothing here; user can use the dropdown)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
