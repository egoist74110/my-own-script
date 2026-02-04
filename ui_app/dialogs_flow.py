from __future__ import annotations

import json

import httpx
from PySide6 import QtCore, QtGui, QtWidgets

from ui_app.ado_discovery import BuildTarget, GitBranch, GitRepo, discover_build_targets
from ui_app.ado_git import list_branches, list_repos
from ui_app.ado_release import ReleaseDef, ReleaseStage, list_release_definitions, list_release_stages
from ui_app.library_store import get_pat
from ui_app.settings_store import LibraryEntry, ProjectEntry, UiSettings
from ui_app.tasks_store import FlowTaskConfig


class RefreshWorker(QtCore.QObject):
    ok = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(str)

    def _pp(self, obj: object, *, limit: int = 12000) -> str:
        try:
            s = json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            s = str(obj)
        if len(s) > limit:
            return s[:limit] + "\n...<truncated>"
        return s

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
        debug: list[str] = []

        debug.append(f"base={self.base_url} collection={self.collection} project={self.project}")
        self.progress.emit("worker: start")

        try:
            self.progress.emit("step: list_repos")
            repos = list_repos(self.base_url, self.collection, self.project, self.pat)
            debug.append(f"repos: {len(repos)}")
            debug.append(self._pp([r.__dict__ for r in repos[:50]]))
            repo_id = self.repo_id or (repos[0].id if repos else None)
            debug.append(f"repo_id: {repo_id}")
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:200]
            self.failed.emit(f"repos: HTTP {e.response.status_code}: {body}")
            return
        except Exception as e:
            self.progress.emit(f"repos exception: {e}")
            self.failed.emit(f"repos: {e}")
            return

        if repo_id:
            try:
                self.progress.emit("step: list_branches")
                branches = list_branches(self.base_url, self.collection, self.project, repo_id, self.pat)
                debug.append(f"branches: {len(branches)}")
                debug.append(self._pp([b.__dict__ for b in branches[:200]]))
            except httpx.HTTPStatusError as e:
                body = (e.response.text or "")[:200]
                warnings.append(f"branches: HTTP {e.response.status_code}: {body}")
            except Exception as e:
                warnings.append(f"branches: {e}")

        try:
            self.progress.emit("step: discover_build_targets")
            targets = discover_build_targets(self.base_url, self.collection, self.pat, project=self.project)
            debug.append(f"build_targets: {len(targets)}")
            debug.append(self._pp([t.__dict__ for t in targets[:200]]))
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:200]
            warnings.append(f"build targets: HTTP {e.response.status_code}: {body}")
        except Exception as e:
            warnings.append(f"build targets: {e}")

        release_defs: list[ReleaseDef] = []
        try:
            self.progress.emit("step: list_release_definitions")
            release_defs = list_release_definitions(self.base_url, self.collection, self.project, self.pat)
            debug.append(f"release_defs: {len(release_defs)}")
            debug.append(self._pp([d.__dict__ for d in release_defs[:200]]))
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:200]
            warnings.append(f"release defs: HTTP {e.response.status_code}: {body}")
        except Exception as e:
            warnings.append(f"release defs: {e}")

        self.ok.emit({
            "repos": repos,
            "repo_id": repo_id,
            "branches": branches,
            "targets": targets,
            "release_defs": release_defs,
            "warnings": warnings,
            "debug": debug,
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


class ReleaseStagesWorker(QtCore.QObject):
    ok = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, base_url: str, collection: str, project: str, pat: str, release_def_id: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.collection = collection
        self.project = project
        self.pat = pat
        self.release_def_id = release_def_id

    @QtCore.Slot()
    def run(self) -> None:
        try:
            stages = list_release_stages(
                self.base_url, self.collection, self.project, self.pat, self.release_def_id
            )
            self.ok.emit({"stages": stages, "release_def_id": self.release_def_id})
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

        self.release_stage_list = QtWidgets.QListWidget()
        self.release_stage_list.setMinimumHeight(160)
        self.release_stage_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.release_stage_list.setObjectName("ReleaseStageList")
        try:
            self.release_stage_list.setMinimumWidth(520)
        except Exception:
            pass

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

        self.refresh_stages_btn = QtWidgets.QPushButton("刷新发布阶段")
        self.refresh_stages_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.refresh_stages_btn.clicked.connect(self._refresh_release_stages)
        self.refresh_stages_btn.setEnabled(True)

        self.stop_stages_btn = QtWidgets.QPushButton("停止")
        self.stop_stages_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.stop_stages_btn.clicked.connect(self._cancel_stages)
        self.stop_stages_btn.setEnabled(False)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)

        self.debug_chk = QtWidgets.QCheckBox("调试：输出请求结果到下方日志")
        self.debug_chk.setChecked(True)
        self.debug_box = QtWidgets.QPlainTextEdit()
        self.debug_box.setReadOnly(True)
        self.debug_box.setMaximumHeight(220)
        self.debug_box.setPlaceholderText("这里会输出每一步请求的结果（会截断），方便定位为什么 UI 没拿到数据")

        form.addRow("项目", self.project_combo)
        form.addRow("仓库", self.repo_combo)
        form.addRow("源分支（要合并的）", self.source_combo)
        form.addRow("目标分支（合并到）", self.target_combo)
        form.addRow("构建流水线", self.build_combo)
        form.addRow("发布流水线", self.release_combo)
        form.addRow("发布到阶段（可多选）", self.release_stage_list)
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

        stages_row = QtWidgets.QHBoxLayout()
        stages_row.setSpacing(10)
        stages_row.addWidget(self.refresh_stages_btn)
        stages_row.addWidget(self.stop_stages_btn)
        stages_row.addStretch(1)
        root.addLayout(stages_row)

        root.addWidget(self.status)
        root.addWidget(self.debug_chk)
        root.addWidget(self.debug_box)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._thread: QtCore.QThread | None = None
        self._worker: QtCore.QObject | None = None
        self._watchdog: QtCore.QTimer | None = None
        self._refreshing: bool = False
        self._cancelled: bool = False
        self._auto_refresh_mode: bool = bool(flow.project_id)
        self._auto_refresh_phase: int = 0

        self._branches_thread: QtCore.QThread | None = None
        self._branches_worker: QtCore.QObject | None = None
        self._branches_watchdog: QtCore.QTimer | None = None
        self._branches_refreshing: bool = False
        self._branches_cancelled: bool = False

        self._stages_thread: QtCore.QThread | None = None
        self._stages_worker: QtCore.QObject | None = None
        self._stages_watchdog: QtCore.QTimer | None = None
        self._stages_refreshing: bool = False
        self._stages_cancelled: bool = False

        # load existing (prefill for editing)
        if flow.project_id:
            for i in range(self.project_combo.count()):
                if self.project_combo.itemData(i) == flow.project_id:
                    self.project_combo.setCurrentIndex(i)
                    break

        # prefill texts so user sees previous values even before refresh
        if flow.repo_name:
            self.repo_combo.setCurrentText(flow.repo_name)
        if flow.source_branch:
            self.source_combo.setCurrentText(flow.source_branch)
        if flow.target_branch:
            self.target_combo.setCurrentText(flow.target_branch)
        if flow.build_name:
            self.build_combo.setCurrentText(flow.build_name)
        if flow.release_name:
            self.release_combo.setCurrentText(flow.release_name)
        # stages are loaded after refresh; keep desired selection in flow

        # Manual refresh is safer (avoids auto threads on open)
        self.project_combo.currentIndexChanged.connect(lambda _: self._on_project_change())
        self.repo_combo.currentIndexChanged.connect(lambda _: self._on_repo_change())
        self.release_combo.currentIndexChanged.connect(lambda _: self._on_release_change())

        self.status.setText("提示：先点『刷新 Repo/Branches/Build』拉取仓库/分支/流水线，然后选择：把【源分支】合并到【目标分支】。")

        # When editing an existing task, auto refresh in order:
        # 1) repos/branches/build/release definitions -> 2) branches -> 3) release stages
        if self._auto_refresh_mode and self._settings.projects:
            QtCore.QTimer.singleShot(0, self._auto_refresh_start)

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

    def _cleanup_specific_thread(self, thread: QtCore.QThread, *, kind: str) -> None:
        """Cleanup a specific thread safely (avoid races where old thread finishes and cancels new thread)."""
        try:
            thread.requestInterruption()
            thread.quit()
        except Exception:
            pass

        if kind == "main":
            if self._thread is thread:
                self._thread = None
                self._worker = None
        elif kind == "branches":
            if self._branches_thread is thread:
                self._branches_thread = None
                self._branches_worker = None
        elif kind == "stages":
            if self._stages_thread is thread:
                self._stages_thread = None
                self._stages_worker = None

    def _auto_refresh_start(self) -> None:
        # Only meaningful if a project is selected.
        if not self._selected_project():
            return
        self._auto_refresh_phase = 1
        self.status.setText("编辑模式：自动刷新中（1/3：Repo/Branches/Build）...")
        self._refresh_all()

    def _cancel_refresh(self) -> None:
        if not self._refreshing:
            return
        self._cancelled = True
        self._refreshing = False
        self._set_refreshing(False)
        self.status.setText("已停止刷新（如果网络请求仍在进行，会在后台自行结束）")
        # Don't block UI while cancelling.
        self._cleanup(block=False)
        # keep thread refs until it actually finishes; avoids Qt deleting a running QThread

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
            # keep thread refs until it actually finishes; avoids Qt deleting a running QThread

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
            # keep thread refs until it actually finishes

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
        # keep thread refs until it actually finishes

    def _set_stages_refreshing(self, on: bool, msg: str = "") -> None:
        has_release = isinstance(self.release_combo.currentData(), ReleaseDef)
        self.refresh_stages_btn.setEnabled((not on) and has_release)
        self.stop_stages_btn.setEnabled(on)
        if on:
            self.status.setText(msg)

    def _cleanup_stages(self, *, block: bool = True) -> None:
        if self._stages_watchdog is not None:
            try:
                self._stages_watchdog.stop()
            except Exception:
                pass
            self._stages_watchdog = None

        if self._stages_thread is not None:
            try:
                self._stages_thread.requestInterruption()
                self._stages_thread.quit()
                if block:
                    self._stages_thread.wait(1200)
            except Exception:
                pass
            if block:
                self._stages_thread = None
                self._stages_worker = None

    def _start_stages_watchdog(self, ms: int = 12000) -> None:
        t = QtCore.QTimer(self)
        t.setSingleShot(True)

        def fire() -> None:
            if not self._stages_refreshing:
                return
            self._stages_cancelled = True
            self._stages_refreshing = False
            self._set_stages_refreshing(False)
            if self.status.text().startswith("刷新发布阶段"):
                self.status.setText(f"刷新发布阶段超时（>{ms//1000}s）。可能是网络/权限问题，建议重试")
            self._cleanup_stages(block=False)
            # keep thread refs until it actually finishes

        t.timeout.connect(fire)
        t.start(ms)
        self._stages_watchdog = t

    def _cancel_stages(self) -> None:
        if not self._stages_refreshing:
            return
        self._stages_cancelled = True
        self._stages_refreshing = False
        self._set_stages_refreshing(False)
        self.status.setText("已停止刷新发布阶段（如果网络请求仍在进行，会在后台自行结束）")
        self._cleanup_stages(block=False)
        # keep thread refs until it actually finishes

    def _refresh_release_stages(self) -> None:
        if self._stages_refreshing:
            self.status.setText("正在刷新发布阶段中，请稍候或点击『停止』")
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

        rd: ReleaseDef | None = self.release_combo.currentData()
        if not rd:
            self.status.setText("请先选择发布流水线，才能刷新发布阶段")
            return

        self.release_stage_list.clear()

        self._stages_cancelled = False
        self._stages_refreshing = True
        self._set_stages_refreshing(True, f"刷新发布阶段中：{rd.name} ...")
        self._cleanup_stages(block=False)
        self._stages_thread = None
        self._start_stages_watchdog()

        worker = ReleaseStagesWorker(lib.base_url, p.collection, p.project, pat, rd.id)
        self._stages_worker = worker
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.ok.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def ok(payload: dict) -> None:
            if self._stages_cancelled:
                return
            self._stages_refreshing = False
            self._set_stages_refreshing(False)
            stages: list[ReleaseStage] = payload.get("stages") or []
            self.release_stage_list.clear()

            # Determine desired selected ids (new list fields, fallback old single)
            want_ids = list(getattr(self._flow, "release_stage_ids", []) or [])
            if not want_ids and self._flow.release_stage_id:
                want_ids = [self._flow.release_stage_id]

            for s in stages:
                it = QtWidgets.QListWidgetItem(s.name)
                it.setData(QtCore.Qt.UserRole, s)
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if s.id in want_ids else QtCore.Qt.Unchecked)
                self.release_stage_list.addItem(it)

            self.status.setText(f"发布阶段刷新完成：{len(stages)}")

        def fail(msg: str) -> None:
            if self._stages_cancelled:
                return
            self._stages_refreshing = False
            self._set_stages_refreshing(False)
            self.status.setText(f"刷新发布阶段失败：{msg}")

        worker.ok.connect(ok, QtCore.Qt.QueuedConnection)
        worker.failed.connect(fail, QtCore.Qt.QueuedConnection)

        def _done() -> None:
            if self._stages_refreshing and (not self._stages_cancelled) and self.status.text().startswith("刷新发布阶段"):
                self._stages_refreshing = False
                self._set_stages_refreshing(False)
                self.status.setText("刷新发布阶段已结束但未收到结果（可能是线程/网络异常）。请重试")

        thread.finished.connect(_done)
        thread.finished.connect(lambda th=thread: self._cleanup_specific_thread(th, kind="stages"))

        self._stages_thread = thread
        thread.start()

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

        # Preserve current branch selections (user may have changed them)
        want_src = self.source_combo.currentText().strip()
        want_tgt = self.target_combo.currentText().strip()

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
                # preserve current UI selection; then config; else first
                src_pick = want_src or self._flow.source_branch
                if src_pick:
                    for i in range(self.source_combo.count()):
                        bb: GitBranch = self.source_combo.itemData(i)
                        if bb and bb.short == src_pick:
                            self.source_combo.setCurrentIndex(i)
                            break
                else:
                    self.source_combo.setCurrentIndex(0)

                tgt_pick = want_tgt or self._flow.target_branch
                if tgt_pick:
                    for i in range(self.target_combo.count()):
                        bb: GitBranch = self.target_combo.itemData(i)
                        if bb and bb.short == tgt_pick:
                            self.target_combo.setCurrentIndex(i)
                            break
                else:
                    self.target_combo.setCurrentIndex(0)
            self.status.setText(f"分支刷新完成：{len(branches)}")

        def fail(msg: str) -> None:
            if self._branches_cancelled:
                return
            self._branches_refreshing = False
            self._set_branches_refreshing(False)
            self.status.setText(f"刷新分支失败：{msg}")

        worker.ok.connect(ok, QtCore.Qt.QueuedConnection)
        worker.failed.connect(fail, QtCore.Qt.QueuedConnection)

        def _done() -> None:
            if self._branches_refreshing and (not self._branches_cancelled) and self.status.text().startswith("刷新分支"):
                self._branches_refreshing = False
                self._set_branches_refreshing(False)
                self.status.setText("刷新分支已结束但未收到结果（可能是线程/网络异常）。请重试")

        thread.finished.connect(_done)
        thread.finished.connect(lambda th=thread: self._cleanup_specific_thread(th, kind="branches"))

        self._branches_thread = thread
        thread.start()

    def closeEvent(self, event) -> None:
        # Ensure background refresh thread is stopped
        self._cleanup()
        self._cleanup_branches()
        self._cleanup_stages()
        return super().closeEvent(event)

    def _on_project_change(self) -> None:
        # reset dependent dropdowns
        self.repo_combo.clear()
        self.source_combo.clear()
        self.target_combo.clear()
        self.build_combo.clear()
        self.release_combo.clear()
        self.release_stage_list.clear()
        self.status.setText("项目已切换：请点击刷新")

    def _on_repo_change(self) -> None:
        # changing repo should allow refresh branches
        self.source_combo.clear()
        self.target_combo.clear()
        self.status.setText("Repo 已切换：可点击『刷新分支』")
        self._set_branches_refreshing(False)

    def _on_release_change(self) -> None:
        # release changed -> refresh stages
        self.release_stage_list.clear()
        self.status.setText("发布流水线已切换：请刷新发布阶段")

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

        # Preserve current branch selections (user may have changed them)
        want_src = self.source_combo.currentText().strip()
        want_tgt = self.target_combo.currentText().strip()

        self.repo_combo.clear()
        self.source_combo.clear()
        self.target_combo.clear()
        self.build_combo.clear()
        self.release_combo.clear()
        self.release_stage_list.clear()

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
        # IMPORTANT: cleanup the specific thread to avoid old-thread-finish cancelling a new thread.
        thread.finished.connect(lambda th=thread: self._cleanup_specific_thread(th, kind="main"))

        def ok(payload: dict) -> None:
            if self._cancelled:
                return
            self._refreshing = False
            self._set_refreshing(False)

            repos: list[GitRepo] = payload.get("repos") or []
            repo_id: str | None = payload.get("repo_id")
            branches: list[GitBranch] = payload.get("branches") or []
            targets: list[BuildTarget] = payload.get("targets") or []
            release_defs: list[ReleaseDef] = payload.get("release_defs") or []
            warnings: list[str] = payload.get("warnings") or []
            debug: list[str] = payload.get("debug") or []

            if self.debug_chk.isChecked():
                self.debug_box.clear()
                self.debug_box.appendPlainText("\n\n".join(debug) if debug else "(no debug)")

            # repos
            for r in repos:
                self.repo_combo.addItem(r.name, userData=r)
            if repos:
                idx = 0
                # prefer config repo_id; else worker-chosen repo_id
                want_repo_id = self._flow.repo_id or repo_id
                if want_repo_id:
                    for i in range(self.repo_combo.count()):
                        rr: GitRepo = self.repo_combo.itemData(i)
                        if rr and rr.id == want_repo_id:
                            idx = i
                            break
                self.repo_combo.setCurrentIndex(idx)

            # branches
            for b in branches:
                self.source_combo.addItem(b.short, userData=b)
                self.target_combo.addItem(b.short, userData=b)
            if branches:
                # prefer current UI selection; then config; else first
                src_pick = want_src or self._flow.source_branch
                if src_pick:
                    for i in range(self.source_combo.count()):
                        bb: GitBranch = self.source_combo.itemData(i)
                        if bb and bb.short == src_pick:
                            self.source_combo.setCurrentIndex(i)
                            break
                else:
                    self.source_combo.setCurrentIndex(0)

                tgt_pick = want_tgt or self._flow.target_branch
                if tgt_pick:
                    for i in range(self.target_combo.count()):
                        bb: GitBranch = self.target_combo.itemData(i)
                        if bb and bb.short == tgt_pick:
                            self.target_combo.setCurrentIndex(i)
                            break
                else:
                    self.target_combo.setCurrentIndex(0)

            # build
            for t in targets:
                self.build_combo.addItem(f"{t.name} ({t.kind}:{t.id})", userData=t)
            if targets:
                # pick configured build if possible
                if self._flow.build_id:
                    for i in range(self.build_combo.count()):
                        bd: BuildTarget = self.build_combo.itemData(i)
                        if bd and bd.id == self._flow.build_id:
                            self.build_combo.setCurrentIndex(i)
                            break
                else:
                    self.build_combo.setCurrentIndex(0)

            # release definitions (classic release)
            self.release_combo.clear()
            for rd in release_defs:
                self.release_combo.addItem(rd.name, userData=rd)
            if release_defs:
                if self._flow.release_id:
                    for i in range(self.release_combo.count()):
                        rdd: ReleaseDef = self.release_combo.itemData(i)
                        if rdd and rdd.id == self._flow.release_id:
                            self.release_combo.setCurrentIndex(i)
                            break
                else:
                    self.release_combo.setCurrentIndex(0)

            msg = f"刷新完成：repos={len(repos)} branches={len(branches)} buildTargets={len(targets)}"
            if warnings:
                msg += "\n" + "\n".join([f"⚠️ {w}" for w in warnings][:3])
            self.status.setText(msg)

            # If we already have a release selected, try to load stages automatically (best-effort).
            if self.release_combo.currentData() and self.release_stage_list.count() == 0:
                self._refresh_release_stages()

            # Auto refresh chain for edit-mode
            if self._auto_refresh_mode and self._auto_refresh_phase == 1:
                self._auto_refresh_phase = 2
                self.status.setText("编辑模式：自动刷新中（2/3：分支）...")
                # refresh branches requires repo selected
                self._refresh_branches()
                self._auto_refresh_phase = 3
                # stages refresh happens after release defs are loaded; call explicitly too
                if self.release_combo.currentData():
                    self.status.setText("编辑模式：自动刷新中（3/3：发布阶段）...")
                    self._refresh_release_stages()

        def fail(msg: str) -> None:
            if self._cancelled:
                return
            self._refreshing = False
            self._set_refreshing(False)
            self.status.setText(f"刷新失败：{msg}")
            if self.debug_chk.isChecked():
                self.debug_box.appendPlainText(f"FAIL: {msg}")

        worker.ok.connect(ok, QtCore.Qt.QueuedConnection)
        worker.failed.connect(fail, QtCore.Qt.QueuedConnection)
        worker.progress.connect(
            lambda s: self.debug_box.appendPlainText(s) if self.debug_chk.isChecked() else None,
            QtCore.Qt.QueuedConnection,
        )

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
        rt: ReleaseDef | None = self.release_combo.currentData()

        # stages from checklist
        stage_ids: list[str] = []
        stage_names: list[str] = []
        for i in range(self.release_stage_list.count()):
            it = self.release_stage_list.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                s: ReleaseStage = it.data(QtCore.Qt.UserRole)
                if s:
                    stage_ids.append(s.id)
                    stage_names.append(s.name)

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
                r: ReleaseDef = self.release_combo.itemData(i)
                if r and r.name == t:
                    rt = r
                    break
        # release stages are multi-select (checkbox list)

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
            QtWidgets.QMessageBox.warning(self, "错误", "请先刷新并选择 构建流水线/发布流水线")
            return
        if not stage_ids:
            QtWidgets.QMessageBox.warning(self, "错误", "请选择发布到哪个阶段（可多选）")
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
                "release_kind": "release",
                "release_id": rt.id,
                "release_name": rt.name,
                "release_stage_ids": stage_ids,
                "release_stage_names": stage_names,
                # keep old fields for back-compat
                "release_stage_id": stage_ids[0] if stage_ids else None,
                "release_stage_name": stage_names[0] if stage_names else None,
            }
        )
        super().accept()
