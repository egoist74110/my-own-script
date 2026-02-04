from __future__ import annotations

import sys
from dataclasses import asdict

from PySide6 import QtCore, QtWidgets

from ui_app.logging_setup import setup_app_logger
from ui_app.task_base import DemoSleepTask, TaskLogEvent
from ui_app.widgets import NavButton, TaskRowCard
from ui_app.settings_store import load_ui_settings, save_ui_settings, UiSettings, LibraryEntry, ProjectEntry
from ui_app.dialogs_library import LibraryDialog
from ui_app.dialogs_project import ProjectDialog
from ui_app.library_store import new_library_id, set_pat


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
        # light theme + high contrast
        self.setStyleSheet(
            """
            #Root { background: #f5f7fb; }
            #Sidebar { background: #ffffff; border-right: 1px solid #e5e7eb; }
            #SidebarTitle { color: #0f172a; font-size: 16px; font-weight: 800; padding: 6px 6px; }

            QPushButton#NavButton {
              text-align: left;
              padding: 10px 10px;
              border-radius: 10px;
              color: #0f172a;
              background: transparent;
              border: 1px solid transparent;
            }
            QPushButton#NavButton:hover { background: rgba(2,132,199,0.08); }
            QPushButton#NavButton:checked {
              background: rgba(2,132,199,0.12);
              border: 1px solid rgba(2,132,199,0.25);
              color: #0f172a;
            }

            #Stack { background: #f5f7fb; }
            QLabel#PageHeader { color: #0f172a; font-size: 20px; font-weight: 800; }
            QLabel#Muted { color: #475569; }

            QScrollArea#TaskScroll { border: none; background: transparent; }
            QWidget#TaskList { background: transparent; }

            QFrame#TaskRowCard {
              background: #ffffff;
              border: 1px solid #e5e7eb;
              border-radius: 14px;
            }
            QFrame#TaskRowCard:hover { border: 1px solid rgba(2,132,199,0.40); }

            QFrame#RepoCard {
              background: #ffffff;
              border: 1px solid #e5e7eb;
              border-radius: 14px;
            }
            QFrame#RepoCard QLabel { color: #0f172a; }

            /* Dialog / form widgets */
            QDialog { background: #ffffff; }
            QDialog QLabel { color: #0f172a; }
            QLineEdit, QComboBox {
              background: #ffffff;
              color: #0f172a;
              border-radius: 10px;
              border: 1px solid #cbd5e1;
              padding: 8px 12px;
              min-height: 34px;
            }
            QLineEdit:focus, QComboBox:focus {
              border: 1px solid rgba(2,132,199,0.45);
            }
            QLineEdit:disabled, QComboBox:disabled { color: #94a3b8; border: 1px solid #e2e8f0; }

            /* macOS-like combo */
            QComboBox { padding-right: 28px; }
            QComboBox::drop-down {
              subcontrol-origin: padding;
              subcontrol-position: top right;
              width: 26px;
              border-left: 1px solid #e2e8f0;
              border-top-right-radius: 10px;
              border-bottom-right-radius: 10px;
              background: #f8fafc;
            }
            QComboBox::down-arrow {
              width: 10px;
              height: 10px;
              image: none;
            }

            QComboBox QAbstractItemView {
              background: #ffffff;
              color: #0f172a;
              border: 1px solid #cbd5e1;
              border-radius: 10px;
              padding: 6px;
              selection-background-color: rgba(2,132,199,0.12);
              selection-color: #0f172a;
              outline: 0;
            }
            QComboBox QAbstractItemView::item {
              padding: 8px 10px;
              border-radius: 8px;
              margin: 2px;
            }
            QComboBox QAbstractItemView::item:selected {
              background: rgba(2,132,199,0.12);
            }
            QComboBox QAbstractItemView::item:hover {
              background: rgba(2,132,199,0.08);
            }

            QLabel#TaskTitle { color: #0f172a; font-size: 15px; font-weight: 750; }
            QLabel#TaskSubtitle { color: #475569; }
            QLabel#TaskStatus { color: #0f172a; }

            QPushButton#PrimaryButton {
              background: #0284c7;
              color: #ffffff;
              padding: 9px 16px;
              border-radius: 12px;
              border: 1px solid rgba(2,132,199,0.6);
            }
            QPushButton#PrimaryButton:hover { background: #0369a1; }
            QPushButton#PrimaryButton:pressed { background: #075985; }

            QPushButton#SecondaryButton {
              background: #ffffff;
              color: #0f172a;
              padding: 9px 14px;
              border-radius: 12px;
              border: 1px solid #cbd5e1;
            }
            QPushButton#SecondaryButton:hover { background: #f1f5f9; }

            QPushButton#DangerButton {
              background: #ffffff;
              color: #b91c1c;
              padding: 9px 14px;
              border-radius: 12px;
              border: 1px solid rgba(185,28,28,0.45);
            }
            QPushButton#DangerButton:hover { background: rgba(185,28,28,0.08); }

            QToolButton#MenuButton {
              background: #ffffff;
              color: #0f172a;
              border-radius: 10px;
              padding: 6px 10px;
              border: 1px solid #cbd5e1;
            }
            QToolButton#MenuButton:hover { background: #f1f5f9; }

            QTabWidget::pane {
              border: 1px solid #e5e7eb;
              border-radius: 12px;
              top: -1px;
              background: #ffffff;
            }
            QTabBar::tab {
              background: #f1f5f9;
              color: #334155;
              padding: 8px 12px;
              border-top-left-radius: 10px;
              border-top-right-radius: 10px;
              margin-right: 6px;
            }
            QTabBar::tab:selected { color: #0f172a; background: #ffffff; }

            QPlainTextEdit#TaskLogBox, QPlainTextEdit#ScriptLogBox {
              background: #ffffff;
              color: #0f172a;
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

        from PySide6 import QtCore

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        def make_row(label: str):
            l = QtWidgets.QLabel(label)
            combo = QtWidgets.QComboBox()
            combo.setMinimumWidth(380)
            btn_add = QtWidgets.QPushButton("新增")
            btn_add.setObjectName("PrimaryButton")
            btn_edit = QtWidgets.QPushButton("编辑")
            btn_edit.setObjectName("SecondaryButton")
            btn_del = QtWidgets.QPushButton("删除")
            btn_del.setObjectName("DangerButton")
            return l, combo, btn_add, btn_edit, btn_del

        # Row 1: Libraries
        self.lib_label, self.lib_combo, self.lib_add_btn, self.lib_edit_btn, self.lib_del_btn = make_row("代码库")
        self.lib_combo.currentIndexChanged.connect(self._on_library_selected)
        self.lib_add_btn.clicked.connect(self._add_library)
        self.lib_edit_btn.clicked.connect(self._edit_library)
        self.lib_del_btn.clicked.connect(self._delete_library)

        # Row 2: Projects
        self.proj_label, self.proj_combo, self.proj_add_btn, self.proj_edit_btn, self.proj_del_btn = make_row("项目")
        self.proj_combo.currentIndexChanged.connect(self._on_project_selected)
        self.proj_add_btn.clicked.connect(self._add_project)
        self.proj_edit_btn.clicked.connect(self._edit_project)
        self.proj_del_btn.clicked.connect(self._delete_project)

        # Layout rows: label | combo | add | edit | del
        grid.addWidget(self.lib_label, 0, 0)
        grid.addWidget(self.lib_combo, 0, 1)
        grid.addWidget(self.lib_add_btn, 0, 2)
        grid.addWidget(self.lib_edit_btn, 0, 3)
        grid.addWidget(self.lib_del_btn, 0, 4)

        grid.addWidget(self.proj_label, 1, 0)
        grid.addWidget(self.proj_combo, 1, 1)
        grid.addWidget(self.proj_add_btn, 1, 2)
        grid.addWidget(self.proj_edit_btn, 1, 3)
        grid.addWidget(self.proj_del_btn, 1, 4)

        # Info card
        self.info_card = QtWidgets.QFrame()
        self.info_card.setObjectName("RepoCard")
        info_layout = QtWidgets.QFormLayout(self.info_card)
        info_layout.setContentsMargins(14, 14, 14, 14)
        info_layout.setSpacing(8)

        self.info_a = QtWidgets.QLabel("-")
        self.info_b = QtWidgets.QLabel("-")
        self.info_c = QtWidgets.QLabel("-")

        for w in (self.info_a, self.info_b, self.info_c):
            w.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        info_layout.addRow("当前代码库", self.info_a)
        info_layout.addRow("URL", self.info_b)
        info_layout.addRow("当前项目", self.info_c)

        hint = QtWidgets.QLabel(
            "代码库：只配置名称+URL+PAT（安全写入 Keychain）。\n"
            "项目：选择代码库后拉取 collection/project（能拉就下拉默认第一个；拉不到就手填）。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")

        layout.addWidget(header)
        layout.addLayout(grid)
        layout.addWidget(self.info_card)
        layout.addWidget(hint)
        layout.addStretch(1)

        self._refresh_settings_rows()
        return page

    def _refresh_settings_rows(self) -> None:
        # Libraries dropdown
        self.lib_combo.blockSignals(True)
        self.lib_combo.clear()
        if not self.ui_settings.libraries:
            self.lib_combo.addItem("（暂无，点击新增）", userData=None)
            self.lib_combo.setEnabled(False)
        else:
            self.lib_combo.setEnabled(True)
            active = self.ui_settings.active_library_id
            idx = 0
            for i, lib in enumerate(self.ui_settings.libraries):
                self.lib_combo.addItem(lib.name, userData=lib.id)
                if active and lib.id == active:
                    idx = i
            self.lib_combo.setCurrentIndex(idx)
        self.lib_combo.blockSignals(False)

        # Projects dropdown
        self.proj_combo.blockSignals(True)
        self.proj_combo.clear()
        if not self.ui_settings.projects:
            self.proj_combo.addItem("（暂无，点击新增）", userData=None)
            self.proj_combo.setEnabled(False)
        else:
            self.proj_combo.setEnabled(True)
            active = self.ui_settings.active_project_id
            idx = 0
            for i, p in enumerate(self.ui_settings.projects):
                self.proj_combo.addItem(p.project, userData=p.id)  # 2:b only name
                if active and p.id == active:
                    idx = i
            self.proj_combo.setCurrentIndex(idx)
        self.proj_combo.blockSignals(False)

        self._update_info_card()

    def _active_library(self) -> LibraryEntry | None:
        if not self.ui_settings.libraries:
            return None
        lid = self.ui_settings.active_library_id or self.ui_settings.libraries[0].id
        return next((x for x in self.ui_settings.libraries if x.id == lid), None)

    def _active_project(self) -> ProjectEntry | None:
        if not self.ui_settings.projects:
            return None
        pid = self.ui_settings.active_project_id or self.ui_settings.projects[0].id
        return next((x for x in self.ui_settings.projects if x.id == pid), None)

    def _update_info_card(self) -> None:
        lib = self._active_library()
        proj = self._active_project()

        self.lib_edit_btn.setEnabled(lib is not None)
        self.lib_del_btn.setEnabled(lib is not None)
        self.proj_edit_btn.setEnabled(proj is not None)
        self.proj_del_btn.setEnabled(proj is not None)

        if not lib:
            self.info_a.setText("未配置")
            self.info_b.setText("-")
        else:
            self.info_a.setText(lib.name)
            self.info_b.setText(lib.base_url)

        self.info_c.setText(proj.project if proj else "-")

    def _on_library_selected(self, idx: int) -> None:
        lid = self.lib_combo.currentData()
        if lid:
            self.ui_settings.active_library_id = lid
            save_ui_settings(self.ui_settings)
        self._update_info_card()

    def _on_project_selected(self, idx: int) -> None:
        pid = self.proj_combo.currentData()
        if pid:
            self.ui_settings.active_project_id = pid
            save_ui_settings(self.ui_settings)
        self._update_info_card()

    def _add_library(self) -> None:
        dlg = LibraryDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        entry = dlg.result_entry()
        if not entry:
            return

        # assign real id
        real_id = new_library_id()
        entry = entry.model_copy(update={"id": real_id})
        # If dialog stored token under placeholder id, user will re-enter; keep simple.

        self.ui_settings.libraries.append(entry)
        self.ui_settings.active_library_id = entry.id
        save_ui_settings(self.ui_settings)
        self._refresh_settings_rows()

    def _edit_library(self) -> None:
        lib = self._active_library()
        if not lib:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择一个代码库")
            return
        dlg = LibraryDialog(self, existing=lib)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        updated = dlg.result_entry()
        if not updated:
            return
        # keep id
        updated = updated.model_copy(update={"id": lib.id})
        self.ui_settings.libraries = [updated if x.id == lib.id else x for x in self.ui_settings.libraries]
        self.ui_settings.active_library_id = lib.id
        save_ui_settings(self.ui_settings)
        self._refresh_settings_rows()

    def _delete_library(self) -> None:
        lib = self._active_library()
        if not lib:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择一个代码库")
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除代码库：{lib.name} ?")
        if ok != QtWidgets.QMessageBox.Yes:
            return

        self.ui_settings.libraries = [x for x in self.ui_settings.libraries if x.id != lib.id]
        # also remove projects under this library
        self.ui_settings.projects = [p for p in self.ui_settings.projects if p.library_id != lib.id]
        self.ui_settings.active_library_id = self.ui_settings.libraries[0].id if self.ui_settings.libraries else None
        self.ui_settings.active_project_id = self.ui_settings.projects[0].id if self.ui_settings.projects else None
        save_ui_settings(self.ui_settings)
        self._refresh_settings_rows()

    def _add_project(self) -> None:
        if not self.ui_settings.libraries:
            QtWidgets.QMessageBox.information(self, "提示", "请先新增一个代码库")
            return
        dlg = ProjectDialog(self, libraries=self.ui_settings.libraries)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        entry = dlg.result_entry()
        if not entry:
            return
        self.ui_settings.projects.append(entry)
        self.ui_settings.active_project_id = entry.id
        save_ui_settings(self.ui_settings)
        self._refresh_settings_rows()

    def _edit_project(self) -> None:
        proj = self._active_project()
        if not proj:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择一个项目")
            return
        dlg = ProjectDialog(self, libraries=self.ui_settings.libraries, existing=proj)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        updated = dlg.result_entry()
        if not updated:
            return
        updated = updated.model_copy(update={"id": proj.id})
        self.ui_settings.projects = [updated if x.id == proj.id else x for x in self.ui_settings.projects]
        self.ui_settings.active_project_id = proj.id
        save_ui_settings(self.ui_settings)
        self._refresh_settings_rows()

    def _delete_project(self) -> None:
        proj = self._active_project()
        if not proj:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择一个项目")
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除项目：{proj.project} ?")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self.ui_settings.projects = [x for x in self.ui_settings.projects if x.id != proj.id]
        self.ui_settings.active_project_id = self.ui_settings.projects[0].id if self.ui_settings.projects else None
        save_ui_settings(self.ui_settings)
        self._refresh_settings_rows()

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
