from __future__ import annotations

import httpx
from PySide6 import QtCore, QtGui, QtWidgets

from ui_app.ado_discovery import BuildTarget, GitBranch, GitRepo, discover_build_targets
from ui_app.ado_git import list_branches, list_repos
from ui_app.library_store import get_pat
from ui_app.settings_store import LibraryEntry, ProjectEntry, UiSettings
from ui_app.tasks_store import FlowTaskConfig


class RefreshWorker(QtCore.QObject):
    ok = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, base_url: str, collection: str, project: str, pat: str, repo_id: str | None) -> None:
        super().__init__()
        self.base_url = base_url
        self.collection = collection
        self.project = project
        self.pat = pat
        self.repo_id = repo_id

    @QtCore.Slot()
    def run(self) -> None:
        # Do best-effort refresh so a 401 on Build doesn't block repos/branches.
        repos: list[GitRepo] = []
        branches: list[GitBranch] = []
        targets: list[BuildTarget] = []
        repo_id: str | None = None
        warnings: list[str] = []

        try:
            repos = list_repos(self.base_url, self.collection, self.project, self.pat)
            repo_id = self.repo_id or (repos[0].id if repos else None)
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:200]
            self.failed.emit(f"repos: HTTP {e.response.status_code}: {body}")
            return
        except Exception as e:
            self.failed.emit(f"repos: {e}")
            return

        if repo_id:
            try:
                branches = list_branches(self.base_url, self.collection, self.project, repo_id, self.pat)
            except httpx.HTTPStatusError as e:
                body = (e.response.text or "")[:200]
                warnings.append(f"branches: HTTP {e.response.status_code}: {body}")
            except Exception as e:
                warnings.append(f"branches: {e}")

        try:
            targets = discover_build_targets(self.base_url, self.collection, self.pat)
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:200]
            warnings.append(f"build targets: HTTP {e.response.status_code}: {body}")
        except Exception as e:
            warnings.append(f"build targets: {e}")

        self.ok.emit({
            "repos": repos,
            "repo_id": repo_id,
            "branches": branches,
            "targets": targets,
            "warnings": warnings,
        })


class FlowTaskDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, *, settings: UiSettings, flow: FlowTaskConfig) -> None:
        super().__init__(parent)
        self._settings = settings
        self._flow = flow
        self._result: FlowTaskConfig | None = None

        self.setWindowTitle("配置：Sync/Merge + Build + Release")
        self.setModal(True)
        self.resize(760, 520)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.project_combo = QtWidgets.QComboBox()
        for p in settings.projects:
            self.project_combo.addItem(p.project, userData=p.id)

        self.repo_combo = QtWidgets.QComboBox()

        self.source_combo = QtWidgets.QComboBox()
        self.target_combo = QtWidgets.QComboBox()

        self.build_combo = QtWidgets.QComboBox()
        self.release_combo = QtWidgets.QComboBox()

        self.refresh_btn = QtWidgets.QPushButton("刷新 Repo/Branches/Build")
        self.refresh_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.refresh_btn.clicked.connect(self._refresh_all)

        self.stop_btn = QtWidgets.QPushButton("停止")
        self.stop_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.stop_btn.clicked.connect(self._cancel_refresh)
        self.stop_btn.setEnabled(False)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)

        form.addRow("Project", self.project_combo)
        form.addRow("Repo", self.repo_combo)
        form.addRow("source_branch", self.source_combo)
        form.addRow("target_branch", self.target_combo)
        form.addRow("Build", self.build_combo)
        form.addRow("Release", self.release_combo)
        root.addLayout(form)

        refresh_row = QtWidgets.QHBoxLayout()
        refresh_row.setSpacing(10)
        refresh_row.addWidget(self.refresh_btn)
        refresh_row.addWidget(self.stop_btn)
        refresh_row.addStretch(1)
        root.addLayout(refresh_row)
        root.addWidget(self.status)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._thread: QtCore.QThread | None = None
        self._watchdog: QtCore.QTimer | None = None
        self._refreshing: bool = False
        self._cancelled: bool = False

        # load existing
        if flow.project_id:
            for i in range(self.project_combo.count()):
                if self.project_combo.itemData(i) == flow.project_id:
                    self.project_combo.setCurrentIndex(i)
                    break

        # Manual refresh is safer (avoids auto threads on open)
        self.project_combo.currentIndexChanged.connect(lambda _: self._on_project_change())
        self.repo_combo.currentIndexChanged.connect(lambda _: self._on_repo_change())

        self.status.setText("请点击『刷新 Repo/Branches/Build』拉取下拉选项")

    def result_flow(self) -> FlowTaskConfig | None:
        return self._result

    def _cleanup(self, *, block: bool = True) -> None:
        if self._watchdog is not None:
            try:
                self._watchdog.stop()
            except Exception:
                pass
            self._watchdog = None

        if self._thread is not None:
            try:
                # Best-effort; may not stop a blocked network call.
                self._thread.requestInterruption()
                self._thread.quit()
                if block:
                    self._thread.wait(1200)
            except Exception:
                pass
            if block:
                self._thread = None

    def _cancel_refresh(self) -> None:
        if not self._refreshing:
            return
        self._cancelled = True
        self._refreshing = False
        self._set_refreshing(False)
        self.status.setText("已停止刷新（如果网络请求仍在进行，会在后台自行结束）")
        # Don't block UI while cancelling.
        self._cleanup(block=False)
        self._thread = None

    def _start_watchdog(self, ms: int = 12000) -> None:
        t = QtCore.QTimer(self)
        t.setSingleShot(True)

        def fire() -> None:
            if not self._refreshing:
                return
            self._cancelled = True
            self._refreshing = False
            # Don't leave UI stuck even if worker never emits.
            self._set_refreshing(False)
            if self.status.text().startswith("刷新中"):
                self.status.setText(f"刷新超时（>{ms//1000}s）。可能是网络/权限问题，建议重试")
            # Don't block UI; background thread may still be in-flight.
            self._cleanup(block=False)
            self._thread = None

        t.timeout.connect(fire)
        t.start(ms)
        self._watchdog = t

    def closeEvent(self, event) -> None:
        # Ensure background refresh thread is stopped
        self._cleanup()
        return super().closeEvent(event)

    def _on_project_change(self) -> None:
        # reset dependent dropdowns
        self.repo_combo.clear()
        self.source_combo.clear()
        self.target_combo.clear()
        self.build_combo.clear()
        self.release_combo.clear()
        self.status.setText("项目已切换：请点击刷新")

    def _on_repo_change(self) -> None:
        # changing repo should refresh branches
        self.source_combo.clear()
        self.target_combo.clear()
        self.status.setText("Repo 已切换：请点击刷新")

    def _selected_project(self) -> ProjectEntry | None:
        pid = self.project_combo.currentData()
        for p in self._settings.projects:
            if p.id == pid:
                return p
        return None

    def _selected_library(self, project: ProjectEntry) -> LibraryEntry | None:
        for lib in self._settings.libraries:
            if lib.id == project.library_id:
                return lib
        return None

    def _set_refreshing(self, on: bool, msg: str = "") -> None:
        self.refresh_btn.setEnabled(not on)
        self.stop_btn.setEnabled(on)
        if on:
            self.status.setText(msg)

    def _refresh_all(self) -> None:
        if self._refreshing:
            self.status.setText("正在刷新中，请稍候或点击『停止』")
            return

        p = self._selected_project()
        if not p:
            self.status.setText("请先在设置里新增项目")
            return
        lib = self._selected_library(p)
        if not lib:
            self.status.setText("项目未关联代码库")
            return
        pat = get_pat(lib.id)
        if not pat:
            self.status.setText("该代码库没有 PAT，请先去设置-代码库里保存 PAT")
            return

        # Keep selected repo if any (read before clearing)
        existing_repo: str | None = None
        d = self.repo_combo.currentData()
        if isinstance(d, GitRepo):
            existing_repo = d.id

        self.repo_combo.clear()
        self.source_combo.clear()
        self.target_combo.clear()
        self.build_combo.clear()
        self.release_combo.clear()

        self._cancelled = False
        self._refreshing = True
        self._set_refreshing(True, f"刷新中：repos/branches/build ({p.project})...")
        # Best-effort cleanup of any prior thread without blocking UI
        self._cleanup(block=False)
        self._thread = None
        self._start_watchdog()

        worker = RefreshWorker(lib.base_url, p.collection, p.project, pat, existing_repo)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.ok.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def _done() -> None:
            # If worker finishes without emitting ok/failed, don't leave UI in "refreshing" state.
            if self._refreshing and (not self._cancelled) and self.status.text().startswith("刷新中"):
                self._refreshing = False
                self._set_refreshing(False)
                self.status.setText("刷新已结束但未收到结果（可能是线程/网络异常）。请重试")

        thread.finished.connect(_done)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup(block=False))

        def ok(payload: dict) -> None:
            if self._cancelled:
                return
            self._refreshing = False
            self._set_refreshing(False)

            repos: list[GitRepo] = payload.get("repos") or []
            repo_id: str | None = payload.get("repo_id")
            branches: list[GitBranch] = payload.get("branches") or []
            targets: list[BuildTarget] = payload.get("targets") or []
            warnings: list[str] = payload.get("warnings") or []

            # repos
            for r in repos:
                self.repo_combo.addItem(r.name, userData=r)
            if repos:
                idx = 0
                if repo_id:
                    for i in range(self.repo_combo.count()):
                        rr: GitRepo = self.repo_combo.itemData(i)
                        if rr and rr.id == repo_id:
                            idx = i
                            break
                self.repo_combo.setCurrentIndex(idx)

            # branches
            for b in branches:
                self.source_combo.addItem(b.short, userData=b)
                self.target_combo.addItem(b.short, userData=b)
            # try to keep previous text if any
            if branches:
                self.source_combo.setCurrentIndex(0)
                self.target_combo.setCurrentIndex(0)

            # build/release
            for t in targets:
                self.build_combo.addItem(f"{t.name} ({t.kind}:{t.id})", userData=t)
                self.release_combo.addItem(f"{t.name} ({t.kind}:{t.id})", userData=t)
            if targets:
                self.build_combo.setCurrentIndex(0)
                self.release_combo.setCurrentIndex(0)

            msg = f"刷新完成：repos={len(repos)} branches={len(branches)} buildTargets={len(targets)}"
            if warnings:
                msg += "\n" + "\n".join([f"⚠️ {w}" for w in warnings][:3])
            self.status.setText(msg)

        def fail(msg: str) -> None:
            if self._cancelled:
                return
            self._refreshing = False
            self._set_refreshing(False)
            self.status.setText(f"刷新失败：{msg}")

        worker.ok.connect(ok)
        worker.failed.connect(fail)

        self._thread = thread
        thread.start()

    def _refresh_branches_only(self) -> None:
        # Keep it simple for v1: full refresh
        self._refresh_all()

    def accept(self) -> None:
        if not self._settings.projects:
            QtWidgets.QMessageBox.warning(self, "错误", "请先在设置里新增项目")
            return

        pid = self.project_combo.currentData()
        rr: GitRepo | None = self.repo_combo.currentData()
        sb: GitBranch | None = self.source_combo.currentData()
        tb: GitBranch | None = self.target_combo.currentData()
        bt: BuildTarget | None = self.build_combo.currentData()
        rt: BuildTarget | None = self.release_combo.currentData()

        if not pid:
            QtWidgets.QMessageBox.warning(self, "错误", "请选择 Project")
            return
        if not rr:
            QtWidgets.QMessageBox.warning(self, "错误", "请选择 Repo")
            return
        if not sb or not tb:
            QtWidgets.QMessageBox.warning(self, "错误", "请选择 source/target 分支")
            return
        if not bt or not rt:
            QtWidgets.QMessageBox.warning(self, "错误", "请先刷新并选择 Build/Release")
            return

        self._result = self._flow.model_copy(
            update={
                "project_id": pid,
                "repo_id": rr.id,
                "repo_name": rr.name,
                "source_branch": sb.short,
                "target_branch": tb.short,
                "build_kind": bt.kind,
                "build_id": bt.id,
                "build_name": bt.name,
                "release_kind": rt.kind,
                "release_id": rt.id,
                "release_name": rt.name,
            }
        )
        super().accept()
