from __future__ import annotations

import json
from dataclasses import asdict

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import ComboBox, LineEdit, PushButton

from app_ado.ado_http import GitBranch, GitRepo, list_branches, list_repos
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

        self.setWindowTitle("配置任务：同步/合并 + 构建 + 发布")
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

        self.repo_path = LineEdit(); self.repo_path.setFixedWidth(420)
        self.btn_pick_path = PushButton("选择...")

        self.btn_refresh = PushButton("刷新 Repo/分支")
        self.btn_refresh.clicked.connect(self._refresh_repos_and_branches)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        form.addRow("项目", self.project_combo)
        form.addRow("本地仓库路径", self._row(self.repo_path, self.btn_pick_path))
        form.addRow("仓库(Repo)", self.repo_combo)
        form.addRow("源分支（要合并的）", self.source_combo)
        form.addRow("目标分支（合并到）", self.target_combo)

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
        if flow.repo_name:
            self.repo_combo.setCurrentText(flow.repo_name)
        if flow.source_branch:
            self.source_combo.setCurrentText(flow.source_branch)
        if flow.target_branch:
            self.target_combo.setCurrentText(flow.target_branch)

        # store local path in build_name field for now? (we'll add real field later)
        # Use Qt dynamic property for now
        self.repo_path.setText(getattr(flow, "local_repo_path", "") if hasattr(flow, "local_repo_path") else "")

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

        self._set_loading(True, "刷新中...")

        import threading

        result: dict | Exception | None = None

        def run():
            nonlocal result
            try:
                repos = list_repos(lib.base_url, proj.collection, proj.project, pat=pat)
                # pick repo
                want_repo_id = self._flow.repo_id
                rid = want_repo_id or (repos[0].id if repos else None)
                branches: list[GitBranch] = []
                if rid:
                    branches = list_branches(lib.base_url, proj.collection, proj.project, rid, pat=pat)
                result = {
                    "repos": repos,
                    "repo_id": rid,
                    "branches": branches,
                }
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

        if not rr or not sb or not tb:
            show_error_dialog(self, "错误", "请刷新并选择 Repo/分支")
            return

        local_path = self.repo_path.text().strip()
        if not local_path:
            show_error_dialog(self, "错误", "请选择本地仓库路径")
            return

        # store extra attribute (temporary)
        updated = self._flow.model_copy(
            update={
                "project_id": proj.id,
                "repo_id": rr.id,
                "repo_name": rr.name,
                "source_branch": sb.short,
                "target_branch": tb.short,
            }
        )
        setattr(updated, "local_repo_path", local_path)
        self._result = updated
        super().accept()
