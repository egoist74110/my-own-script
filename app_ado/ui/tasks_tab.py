from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QWidget, QFormLayout
from qfluentwidgets import CardWidget, ComboBox, PushButton

from app_ado.ui.task_card import TaskCard

from app_ado.store import load_task_settings, save_task_settings
from app_ado.ui.confirm import show_confirm_dialog
from app_ado.ui.dialogs import show_error_dialog
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

        # One task card for now; can add more later.
        self.flow_card = TaskCard(
            title="同步/合并 + 构建 + 发布",
            subtitle="把源分支合并到目标分支，然后构建并发布（后续会接入ADO流水线）",
        )
        self.flow_card.config_clicked.connect(self._edit)
        self.flow_card.run_clicked.connect(self._run)
        self.add_widget(self.flow_card)

    def _clear_run_log(self) -> None:
        self.flow_card.clear_log()

    def _append_run_log(self, text: str) -> None:
        self.flow_card.append_log(text)

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
        # v2: sync both branches, merge source -> target, then push target
        ts = load_task_settings()
        flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if not flow:
            self._edit()
            ts = load_task_settings()
            flow = next((f for f in ts.flows if f.id == "sync_merge_build_release"), None)
        if not flow:
            return

        # basic config validation
        missing: list[str] = []
        if not flow.local_repo_path:
            missing.append("- 本地仓库路径")
        if not flow.source_branch:
            missing.append("- 源分支")
        if not flow.target_branch:
            missing.append("- 目标分支")
        if missing:
            show_error_dialog(self.window(), "配置不完整", "请先在【配置】中补齐：\n" + "\n".join(missing))
            return

        local_path = flow.local_repo_path

        ok = show_confirm_dialog(
            self.window(),
            "确认执行合并并推送？",
            "将执行以下操作：\n"
            f"1) fetch origin {flow.source_branch} / {flow.target_branch}\n"
            f"2) 更新本地分支（ff-only）\n"
            f"3) merge origin/{flow.source_branch} -> {flow.target_branch}\n"
            f"4) push origin {flow.target_branch}\n\n"
            f"repo_path={local_path}",
        )
        if not ok:
            return

        # clear + start log
        self._clear_run_log()
        self._append_run_log("运行：合并并推送")
        self._append_run_log(f"repo_path={local_path}")
        self._append_run_log(f"source={flow.source_branch} target={flow.target_branch}")

        log = RunLogDialog(self.window(), title="运行：合并并推送")
        log.show()

        import subprocess
        import shlex

        def run_cmd(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
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
            if check and cp.returncode != 0:
                raise RuntimeError(f"command failed: {cmd} (rc={cp.returncode})")
            return cp

        def fail(msg: str) -> None:
            log.log(msg)
            self._append_run_log(msg)

        try:
            # verify git repo
            cp = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
            if cp.returncode != 0 or "true" not in (cp.stdout or "").lower():
                show_error_dialog(self.window(), "错误", f"不是有效的 git 仓库：{local_path}")
                return

            # workspace must be clean
            cp = run_cmd(["git", "status", "--porcelain"])
            if cp.returncode != 0:
                fail("git status 失败")
                return
            dirty = (cp.stdout or "").strip()
            if dirty:
                show_error_dialog(
                    self.window(),
                    "工作区未清理",
                    "检测到未提交改动，请先处理后再运行：\n\n" + dirty,
                )
                return

            # fetch both refs
            cp = run_cmd(["git", "fetch", "--prune", "origin", flow.source_branch, flow.target_branch])
            if cp.returncode != 0:
                fail("fetch 失败")
                return

            # update each branch (ff-only)
            for br in [flow.source_branch, flow.target_branch]:
                cp = run_cmd(["git", "checkout", br])
                if cp.returncode != 0:
                    fail(f"checkout 失败: {br}")
                    return
                cp = run_cmd(["git", "pull", "--ff-only"])
                if cp.returncode != 0:
                    fail(f"pull 失败: {br}")
                    return

            # merge source into target
            cp = run_cmd(["git", "checkout", flow.target_branch])
            if cp.returncode != 0:
                fail(f"checkout 失败: {flow.target_branch}")
                return

            cp = run_cmd(["git", "merge", f"origin/{flow.source_branch}"])
            if cp.returncode != 0:
                # list conflict files if any
                cp2 = run_cmd(["git", "diff", "--name-only", "--diff-filter=U"])
                conflicts = (cp2.stdout or "").strip()
                show_error_dialog(
                    self.window(),
                    "合并失败（可能存在冲突）",
                    "merge 失败。请手动处理冲突后再运行。\n\n冲突文件：\n" + (conflicts or "(未检测到冲突文件列表)"),
                )
                return

            # push target
            cp = run_cmd(["git", "push", "origin", flow.target_branch])
            if cp.returncode != 0:
                show_error_dialog(self.window(), "推送失败", f"push 失败，请检查权限/分支保护。\n\nbranch={flow.target_branch}")
                return

            cp = run_cmd(["git", "rev-parse", "HEAD"])
            head = (cp.stdout or "").strip() if cp.returncode == 0 else ""
            ok_msg = f"✅ 合并并推送完成：{flow.source_branch} -> {flow.target_branch}" + (f"\nHEAD={head}" if head else "")
            log.log(ok_msg)
            self._append_run_log(ok_msg)

            # ---- Build (v3) ----
            from app_ado.store import load_ui_settings
            from app_ado.secrets import get_pat
            from app_ado.ado_build_http import (
                trigger_build_definition,
                trigger_pipeline_run,
                wait_build,
                wait_pipeline,
            )

            settings = load_ui_settings()
            proj = next((p for p in settings.projects if p.id == flow.project_id), None)
            if not proj:
                show_error_dialog(self.window(), "错误", "找不到项目配置（project_id）")
                return
            lib = next((l for l in settings.libraries if l.id == proj.library_id), None)
            if not lib:
                show_error_dialog(self.window(), "错误", "找不到代码库配置（library_id）")
                return
            pat = get_pat(lib.id)
            if not pat:
                show_error_dialog(self.window(), "错误", "该代码库未保存 PAT")
                return

            if not flow.build_id or not flow.build_kind:
                show_error_dialog(self.window(), "配置不完整", "请先在【配置】里选择构建，并保存")
                return

            branch = flow.target_branch
            self._append_run_log(f"\n--- Build: kind={flow.build_kind} id={flow.build_id} branch={branch} ---")

            if flow.build_kind == "pipeline":
                pr = trigger_pipeline_run(lib.base_url, proj.collection, proj.project, flow.build_id, branch=branch, pat=pat)
                self._append_run_log(f"已触发 Pipeline：run_id={pr.run_id} state={pr.state} url={pr.url or ''}")
                pr2 = wait_pipeline(lib.base_url, proj.collection, proj.project, flow.build_id, pr.run_id, pat=pat, timeout_min=30)
                self._append_run_log(f"Pipeline 完成：state={pr2.state} result={pr2.result} url={pr2.url or ''}")
                if (pr2.result or '').lower() not in ('succeeded', 'success'):
                    show_error_dialog(self.window(), "构建失败", f"Pipeline result={pr2.result}\n{pr2.url or ''}")
                    return
            else:
                br = trigger_build_definition(lib.base_url, proj.collection, proj.project, flow.build_id, branch=branch, pat=pat)
                self._append_run_log(f"已触发 Build：build_id={br.build_id} status={br.status} url={br.url or ''}")
                br2 = wait_build(lib.base_url, proj.collection, proj.project, br.build_id, pat=pat, timeout_min=30)
                self._append_run_log(f"Build 完成：status={br2.status} result={br2.result} url={br2.url or ''}")
                if (br2.result or '').lower() not in ('succeeded', 'success', 'partiallysucceeded'):
                    show_error_dialog(self.window(), "构建失败", f"Build result={br2.result}\n{br2.url or ''}")
                    return

            self._append_run_log("✅ 构建成功（下一步：接入 Release 触发+监控）")

        except Exception as e:
            show_error_dialog(self.window(), "运行异常", str(e))
            return
