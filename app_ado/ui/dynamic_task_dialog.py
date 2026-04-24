from __future__ import annotations

import re
import uuid

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, ComboBox, LineEdit, PushButton

from app_ado.ado_http import GitBranch, GitRepo, list_branches, list_repos
from app_ado.models import (
    DeployTarget,
    DynamicTaskConfig,
    GitFlow,
    GitMergeRule,
    UiSettings,
    project_entry_collection,
    project_entry_id,
    project_entry_library_id,
    project_entry_name,
)
from app_ado.secrets import get_pat
# (build/release discovery is handled in DeployTargetDialog; no need to import build/release http here)
from app_ado.ui.deploy_target_dialog import DeployTargetDialog
from app_ado.ui.dialogs import show_error_dialog


_CMD_RE = re.compile(r"^[a-z0-9_]{1,32}$")


class BranchPickerDialog(QtWidgets.QDialog):
    """Custom branch selection dialog with a dedicated Refresh button next to the label."""

    def __init__(self, parent: DynamicTaskConfigDialog, title: str, branches: list[str], current_value: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(420)
        self.setModal(True)
        self._current_value = current_value

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Row 1: Label + Refresh Button
        row1 = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("选择分支：")
        label.setStyleSheet("font-weight: bold;")
        row1.addWidget(label)
        row1.addStretch(1)
        self.btn_refresh = PushButton("刷新")
        self.btn_refresh.setFixedWidth(80)
        row1.addWidget(self.btn_refresh)
        layout.addLayout(row1)

        # Row 2: Selection ComboBox
        self.combo = ComboBox()
        self.combo.addItems(branches)
        # Pre-select current value
        if current_value:
            for i in range(self.combo.count()):
                if self.combo.itemText(i) == current_value:
                    self.combo.setCurrentIndex(i)
                    break

        # Note: ComboBox from qfluentwidgets might need a bit of stretch to look good
        self.combo.setMinimumHeight(32)
        layout.addWidget(self.combo)

        # Row 3: Standard Buttons
        self.btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)
        layout.addWidget(self.btns)

        # Signals
        self.btn_refresh.clicked.connect(self._do_refresh)

        # 自动触发：如果列表为空，刚开弹窗时自动刷新一次，省去用户点击
        if not branches:
            QtCore.QTimer.singleShot(100, self._do_refresh)

    def _do_refresh(self):
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("刷新中...")

        def on_done():
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("刷新")
            # Get updated branches from parent
            new_branches = getattr(self.parent(), "_branches", [])
            self.combo.clear()
            self.combo.addItems(new_branches)
            
            # 刷新完成后，重新尝试选中默认值
            if self._current_value:
                for i in range(self.combo.count()):
                    if self.combo.itemText(i) == self._current_value:
                        self.combo.setCurrentIndex(i)
                        break

        # Call parent's refresh logic
        self.parent()._refresh_repos_and_branches(callback=on_done)

    def selected_branch(self) -> str:
        return self.combo.currentText().strip()


