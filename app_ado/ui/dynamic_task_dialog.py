from __future__ import annotations

import re
import uuid

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, ComboBox, LineEdit, PushButton

from app_ado.ado_http import GitBranch, GitRepo, list_branches, list_repos
from app_ado.models import DeployTarget, DynamicTaskConfig, GitFlow, GitMergeRule, UiSettings
from app_ado.secrets import get_pat
from app_ado.ado_build_http import BuildPipeline
from app_ado.ado_http import list_build_definitions, list_build_pipelines
from app_ado.ado_release_http import get_release_stages, list_release_definitions
from app_ado.ui.deploy_target_dialog import DeployTargetDialog
from app_ado.ui.dialogs import show_error_dialog


_CMD_RE = re.compile(r"^[a-z0-9_]{1,32}$")


class DynamicTaskConfigDialog(QtWidgets.QDialog):
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
        self.name_edit = LineEdit(); self.name_edit.setFixedWidth(420)
        self.cmd_edit = LineEdit(); self.cmd_edit.setFixedWidth(260)
        self.desc_edit = LineEdit(); self.desc_edit.setFixedWidth(420)

        # project/repo
        self.project_combo = combo()
        for p in settings.projects:
            self.project_combo.addItem(p.project, userData=p.id)

        self.repo_path = LineEdit(); self.repo_path.setFixedWidth(420)
        self.btn_pick_path = PushButton("选择...")

        self.repo_combo = combo()
        self.source_combo = combo()
        self.target_combo = combo()

        self.chk_merge = QtWidgets.QCheckBox("包含合并（source -> target）")

        # targets
        self.deploy_target_combo = combo()
        self.btn_new_target = PushButton("新增")
        self.btn_edit_target = PushButton("编辑")
        self.btn_del_target = PushButton("删除")

        self.btn_refresh = PushButton("刷新 Repo/分支")
        self.btn_refresh_build = PushButton("刷新构建列表")
        self.btn_refresh_release = PushButton("刷新发布/阶段")

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        form.addRow("任务名称", self.name_edit)
        form.addRow("TG 命令（/xxx）", self.cmd_edit)
        form.addRow("TG 说明", self.desc_edit)
        form.addRow("项目", self.project_combo)
        form.addRow("本地仓库路径", self._row(self.repo_path, self.btn_pick_path))
        form.addRow("仓库(Repo)", self.repo_combo)
        form.addRow("Git 流程", self.chk_merge)
        form.addRow("源分支（要合并的）", self.source_combo)
        form.addRow("目标分支" , self.target_combo)
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
        self.btn_refresh.clicked.connect(self._refresh_repos_and_branches)
        self.repo_combo.currentIndexChanged.connect(self._on_repo_changed)
        self.chk_merge.stateChanged.connect(self._on_merge_toggle)

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

        # infer merge mode
        has_merge = bool(getattr(task.git_flow, "merges", []) or [])
        self.chk_merge.setChecked(has_merge)

        # echo saved values if not yet loaded
        if task.repo_name:
            if self.repo_combo.count() == 0:
                self.repo_combo.addItem(task.repo_name, userData=GitRepo(id=task.repo_id or "", name=task.repo_name))
            self.repo_combo.setCurrentIndex(0)

        # fill branches from git_flow
        src = ""
        tgt = ""
        if has_merge and task.git_flow.merges:
            src = task.git_flow.merges[0].source
            tgt = task.git_flow.merges[0].target
        else:
            # pick first update branch as target
            if task.git_flow.update_branches:
                tgt = task.git_flow.update_branches[0]

        if src:
            if self.source_combo.count() == 0:
                self.source_combo.addItem(src, userData=GitBranch(name=f"refs/heads/{src}"))
            self.source_combo.setCurrentIndex(0)
        if tgt:
            if self.target_combo.count() == 0:
                self.target_combo.addItem(tgt, userData=GitBranch(name=f"refs/heads/{tgt}"))
            self.target_combo.setCurrentIndex(0)

        self._on_merge_toggle()

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
        return next((p for p in self._settings.projects if p.id == pid), None)

    def _selected_library(self, project):
        return next((l for l in self._settings.libraries if l.id == project.library_id), None)

    def _set_loading(self, on: bool, msg: str = "") -> None:
        self.btn_refresh.setEnabled(not on)
        if msg:
            self.status.setText(msg)

    def _refresh_repos_and_branches(self) -> None:
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

        self._set_loading(True, "刷新 Repo/分支...")

        import threading

        result: dict | Exception | None = None

        def run():
            nonlocal result
            try:
                repos = list_repos(lib.base_url, proj.collection, proj.project, pat=pat)
                rid = self._task.repo_id or (repos[0].id if repos else None)
                branches: list[GitBranch] = []
                if rid:
                    branches = list_branches(lib.base_url, proj.collection, proj.project, rid, pat=pat)
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

            self._fill_branches(branches)
            self.status.setText(f"刷新完成：repos={len(repos)} branches={len(branches)}")

        QtCore.QTimer.singleShot(80, self, finish)

    def _fill_branches(self, branches: list[GitBranch]) -> None:
        self.source_combo.clear()
        self.target_combo.clear()
        for b in branches:
            self.source_combo.addItem(b.short, userData=b)
            self.target_combo.addItem(b.short, userData=b)

    def _on_repo_changed(self) -> None:
        # require explicit refresh to pull branches
        return

    def _on_merge_toggle(self) -> None:
        needs = self.chk_merge.isChecked()
        lbl = self.layout().itemAt(0).layout().labelForField(self.source_combo)  # type: ignore
        if lbl:
            lbl.setVisible(needs)
        self.source_combo.setVisible(needs)

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
        dlg = DeployTargetDialog(self, target=None)
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
        dlg = DeployTargetDialog(self, target=existing)
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
        name = (self.name_edit.text() or "").strip()
        cmd = (self.cmd_edit.text() or "").strip().lower()
        desc = (self.desc_edit.text() or "").strip()

        if not name:
            show_error_dialog(self, "错误", "请输入任务名称")
            return
        if not cmd or not _CMD_RE.match(cmd):
            show_error_dialog(self, "错误", "TG 命令只允许 a-z0-9_，长度 1-32")
            return

        proj_id = self.project_combo.currentData()
        local_repo_path = (self.repo_path.text() or "").strip()
        if not local_repo_path:
            show_error_dialog(self, "错误", "请填写本地仓库路径")
            return

        repo: GitRepo | None = self.repo_combo.currentData()
        repo_id = repo.id if repo else None
        repo_name = repo.name if repo else None

        needs_merge = self.chk_merge.isChecked()
        src: GitBranch | None = self.source_combo.currentData() if needs_merge else None
        tgt: GitBranch | None = self.target_combo.currentData()

        if needs_merge and not src:
            show_error_dialog(self, "错误", "请选择源分支")
            return
        if not tgt:
            show_error_dialog(self, "错误", "请选择目标分支")
            return

        if not self._targets:
            show_error_dialog(self, "错误", "请至少新增一个发布目标")
            return

        if needs_merge:
            git_flow = GitFlow(
                update_branches=[src.short, tgt.short],
                merges=[GitMergeRule(source=src.short, target=tgt.short)],
                push_branches=[tgt.short],
            )
        else:
            git_flow = GitFlow(update_branches=[tgt.short], merges=[], push_branches=[])

        self._result = DynamicTaskConfig(
            id=self._task.id or str(uuid.uuid4()),
            enabled=self._task.enabled,
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
