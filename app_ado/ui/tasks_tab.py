from __future__ import annotations

from PySide6 import QtCore
from PySide6.QtWidgets import QWidget, QFormLayout
from qfluentwidgets import CardWidget, ComboBox, PushButton

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

        self.task_combo = ComboBox(); self.task_combo.setFixedWidth(260)
        self.task_combo.addItem("同步/合并 + 构建 + 发布", userData="sync_merge_build_release")

        self.btn_edit = PushButton("配置")
        self.btn_run = PushButton("运行")

        self.btn_edit.clicked.connect(self._edit)
        self.btn_run.clicked.connect(self._run)

        form.addRow("任务", self.task_combo)
        form.addRow(self.btn_edit, self.btn_run)

        self.add_card("任务", w)

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

        local_path = getattr(flow, "local_repo_path", "")
        if not local_path:
            self._edit()
            ts = load_task_settings()
            flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
            local_path = getattr(flow, "local_repo_path", "")
        if not local_path:
            return

        log = RunLogDialog(self.window(), title="运行：更新两个分支")
        log.show()

        import subprocess
        import shlex
        import time

        def run_cmd(cmd: list[str]) -> int:
            log.log("$ " + " ".join(shlex.quote(x) for x in cmd))
            cp = subprocess.run(cmd, cwd=local_path, capture_output=True, text=True)
            if cp.stdout:
                log.log(cp.stdout.strip())
            if cp.stderr:
                log.log(cp.stderr.strip())
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