class DynamicTaskConfigDialog(QtWidgets.QDialog):
    def _set_list(self, w: QtWidgets.QListWidget, items: list[str]) -> None:
        w.clear()
        for s in items or []:
            s2 = str(s).strip()
            if not s2:
                continue
            it = QtWidgets.QListWidgetItem(s2)
            it.setData(QtCore.Qt.UserRole, s2)
            w.addItem(it)

    def _get_list(self, w: QtWidgets.QListWidget) -> list[str]:
        out: list[str] = []
        for i in range(w.count()):
            it = w.item(i)
            v = str(it.data(QtCore.Qt.UserRole) or it.text() or "").strip()
            if v:
                out.append(v)
        return out

    def _set_merge_list(self, w: QtWidgets.QListWidget, merges: list[GitMergeRule]) -> None:
        w.clear()
        for mr in merges or []:
            src = (mr.source or "").strip()
            tgt = (mr.target or "").strip()
            if not src or not tgt:
                continue
            txt = f"{src} -> {tgt}"
            it = QtWidgets.QListWidgetItem(txt)
            it.setData(QtCore.Qt.UserRole, {"source": src, "target": tgt})
            w.addItem(it)

    def _get_merge_list(self, w: QtWidgets.QListWidget) -> list[GitMergeRule]:
        out: list[GitMergeRule] = []
        for i in range(w.count()):
            it = w.item(i)
            d = it.data(QtCore.Qt.UserRole)
            if isinstance(d, dict):
                src = str(d.get("source") or "").strip()
                tgt = str(d.get("target") or "").strip()
            else:
                # fallback parse
                txt = (it.text() or "")
                if "->" in txt:
                    src, tgt = [x.strip() for x in txt.split("->", 1)]
                else:
                    continue
            if src and tgt:
                out.append(GitMergeRule(source=src, target=tgt))
        return out

    def _pick_build_branch(self) -> None:
        val = self.build_branch.text().strip()
        self._pick_branch("选择构建分支", current_value=val, on_picked=lambda br: self.build_branch.setText(br))

    def _pick_branch(self, title: str, current_value: str = "", on_picked: callable = None) -> str | None:
        dlg = BranchPickerDialog(self, title, self._branches, current_value=current_value)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return None

        res = dlg.selected_branch()
        if not res:
            return None

        if on_picked:
            on_picked(res)
        return res

    def _add_update_branch(self) -> None:
        def _on_picked(br: str):
            cur = self._get_list(self.update_list)
            cur.append(br)
            self._set_list(self.update_list, cur)
        self._pick_branch("新增更新分支", on_picked=_on_picked)

    def _del_update_branch(self) -> None:
        row = self.update_list.currentRow()
        if row >= 0:
            self.update_list.takeItem(row)

    def _add_push_branch(self) -> None:
        def _on_picked(br: str):
            cur = self._get_list(self.push_list)
            cur.append(br)
            self._set_list(self.push_list, cur)
        self._pick_branch("新增推送分支", on_picked=_on_picked)

    def _del_push_branch(self) -> None:
        row = self.push_list.currentRow()
        if row >= 0:
            self.push_list.takeItem(row)

    def _add_merge_rule(self) -> None:
        def _on_src_picked(src: str):
            # 第一步选完 source，接着选 target
            def _on_tgt_picked(tgt: str):
                merges = self._get_merge_list(self.merge_list)
                merges.append(GitMergeRule(source=src, target=tgt))
                self._set_merge_list(self.merge_list, merges)
            
            self._pick_branch("选择合并目标分支", on_picked=_on_tgt_picked)

        self._pick_branch("选择合并源分支", on_picked=_on_src_picked)

    def _del_merge_rule(self) -> None:
        row = self.merge_list.currentRow()
        if row >= 0:
            self.merge_list.takeItem(row)
    """Configure a dynamic task.

    v1: git_flow UI is compatible with existing two modes:
    - with merge: source -> target
    - without merge: only target branch
    """

    def __init__(self, parent, *, settings: UiSettings, task: DynamicTaskConfig):
        super().__init__(parent)
        self._settings = settings
        self._task = task
        self._result: DynamicTaskConfig | None = None

        self.setWindowTitle("配置任务")
        self.setModal(True)
        self.resize(820, 640)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        root.addLayout(form)

        def combo() -> ComboBox:
            cb = ComboBox(); cb.setFixedWidth(260)
            return cb

        # meta
        # We keep a display name in config for UI, but you can just use TG command/desc.
        # In this dialog we make name optional and auto-derived from tg_command.
        self.name_edit = LineEdit(); self.name_edit.setFixedWidth(420)
        self.cmd_edit = LineEdit(); self.cmd_edit.setFixedWidth(260)
        self.desc_edit = LineEdit(); self.desc_edit.setFixedWidth(420)

        # project/repo
        self.project_combo = combo()
        for p in settings.projects:
            project_id = project_entry_id(p)
            project_name = project_entry_name(p)
            if not project_id or not project_name:
                continue
            self.project_combo.addItem(project_name, userData=project_id)

        self.repo_path = LineEdit(); self.repo_path.setFixedWidth(420)
        self.btn_pick_path = PushButton("选择...")
        self.btn_clear_path = PushButton("清空")
        self.btn_clear_path.setFixedWidth(72)

        self.repo_combo = combo()

        # build branch
        self.build_branch = LineEdit(); self.build_branch.setFixedWidth(260)
        self.btn_pick_build_branch = PushButton("选择...")

        # GitFlow (list)
        self.update_list = QtWidgets.QListWidget(); self.update_list.setFixedHeight(110)
        self.btn_add_update = PushButton("新增")
        self.btn_del_update = PushButton("删除")

        self.merge_list = QtWidgets.QListWidget(); self.merge_list.setFixedHeight(130)
        self.btn_add_merge = PushButton("新增")
        self.btn_del_merge = PushButton("删除")

        self.push_list = QtWidgets.QListWidget(); self.push_list.setFixedHeight(110)
        self.btn_add_push = PushButton("新增")
        self.btn_del_push = PushButton("删除")

        # targets
        self.deploy_target_combo = combo()
        self.btn_new_target = PushButton("新增")
        self.btn_edit_target = PushButton("编辑")
        self.btn_del_target = PushButton("删除")

        self.btn_refresh = PushButton("刷新 Repo/分支")
        self._branches: list[str] = []

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        form.addRow("TG 命令（/xxx）", self.cmd_edit)
        form.addRow("中文说明（显示在 /help）", self.desc_edit)
        # No separate name: tg_command is the identity; tg_desc is the human label.
        # (Keep name_edit hidden for back-compat; not shown to user.)
        self.name_edit.setVisible(False)
        form.addRow("项目", self.project_combo)
        form.addRow("本地仓库路径", self._row(self.repo_path, self._row(self.btn_pick_path, self.btn_clear_path)))
        form.addRow("仓库(Repo)", self.repo_combo)
        form.addRow("构建分支", self._row(self.build_branch, self.btn_pick_build_branch))

        form.addRow("更新分支（按顺序 checkout + pull --ff-only，可为空）", self._row(self.update_list, self._row(self.btn_add_update, self.btn_del_update)))
        form.addRow("合并规则（按顺序 merge origin/<source> -> <target>）", self._row(self.merge_list, self._row(self.btn_add_merge, self.btn_del_merge)))
        self.push_hint = QtWidgets.QLabel("提示：Push 仅在填写【本地仓库路径】时可用；未填写时将禁用（避免远程推送带来的风险）。")
        self.push_hint.setWordWrap(True)
        self.push_hint.setStyleSheet("color:#666;")

        form.addRow("推送分支（按顺序 push origin <branch>）", self._row(self.push_list, self._row(self.btn_add_push, self.btn_del_push)))
        form.addRow(self.push_hint)

        form.addRow(
            "发布目标",
            self._row(
                self.deploy_target_combo,
                self._row(self.btn_new_target, self._row(self.btn_edit_target, self.btn_del_target)),
            ),
        )

        root.addWidget(self.btn_refresh)
        root.addWidget(self.status)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # signals
        self.btn_pick_path.clicked.connect(self._pick_path)
        self.btn_clear_path.clicked.connect(lambda: self.repo_path.setText(""))
        self.btn_refresh.clicked.connect(self._refresh_repos_and_branches)
        self.repo_combo.currentIndexChanged.connect(self._on_repo_changed)
        self.btn_pick_build_branch.clicked.connect(self._pick_build_branch)

        self.btn_add_update.clicked.connect(self._add_update_branch)
        self.btn_del_update.clicked.connect(self._del_update_branch)
        self.btn_add_merge.clicked.connect(self._add_merge_rule)
        self.btn_del_merge.clicked.connect(self._del_merge_rule)
        self.btn_add_push.clicked.connect(self._add_push_branch)
        self.btn_del_push.clicked.connect(self._del_push_branch)

        self.repo_path.textChanged.connect(self._update_push_enabled)

        self.btn_new_target.clicked.connect(self._new_deploy_target)
        self.btn_edit_target.clicked.connect(self._edit_deploy_target)
        self.btn_del_target.clicked.connect(self._delete_deploy_target)

        # state
        self._targets = list(task.targets or [])
        self._refresh_target_combo()

        # prefill
        self.name_edit.setText(task.name or "")
        self.cmd_edit.setText(task.tg_command or "")
        self.desc_edit.setText(task.tg_desc or "")
        self.repo_path.setText(task.local_repo_path or "")

        if task.project_id:
            for i in range(self.project_combo.count()):
                if self.project_combo.itemData(i) == task.project_id:
                    self.project_combo.setCurrentIndex(i)
                    break

        # prefill git_flow
        self.build_branch.setText((task.git_flow.build_branch or "").strip())
        self._set_list(self.update_list, list(task.git_flow.update_branches or []))
        self._set_merge_list(self.merge_list, list(task.git_flow.merges or []))
        self._set_list(self.push_list, list(task.git_flow.push_branches or []))

        self._update_push_enabled()

        # echo saved values if not yet loaded
        if task.repo_name:
            if self.repo_combo.count() == 0:
                self.repo_combo.addItem(task.repo_name, userData=GitRepo(id=task.repo_id or "", name=task.repo_name))
            self.repo_combo.setCurrentIndex(0)

        # Note: branch pickers are driven by the lists above; refresh Repo/分支
        # will populate self._branches for selection.

    def result_task(self) -> DynamicTaskConfig | None:
        return self._result

    def _row(self, a: QtWidgets.QWidget, b: QtWidgets.QWidget) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(a)
        h.addWidget(b)
        h.addStretch(1)
        return w

    def _pick_path(self) -> None:
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "选择本地仓库目录")
        if p:
            self.repo_path.setText(p)

    def _selected_project(self):
        pid = self.project_combo.currentData()
        return next((p for p in self._settings.projects if project_entry_id(p) == pid), None)

    def _selected_library(self, project):
        library_id = project_entry_library_id(project)
        return next((l for l in self._settings.libraries if l.id == library_id), None)

    def _set_loading(self, on: bool, msg: str = "") -> None:
        self.btn_refresh.setEnabled(not on)
        if msg:
            self.status.setText(msg)

    def _refresh_repos_and_branches(self, *, callback: callable = None) -> None:
        proj = self._selected_project()
        if not proj:
            show_error_dialog(self, "错误", "请先新增并选择项目")
            return
        lib = self._selected_library(proj)
        if not lib:
            show_error_dialog(self, "错误", "项目未关联代码库")
            return
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(self, "错误", "该代码库未保存 PAT")
            return
        collection = project_entry_collection(proj)
        project_name = project_entry_name(proj)
        if not collection or not project_name:
            show_error_dialog(self, "错误", "项目配置缺少 collection/project")
            return

        # 获取当前选中的 Repo ID，以便刷新后恢复
        current_repo: GitRepo | None = self.repo_combo.currentData()
        current_repo_id = current_repo.id if current_repo else (self._task.repo_id or None)

        self._set_loading(True, "刷新 Repo/分支...")

        import threading

        result: dict | Exception | None = None

        def run():
            nonlocal result
            try:
                repos = list_repos(lib.base_url, collection, project_name, pat=pat)
                
                # 如果当前选中的 ID 在新的列表中，则继续使用它
                rid = current_repo_id
                if rid and not any(r.id == rid for r in repos):
                    rid = repos[0].id if repos else None
                elif not rid:
                    rid = repos[0].id if repos else None
                
                branches: list[GitBranch] = []
                if rid:
                    branches = list_branches(lib.base_url, collection, project_name, rid, pat=pat)
                result = {"repos": repos, "repo_id": rid, "branches": branches}
            except Exception as e:
                result = e

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish():
            nonlocal result
            if th.is_alive():
                QtCore.QTimer.singleShot(80, self, finish)
                return
            self._set_loading(False)
            if isinstance(result, Exception):
                show_error_dialog(self, "刷新失败", str(result))
                return
            assert isinstance(result, dict)
            repos: list[GitRepo] = result.get("repos") or []
            rid = result.get("repo_id")
            branches: list[GitBranch] = result.get("branches") or []

            # 刷新 Repo 下拉框
            self.repo_combo.blockSignals(True)
            self.repo_combo.clear()
            for r in repos:
                self.repo_combo.addItem(r.name, userData=r)

            if repos:
                idx = 0
                if rid:
                    for i in range(self.repo_combo.count()):
                        rr: GitRepo = self.repo_combo.itemData(i)
                        if rr and rr.id == rid:
                            idx = i
                            break
                self.repo_combo.setCurrentIndex(idx)
            self.repo_combo.blockSignals(False)

            self._fill_branches(branches)
            self.status.setText(f"刷新完成：repos={len(repos)} branches={len(branches)}")
            
            if callback:
                callback()

        QtCore.QTimer.singleShot(80, self, finish)

    def _fill_branches(self, branches: list[GitBranch]) -> None:
        self._branches = [b.short for b in (branches or []) if getattr(b, "short", None)]

    def _update_push_enabled(self) -> None:
        has_local = bool((self.repo_path.text() or "").strip())
        self.push_list.setEnabled(has_local)
        self.btn_add_push.setEnabled(has_local)
        self.btn_del_push.setEnabled(has_local)
        self.push_hint.setVisible(True)

    def _on_repo_changed(self) -> None:
        # require explicit refresh to pull branches
        return

    def _deploy_target_args(self) -> dict | None:
        proj = self._selected_project()
        if not proj:
            show_error_dialog(self, "错误", "请先选择项目")
            return None
        lib = self._selected_library(proj)
        if not lib:
            show_error_dialog(self, "错误", "项目未关联代码库")
            return None
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(self, "错误", "该代码库未保存 PAT")
            return None
        collection = project_entry_collection(proj)
        project_name = project_entry_name(proj)
        if not collection or not project_name:
            show_error_dialog(self, "错误", "项目配置缺少 collection/project")
            return None
        return {
            "parent": self,
            "base_url": lib.base_url,
            "collection": collection,
            "project": project_name,
            "pat": pat,
        }

    def _refresh_target_combo(self, *, select_name: str | None = None) -> None:
        self.deploy_target_combo.blockSignals(True)
        self.deploy_target_combo.clear()
        idx = 0
        for i, t in enumerate(self._targets):
            self.deploy_target_combo.addItem(t.name, userData=i)
            if select_name and t.name == select_name:
                idx = i
        if self._targets:
            self.deploy_target_combo.setCurrentIndex(idx)
        self.deploy_target_combo.blockSignals(False)

    def _selected_target_index(self) -> int | None:
        v = self.deploy_target_combo.currentData()
        return int(v) if v is not None else None

    def _new_deploy_target(self) -> None:
        args = self._deploy_target_args()
        if not args:
            return
        # DeployTargetDialog expects target (required)
        dlg = DeployTargetDialog(**args, target=DeployTarget())
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        t = dlg.result_target()
        if not t:
            return
        self._targets.append(t)
        self._refresh_target_combo(select_name=t.name)

    def _edit_deploy_target(self) -> None:
        idx = self._selected_target_index()
        if idx is None:
            return
        existing = self._targets[idx]
        args = self._deploy_target_args()
        if not args:
            return
        dlg = DeployTargetDialog(**args, target=existing)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        t = dlg.result_target()
        if not t:
            return
        self._targets[idx] = t
        self._refresh_target_combo(select_name=t.name)

    def _delete_deploy_target(self) -> None:
        idx = self._selected_target_index()
        if idx is None:
            return
        t = self._targets[idx]
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除发布目标：{t.name}？")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self._targets.pop(idx)
        self._refresh_target_combo()

    def accept(self) -> None:
        cmd = (self.cmd_edit.text() or "").strip().lower()
        desc = (self.desc_edit.text() or "").strip()
        # No separate name; keep for back-compat but derive from cmd.
        name = cmd

        if not cmd or not _CMD_RE.match(cmd):
            show_error_dialog(self, "错误", "TG 命令只允许 a-z0-9_，长度 1-32")
            return

        proj_id = self.project_combo.currentData()
        local_repo_path = (self.repo_path.text() or "").strip()
        # local repo path is optional: if empty, task may run git flow via PAT (remote) or skip git.

        repo: GitRepo | None = self.repo_combo.currentData()
        repo_id = repo.id if repo else None
        repo_name = repo.name if repo else None

        build_branch = (self.build_branch.text() or "").strip()
        update_branches = self._get_list(self.update_list)
        push_branches = self._get_list(self.push_list)
        merges = self._get_merge_list(self.merge_list)

        if not build_branch:
            show_error_dialog(self, "错误", "请指定【构建分支】")
            return

        for i, mr in enumerate(merges, start=1):
            if not mr.source or not mr.target:
                show_error_dialog(self, "错误", f"第 {i} 条合并规则不完整")
                return

        if not self._targets:
            show_error_dialog(self, "错误", "请至少新增一个发布目标")
            return

        git_flow = GitFlow(build_branch=build_branch, update_branches=update_branches, merges=merges, push_branches=push_branches)

        self._result = DynamicTaskConfig(
            id=self._task.id or str(uuid.uuid4()),
            enabled=self._task.enabled,
            sort_order=int(getattr(self._task, "sort_order", 0) or 0),
            name=name,
            tg_command=cmd,
            tg_desc=desc,
            project_id=str(proj_id) if proj_id else None,
            local_repo_path=local_repo_path,
            repo_id=repo_id,
            repo_name=repo_name,
            git_flow=git_flow,
            targets=list(self._targets),
        )

        super().accept()
