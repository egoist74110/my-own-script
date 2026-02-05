from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QWidget, QFormLayout
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    DropDownToolButton,
    ExpandSettingCard,
    FluentIcon,
    PushButton,
)

from app_ado.store import load_task_settings, save_task_settings
from app_ado.ui.run_log_dialog import RunLogDialog
from app_ado.ui.task_flow_dialog import FlowTaskConfigDialog
from ok.gui.widget.Tab import Tab


class TasksTab(Tab):
    """Task page placeholder.

    Next step: implement FlowTask config + execution:
    - repo/branches dropdown discovery
    - merge/push
    - build trigger + monitor
    - release trigger + monitor (multi-stage)
    - logs
    """

    icon = None
    name = "任务"

    def __init__(self):
        super().__init__()

        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        # left: task selector; right: actions
        self.task_combo = ComboBox(); self.task_combo.setFixedWidth(260)
        self.task_combo.addItem("同步/合并 + 构建 + 发布", userData="sync_merge_build_release")

        self.btn_edit = PushButton("配置")
        self.btn_run = PushButton("运行")

        self.btn_run_menu = DropDownToolButton(FluentIcon.CHEVRON_DOWN_MED)
        self.btn_run_menu.setFixedWidth(34)
        menu = QtWidgets.QMenu(self)
        self.action_run = menu.addAction("运行")
        self.action_run.triggered.connect(self._run)
        self.action_clear_log = menu.addAction("清空运行日志")
        self.action_clear_log.triggered.connect(self._clear_run_log)
        self.btn_run_menu.setMenu(menu)

        self.btn_edit.clicked.connect(self._edit)
        self.btn_run.clicked.connect(self._run)

        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        h.addWidget(self.task_combo)
        h.addStretch(1)
        h.addWidget(self.btn_edit)
        h.addWidget(self.btn_run)
        h.addWidget(self.btn_run_menu)

        form.addRow("任务", row)

        self.add_card("任务", w)

        # Collapsible run log panel
        self.run_log_box = QtWidgets.QPlainTextEdit()
        self.run_log_box.setReadOnly(True)
        self.run_log_box.setPlaceholderText("运行日志：每次点击运行会清空并写入新的日志")

        self.run_log_card = ExpandSettingCard(
            FluentIcon.DOCUMENT,
            "运行日志",
            "每次运行会清空并重新写入（可折叠）",
        )
        self.run_log_card.viewLayout.addWidget(self.run_log_box)
        self.run_log_card.setExpand(True)
        self.add_widget(self.run_log_card)

    def _clear_run_log(self) -> None:
        self.run_log_box.clear()

    def _append_run_log(self, text: str) -> None:
        self.run_log_box.appendPlainText(text)
        sb = self.run_log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _edit(self) -> None:
        ts = load_task_settings()
        flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if flow is None:
            from app_ado.models import FlowTaskConfig

            flow = FlowTaskConfig()
            ts.flows.append(flow)

        from app_ado.store import load_ui_settings

        settings = load_ui_settings()
        dlg = FlowTaskConfigDialog(self.window(), settings=settings, flow=flow)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        updated = dlg.result_config()
        if not updated:
            return
        ts.flows = [updated if f.id == updated.id else f for f in ts.flows]
        save_task_settings(ts)

    def _run(self) -> None:
        # v1: only verify we can update both branches locally (git fetch + pull)
        from app_ado.store import load_ui_settings

        ts = load_task_settings()
        flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if not flow or not flow.project_id or not flow.source_branch or not flow.target_branch:
            self._edit()
            ts = load_task_settings()
            flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if not flow:
            return

        local_path = flow.local_repo_path
        if not local_path:
            self._edit()
            ts = load_task_settings()
            flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
            local_path = flow.local_repo_path
        if not local_path:
            return

        # clear + start log
        self._clear_run_log()
        self._append_run_log("运行：更新两个分支")
        self._append_run_log(f"repo_path={local_path}")

        log = RunLogDialog(self.window(), title="运行：更新两个分支")
        log.show()

        import subprocess
        import shlex
        import time

        def run_cmd(cmd: list[str]) -> int:
            line = "$ " + " ".join(shlex.quote(x) for x in cmd)
            log.log(line)
            self._append_run_log(line)
            cp = subprocess.run(cmd, cwd=local_path, capture_output=True, text=True)
            if cp.stdout:
                log.log(cp.stdout.strip())
                self._append_run_log(cp.stdout.strip())
            if cp.stderr:
                log.log(cp.stderr.strip())
                self._append_run_log(cp.stderr.strip())
            return cp.returncode

        # fetch both refs
        rc = run_cmd(["git", "fetch", "--prune", "origin", flow.source_branch, flow.target_branch])
        if rc != 0:
            log.log("fetch 失败")
            return

        # update each branch (ff-only)
        for br in [flow.source_branch, flow.target_branch]:
            rc = run_cmd(["git", "checkout", br])
            if rc != 0:
                log.log(f"checkout 失败: {br}")
                return
            rc = run_cmd(["git", "pull", "--ff-only"]) 
            if rc != 0:
                log.log(f"pull 失败: {br}")
                return

        log.log("✅ 两个分支已更新（fetch + pull --ff-only）")
        self._append_run_log("✅ 两个分支已更新（fetch + pull --ff-only）")
