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
            targets = discover_build_targets(self.base_url, self.collection, self.pat, project=self.project)
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


class BranchesWorker(QtCore.QObject):
    ok = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, base_url: str, collection: str, project: str, pat: str, repo_id: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.collection = collection
        self.project = project
        self.pat = pat
        self.repo_id = repo_id

    @QtCore.Slot()
    def run(self) -> None:
        try:
            branches = list_branches(self.base_url, self.collection, self.project, self.repo_id, self.pat)
            self.ok.emit({"branches": branches, "repo_id": self.repo_id})
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:400]
            self.failed.emit(f"HTTP {e.response.status_code}: {body}")
        except Exception as e:
            self.failed.emit(str(e))


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

        def setup_combo(cb: QtWidgets.QComboBox, *, min_w: int = 520, popup_w: int = 720) -> None:
            cb.setMinimumWidth(min_w)
            cb.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(28)
            # Make popup wide enough to read long names
            try:
                cb.view().setMinimumWidth(popup_w)
            except Exception:
                pass

        self.repo_combo = QtWidgets.QComboBox()
        self.repo_combo.setEditable(True)
        self.repo_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.repo_combo.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.repo_combo.completer().setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        setup_combo(self.repo_combo)

        self.source_combo = QtWidgets.QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.source_combo.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.source_combo.completer().setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        setup_combo(self.source_combo, popup_w=520)

        self.target_combo = QtWidgets.QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.target_combo.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.target_combo.completer().setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        setup_combo(self.target_combo, popup_w=520)

        self.build_combo = QtWidgets.QComboBox()
        self.build_combo.setEditable(True)
        self.build_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.build_combo.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.build_combo.completer().setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        setup_combo(self.build_combo, popup_w=820)

        self.release_combo = QtWidgets.QComboBox()
        self.release_combo.setEditable(True)
        self.release_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.release_combo.completer().setFilterMode(QtCore.Qt.MatchContains)
        self.release_combo.completer().setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        setup_combo(self.release_combo, popup_w=820)

        setup_combo(self.project_combo, min_w=520, popup_w=520)

        self.refresh_btn = QtWidgets.QPushButton("刷新 Repo/Branches/Build")
        self.refresh_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.refresh_btn.clicked.connect(self._refresh_all)

        self.stop_btn = QtWidgets.QPushButton("停止")
        self.stop_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.stop_btn.clicked.connect(self._cancel_refresh)
        self.stop_btn.setEnabled(False)

        self.refresh_branches_btn = QtWidgets.QPushButton("刷新分支")
        self.refresh_branches_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.refresh_branches_btn.clicked.connect(self._refresh_branches)
        self.refresh_branches_btn.setEnabled(True)

        self.stop_branches_btn = QtWidgets.QPushButton("停止")
        self.stop_branches_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.stop_branches_btn.clicked.connect(self._cancel_branches)
        self.stop_branches_btn.setEnabled(False)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)

        form.addRow("项目", self.project_combo)
        form.addRow("仓库", self.repo_combo)
        form.addRow("源分支（要合并的）", self.source_combo)
        form.addRow("目标分支（合并到）", self.target_combo)
        form.addRow("构建流水线", self.build_combo)
        form.addRow("发布流水线", self.release_combo)
        root.addLayout(form)

        refresh_row = QtWidgets.QHBoxLayout()
        refresh_row.setSpacing(10)
        refresh_row.addWidget(self.refresh_btn)
        refresh_row.addWidget(self.stop_btn)
        refresh_row.addStretch(1)
        root.addLayout(refresh_row)

        branches_row = QtWidgets.QHBoxLayout()
        branches_row.setSpacing(10)
        branches_row.addWidget(self.refresh_branches_btn)
        branches_row.addWidget(self.stop_branches_btn)
        branches_row.addStretch(1)
        root.addLayout(branches_row)

        root.addWidget(self.status)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._thread: QtCore.QThread | None = None
        self._worker: QtCore.QObject | None = None
        self._watchdog: QtCore.QTimer | None = None
        self._refreshing: bool = False
        self._cancelled: bool = False

        self._branches_thread: QtCore.QThread | None = None
        self._branches_worker: QtCore.QObject | None = None
        self._branches_watchdog: QtCore.QTimer | None = None
        self._branches_refreshing: bool = False
        self._branches_cancelled: bool = False

        # load existing
        if flow.project_id:
            for i in range(self.project_combo.count()):
                if self.project_combo.itemData(i) == flow.project_id:
                    self.project_combo.setCurrentIndex(i)
                    break

        # Manual refresh is safer (avoids auto threads on open)
        self.project_combo.currentIndexChanged.connect(lambda _: self._on_project_change())
        self.repo_combo.currentIndexChanged.connect(lambda _: self._on_repo_change())

        self.status.setText("提示：先点『刷新 Repo/Branches/Build』拉取仓库/分支/流水线，然后选择：把【源分支】合并到【目标分支】。")

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
                self._worker = None

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
        self._worker = None

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
            self._worker = None

        t.timeout.connect(fire)
        t.start(ms)
        self._watchdog = t

    def _set_branches_refreshing(self, on: bool, msg: str = "") -> None:
        # must have repo selected to refresh branches
        has_repo = isinstance(self.repo_combo.currentData(), GitRepo)
        self.refresh_branches_btn.setEnabled((not on) and has_repo)
        self.stop_branches_btn.setEnabled(on)
        if on:
            self.status.setText(msg)

    def _cleanup_branches(self, *, block: bool = True) -> None:
        if self._branches_watchdog is not None:
            try:
                self._branches_watchdog.stop()
            except Exception:
                pass
            self._branches_watchdog = None

        if self._branches_thread is not None:
            try:
                self._branches_thread.requestInterruption()
                self._branches_thread.quit()
                if block:
                    self._branches_thread.wait(1200)
            except Exception:
                pass
            if block:
                self._branches_thread = None
                self._branches_worker = None

    def _start_branches_watchdog(self, ms: int = 12000) -> None:
        t = QtCore.QTimer(self)
        t.setSingleShot(True)

        def fire() -> None:
            if not self._branches_refreshing:
                return
            self._branches_cancelled = True
            self._branches_refreshing = False
            self._set_branches_refreshing(False)
            if self.status.text().startswith("刷新分支"):
                self.status.setText(f"刷新分支超时（>{ms//1000}s）。可能是网络/权限问题，建议重试")
            self._cleanup_branches(block=False)
            self._branches_thread = None
            self._branches_worker = None

        t.timeout.connect(fire)
        t.start(ms)
        self._branches_watchdog = t

    def _cancel_branches(self) -> None:
        if not self._branches_refreshing:
            return
        self._branches_cancelled = True
        self._branches_refreshing = False
        self._set_branches_refreshing(False)
        self.status.setText("已停止刷新分支（如果网络请求仍在进行，会在后台自行结束）")
        self._cleanup_branches(block=False)
        self._branches_thread = None
        self._branches_worker = None

    def _refresh_branches(self) -> None:
        if self._branches_refreshing:
            self.status.setText("正在刷新分支中，请稍候或点击『停止』")
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
        rr: GitRepo | None = self.repo_combo.currentData()
        if not rr:
            self.status.setText("请先选择 Repo，才能刷新分支")
            return

        self.source_combo.clear()
        self.target_combo.clear()

        self._branches_cancelled = False
        self._branches_refreshing = True
        self._set_branches_refreshing(True, f"刷新分支中：{rr.name} ...")
        self._cleanup_branches(block=False)
        self._branches_thread = None
        self._start_branches_watchdog()

        worker = BranchesWorker(lib.base_url, p.collection, p.project, pat, rr.id)
        self._branches_worker = worker  # keep Python ref
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.ok.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def ok(payload: dict) -> None:
            if self._branches_cancelled:
                return
            self._branches_refreshing = False
            self._set_branches_refreshing(False)
            branches: list[GitBranch] = payload.get("branches") or []
            for b in branches:
                self.source_combo.addItem(b.short, userData=b)
                self.target_combo.addItem(b.short, userData=b)
            if branches:
                self.source_combo.setCurrentIndex(0)
                self.target_combo.setCurrentIndex(0)
            self.status.setText(f"分支刷新完成：{len(branches)}")

        def fail(msg: str) -> None:
            if self._branches_cancelled:
                return
            self._branches_refreshing = False
            self._set_branches_refreshing(False)
            self.status.setText(f"刷新分支失败：{msg}")

        worker.ok.connect(ok)
        worker.failed.connect(fail)

        def _done() -> None:
            if self._branches_refreshing and (not self._branches_cancelled) and self.status.text().startswith("刷新分支"):
                self._branches_refreshing = False
                self._set_branches_refreshing(False)
                self.status.setText("刷新分支已结束但未收到结果（可能是线程/网络异常）。请重试")

        thread.finished.connect(_done)
        thread.finished.connect(lambda: self._cleanup_branches(block=False))

        self._branches_thread = thread
        thread.start()

    def closeEvent(self, event) -> None:
        # Ensure background refresh thread is stopped
        self._cleanup()
        self._cleanup_branches()
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
        # changing repo should allow refresh branches
        self.source_combo.clear()
        self.target_combo.clear()
        self.status.setText("Repo 已切换：可点击『刷新分支』")
        self._set_branches_refreshing(False)

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
        self._worker = worker  # keep Python ref; avoid GC before thread starts
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

        # allow manual typing (editable combos): match typed text back to items
        if rr is None:
            t = self.repo_combo.currentText().strip()
            for i in range(self.repo_combo.count()):
                r: GitRepo = self.repo_combo.itemData(i)
                if r and r.name == t:
                    rr = r
                    break
        if sb is None:
            t = self.source_combo.currentText().strip()
            for i in range(self.source_combo.count()):
                b: GitBranch = self.source_combo.itemData(i)
                if b and b.short == t:
                    sb = b
                    break
        if tb is None:
            t = self.target_combo.currentText().strip()
            for i in range(self.target_combo.count()):
                b: GitBranch = self.target_combo.itemData(i)
                if b and b.short == t:
                    tb = b
                    break
        if bt is None:
            t = self.build_combo.currentText().strip()
            for i in range(self.build_combo.count()):
                b: BuildTarget = self.build_combo.itemData(i)
                if b and f"{b.name} ({b.kind}:{b.id})" == t:
                    bt = b
                    break
        if rt is None:
            t = self.release_combo.currentText().strip()
            for i in range(self.release_combo.count()):
                b: BuildTarget = self.release_combo.itemData(i)
                if b and f"{b.name} ({b.kind}:{b.id})" == t:
                    rt = b
                    break

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
