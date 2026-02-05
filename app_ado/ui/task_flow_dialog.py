from __future__ import annotations

import json
from dataclasses import asdict

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import ComboBox, LineEdit, PushButton

from app_ado.ado_http import (
    BuildPipeline,
    GitBranch,
    GitRepo,
    list_branches,
    list_build_definitions,
    list_build_pipelines,
    list_repos,
)
from app_ado.ado_release_http import ReleaseDefinition, ReleaseStage, get_release_stages, list_release_definitions
from app_ado.models import FlowTaskConfig, UiSettings
from app_ado.secrets import get_pat
from app_ado.store import load_ui_settings
from app_ado.ui.dialogs import show_error_dialog, toast


class FlowTaskConfigDialog(QtWidgets.QDialog):
    def __init__(self, parent, *, settings: UiSettings, flow: FlowTaskConfig):
        super().__init__(parent)
        self._settings = settings
        self._flow = flow
        self._result: FlowTaskConfig | None = None
        self._needs_merge = flow.id != "sync_build_release"

        self.setWindowTitle(
            "配置任务：同步/合并 + 构建 + 发布" if self._needs_merge else "配置任务：同步 + 构建 + 发布"
        )
        self.setModal(True)
        self.resize(760, 560)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        root.addLayout(form)

        def combo() -> ComboBox:
            cb = ComboBox(); cb.setFixedWidth(260)
            return cb

        self.project_combo = combo()
        for p in settings.projects:
            self.project_combo.addItem(p.project, userData=p.id)

        # QFluentWidgets ComboBox doesn't support setEditable; keep it selectable only.
        self.repo_combo = combo()
        self.source_combo = combo()
        self.target_combo = combo()

        self.build_combo = combo()
        self.release_combo = combo()

        self.stage_list = QtWidgets.QListWidget()
        self.stage_list.setFixedHeight(180)

        # deploy targets (multi): handled via separate dialogs; selection + CRUD
        self.deploy_target_combo = combo()
        self.btn_new_target = PushButton("新增")
        self.btn_edit_target = PushButton("编辑")
        self.btn_del_target = PushButton("删除")

        self.btn_new_target.clicked.connect(self._new_deploy_target)
        self.btn_edit_target.clicked.connect(self._edit_deploy_target)
        self.btn_del_target.clicked.connect(self._delete_deploy_target)

        self.repo_path = LineEdit(); self.repo_path.setFixedWidth(420)
        self.btn_pick_path = PushButton("选择...")

        self.btn_refresh = PushButton("刷新 Repo/分支")
        self.btn_refresh.clicked.connect(self._refresh_repos_and_branches)

        self.btn_refresh_build = PushButton("刷新构建列表")
        self.btn_refresh_build.clicked.connect(self._refresh_builds)

        self.btn_refresh_release = PushButton("刷新发布/阶段")
        self.btn_refresh_release.clicked.connect(self._refresh_releases)

        self.release_combo.currentIndexChanged.connect(self._on_release_changed)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        form.addRow("项目", self.project_combo)
        form.addRow("本地仓库路径", self._row(self.repo_path, self.btn_pick_path))
        form.addRow("仓库(Repo)", self.repo_combo)
        form.addRow("源分支（要合并的）", self.source_combo)
        form.addRow("分支" if not self._needs_merge else "目标分支", self.target_combo)

        if not self._needs_merge:
            # Hide source branch row for sync+build+release task
            lbl = form.labelForField(self.source_combo)
            if lbl:
                lbl.setVisible(False)
            self.source_combo.setVisible(False)

        # Deploy targets (multiple build+release+stages)
        form.addRow("发布目标", self._row(self.deploy_target_combo, self._row(self.btn_new_target, self._row(self.btn_edit_target, self.btn_del_target))))

        root.addWidget(self.btn_refresh)
        root.addWidget(self.status)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self.btn_pick_path.clicked.connect(self._pick_path)
        self.repo_combo.currentIndexChanged.connect(self._on_repo_changed)

        # prefill
        if flow.project_id:
            for i in range(self.project_combo.count()):
                if self.project_combo.itemData(i) == flow.project_id:
                    self.project_combo.setCurrentIndex(i)
                    break
        # QFluentWidgets ComboBox is selection-only; to "echo" saved values we must ensure they exist as items.
        if flow.repo_name:
            if self.repo_combo.count() == 0:
                self.repo_combo.addItem(flow.repo_name, userData=GitRepo(id=flow.repo_id or "", name=flow.repo_name))
            self.repo_combo.setCurrentIndex(0)
        if flow.source_branch:
            if self.source_combo.count() == 0:
                self.source_combo.addItem(flow.source_branch, userData=GitBranch(name=f"refs/heads/{flow.source_branch}"))
            self.source_combo.setCurrentIndex(0)
        if flow.target_branch:
            if self.target_combo.count() == 0:
                self.target_combo.addItem(flow.target_branch, userData=GitBranch(name=f"refs/heads/{flow.target_branch}"))
            self.target_combo.setCurrentIndex(0)

        # migrate single-target fields into targets if needed
        from app_ado.models import DeployTarget

        self._targets = list(flow.targets or [])
        if not self._targets and (flow.build_id or flow.release_id or (flow.release_stage_ids or [])):
            self._targets = [
                DeployTarget(
                    name="目标1",
                    enabled=True,
                    build_kind=flow.build_kind,
                    build_id=flow.build_id,
                    build_name=flow.build_name,
                    release_id=flow.release_id,
                    release_name=flow.release_name,
                    release_stage_ids=list(flow.release_stage_ids or []),
                    release_stage_names=list(flow.release_stage_names or []),
                )
            ]
        self._refresh_target_combo()

        self.repo_path.setText(flow.local_repo_path)

    def _row(self, a: QtWidgets.QWidget, b: QtWidgets.QWidget) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(a)
        h.addWidget(b)
        h.addStretch(1)
        return w

    def result_config(self) -> FlowTaskConfig | None:
        return self._result

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
        self.btn_refresh_build.setEnabled(not on)
        self.btn_refresh_release.setEnabled(not on)
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
                want_repo_id = self._flow.repo_id
                rid = want_repo_id or (repos[0].id if repos else None)
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
                QtCore.QTimer.singleShot(80, finish)
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

        QtCore.QTimer.singleShot(80, finish)

    def _refresh_builds(self) -> None:
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

        self._set_loading(True, "刷新构建列表...")
        import threading

        result: dict | Exception | None = None

        def run():
            nonlocal result
            try:
                try:
                    items = list_build_pipelines(lib.base_url, proj.collection, proj.project, pat=pat)
                except Exception:
                    items = list_build_definitions(lib.base_url, proj.collection, proj.project, pat=pat)
                result = {"items": items}
            except Exception as e:
                result = e

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish():
            nonlocal result
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            self._set_loading(False)
            if isinstance(result, Exception):
                show_error_dialog(self, "刷新失败", str(result))
                return
            assert isinstance(result, dict)
            items: list[BuildPipeline] = result.get("items") or []

            self.build_combo.clear()
            for it in items:
                self.build_combo.addItem(it.name, userData=it)

            # preserve selection
            want_id = self._flow.build_id
            if items:
                idx = 0
                if want_id:
                    for i in range(self.build_combo.count()):
                        bb: BuildPipeline = self.build_combo.itemData(i)
                        if bb and bb.id == want_id:
                            idx = i
                            break
                self.build_combo.setCurrentIndex(idx)

            kinds = {it.kind for it in items}
            self.status.setText(f"刷新完成：builds={len(items)} ({', '.join(sorted(kinds))})")

        QtCore.QTimer.singleShot(80, finish)

    def _refresh_releases(self) -> None:
        # Preserve current release selection when refreshing
        current_def: ReleaseDefinition | None = self.release_combo.currentData()
        want_release_id = (current_def.id if current_def and current_def.id else None) or self._flow.release_id

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

        self._set_loading(True, "刷新发布/阶段...")
        import threading

        result: dict | Exception | None = None

        def run():
            nonlocal result
            try:
                # some servers require api-version=6.0 for release
                try:
                    defs = list_release_definitions(lib.base_url, proj.collection, proj.project, pat=pat, api_version="7.0")
                    api_used = "7.0"
                except Exception:
                    defs = list_release_definitions(lib.base_url, proj.collection, proj.project, pat=pat, api_version="6.0")
                    api_used = "6.0"

                rid = want_release_id or (defs[0].id if defs else None)
                stages: list[ReleaseStage] = []
                if rid:
                    try:
                        stages = get_release_stages(lib.base_url, proj.collection, proj.project, rid, pat=pat, api_version=api_used)
                    except Exception:
                        # try 6.0 fallback
                        stages = get_release_stages(lib.base_url, proj.collection, proj.project, rid, pat=pat, api_version="6.0")
                result = {"defs": defs, "rid": rid, "stages": stages}
            except Exception as e:
                result = e

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish():
            nonlocal result
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            self._set_loading(False)
            if isinstance(result, Exception):
                show_error_dialog(self, "刷新失败", str(result))
                return
            assert isinstance(result, dict)
            defs: list[ReleaseDefinition] = result.get("defs") or []
            rid = result.get("rid")
            stages: list[ReleaseStage] = result.get("stages") or []

            self.release_combo.clear()
            for d in defs:
                self.release_combo.addItem(d.name, userData=d)

            if defs:
                idx = 0
                if rid:
                    for i in range(self.release_combo.count()):
                        dd: ReleaseDefinition = self.release_combo.itemData(i)
                        if dd and dd.id == rid:
                            idx = i
                            break
                self.release_combo.setCurrentIndex(idx)

            self._fill_stages(stages)
            self.status.setText(f"刷新完成：releases={len(defs)} stages={len(stages)}")

        QtCore.QTimer.singleShot(80, finish)

    def _on_release_changed(self) -> None:
        # stages are loaded on refresh; change selection doesn't auto-fetch in v1.
        pass

    def _fill_stages(self, stages: list[ReleaseStage]) -> None:
        want_ids = set(self._flow.release_stage_ids or [])
        self.stage_list.clear()
        for s in stages:
            it = QtWidgets.QListWidgetItem(s.name)
            it.setData(QtCore.Qt.UserRole, s.id)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if s.id in want_ids else QtCore.Qt.Unchecked)
            self.stage_list.addItem(it)

    def _fill_branches(self, branches: list[GitBranch]) -> None:
        want_src = self.source_combo.currentText().strip() or self._flow.source_branch
        want_tgt = self.target_combo.currentText().strip() or self._flow.target_branch

        self.source_combo.clear(); self.target_combo.clear()
        for b in branches:
            self.source_combo.addItem(b.short, userData=b)
            self.target_combo.addItem(b.short, userData=b)

        if branches:
            # pick preserved
            if want_src:
                for i in range(self.source_combo.count()):
                    bb: GitBranch = self.source_combo.itemData(i)
                    if bb and bb.short == want_src:
                        self.source_combo.setCurrentIndex(i)
                        break
            else:
                self.source_combo.setCurrentIndex(0)

            if want_tgt:
                for i in range(self.target_combo.count()):
                    bb: GitBranch = self.target_combo.itemData(i)
                    if bb and bb.short == want_tgt:
                        self.target_combo.setCurrentIndex(i)
                        break
            else:
                self.target_combo.setCurrentIndex(0)

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

    def _current_target_index(self) -> int | None:
        v = self.deploy_target_combo.currentData()
        return int(v) if v is not None else None

    def _new_deploy_target(self) -> None:
        # need project+pat context
        proj = self._selected_project()
        if not proj:
            show_error_dialog(self, "错误", "请先选择项目")
            return
        lib = self._selected_library(proj)
        if not lib:
            show_error_dialog(self, "错误", "项目未关联代码库")
            return
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(self, "错误", "该代码库未保存 PAT")
            return

        from app_ado.models import DeployTarget
        from app_ado.ui.deploy_target_dialog import DeployTargetDialog

        # name auto increment
        n = 1
        existing = {t.name for t in self._targets}
        while True:
            name = f"目标{n}"
            if name not in existing:
                break
            n += 1

        target = DeployTarget(name=name)
        dlg = DeployTargetDialog(self, base_url=lib.base_url, collection=proj.collection, project=proj.project, pat=pat, target=target)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        res = dlg.result_target()
        if not res:
            return
        self._targets.append(res)
        self._refresh_target_combo(select_name=res.name)

    def _edit_deploy_target(self) -> None:
        idx = self._current_target_index()
        if idx is None or idx < 0 or idx >= len(self._targets):
            show_error_dialog(self, "错误", "请先选择发布目标")
            return

        proj = self._selected_project()
        if not proj:
            show_error_dialog(self, "错误", "请先选择项目")
            return
        lib = self._selected_library(proj)
        if not lib:
            show_error_dialog(self, "错误", "项目未关联代码库")
            return
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(self, "错误", "该代码库未保存 PAT")
            return

        from app_ado.ui.deploy_target_dialog import DeployTargetDialog

        cur = self._targets[idx]
        dlg = DeployTargetDialog(self, base_url=lib.base_url, collection=proj.collection, project=proj.project, pat=pat, target=cur)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        res = dlg.result_target()
        if not res:
            return
        self._targets[idx] = res
        self._refresh_target_combo(select_name=res.name)

    def _delete_deploy_target(self) -> None:
        idx = self._current_target_index()
        if idx is None or idx < 0 or idx >= len(self._targets):
            show_error_dialog(self, "错误", "请先选择发布目标")
            return
        t = self._targets[idx]
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除发布目标：{t.name} ？")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self._targets.pop(idx)
        self._refresh_target_combo()

    def _on_repo_changed(self) -> None:
        # In v1 we refresh full list for simplicity
        pass

    def accept(self) -> None:
        proj = self._selected_project()
        if not proj:
            show_error_dialog(self, "错误", "请选择项目")
            return
        rr: GitRepo | None = self.repo_combo.currentData()
        sb: GitBranch | None = self.source_combo.currentData()
        tb: GitBranch | None = self.target_combo.currentData()

        if rr is None:
            # match by text
            t = self.repo_combo.currentText().strip()
            for i in range(self.repo_combo.count()):
                r: GitRepo = self.repo_combo.itemData(i)
                if r and r.name == t:
                    rr = r
                    break
        if sb is None:
            t = self.source_combo.currentText().strip()
            sb = GitBranch(name=f"refs/heads/{t}") if t else None
        if tb is None:
            t = self.target_combo.currentText().strip()
            tb = GitBranch(name=f"refs/heads/{t}") if t else None

        missing: list[str] = []
        if not rr:
            missing.append("- 请选择仓库(Repo)（可先点：刷新 Repo/分支）")
        if self._needs_merge and not sb:
            missing.append("- 请选择源分支（可先点：刷新 Repo/分支）")
        if not tb:
            missing.append("- 请选择目标分支（可先点：刷新 Repo/分支）")

        if missing:
            show_error_dialog(self, "表单未完整", "\n".join(missing))
            return

        local_path = self.repo_path.text().strip()
        if not local_path:
            show_error_dialog(self, "错误", "请选择本地仓库路径")
            return

        bp: BuildPipeline | None = self.build_combo.currentData()
        rd: ReleaseDefinition | None = self.release_combo.currentData()

        stage_ids: list[str] = []
        stage_names: list[str] = []
        for i in range(self.stage_list.count()):
            it = self.stage_list.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                sid = str(it.data(QtCore.Qt.UserRole) or "")
                if sid:
                    stage_ids.append(sid)
                    stage_names.append(it.text())

        if not self._targets:
            show_error_dialog(self, "表单未完整", "- 请至少新增一个发布目标")
            return

        update = {
            "project_id": proj.id,
            "local_repo_path": local_path,
            "repo_id": rr.id,
            "repo_name": rr.name,
            "source_branch": sb.short if self._needs_merge else "",
            "target_branch": tb.short,
        }

        # save targets and keep back-compat fields in sync with first target
        update.update({"targets": [t.model_dump() for t in self._targets]})
        if self._targets:
            t0 = self._targets[0]
            update.update(
                {
                    "build_kind": t0.build_kind,
                    "build_id": t0.build_id,
                    "build_name": t0.build_name,
                    "release_id": t0.release_id,
                    "release_name": t0.release_name,
                    "release_stage_ids": list(t0.release_stage_ids or []),
                    "release_stage_names": list(t0.release_stage_names or []),
                }
            )

        updated = self._flow.model_copy(update=update)
        self._result = updated
        super().accept()
