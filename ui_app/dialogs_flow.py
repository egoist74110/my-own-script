from __future__ import annotations

import httpx
from PySide6 import QtCore, QtGui, QtWidgets

from ui_app.ado_discovery import BuildTarget, discover_build_targets
from ui_app.library_store import get_pat
from ui_app.settings_store import LibraryEntry, ProjectEntry, UiSettings
from ui_app.tasks_store import FlowTaskConfig


class FetchTargetsWorker(QtCore.QObject):
    ok = QtCore.Signal(list)
    failed = QtCore.Signal(str)

    def __init__(self, base_url: str, collection: str, pat: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.collection = collection
        self.pat = pat

    @QtCore.Slot()
    def run(self) -> None:
        try:
            targets = discover_build_targets(self.base_url, self.collection, self.pat)
            self.ok.emit(targets)
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

        self.source_branch = QtWidgets.QLineEdit()
        self.source_branch.setPlaceholderText("source branch")

        self.target_branch = QtWidgets.QLineEdit()
        self.target_branch.setPlaceholderText("target branch")

        self.build_combo = QtWidgets.QComboBox()
        self.release_combo = QtWidgets.QComboBox()

        self.refresh_btn = QtWidgets.QPushButton("刷新 Build/Release 列表")
        self.refresh_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.refresh_btn.clicked.connect(self._refresh_targets)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)

        form.addRow("Project", self.project_combo)
        form.addRow("source_branch", self.source_branch)
        form.addRow("target_branch", self.target_branch)
        form.addRow("Build", self.build_combo)
        form.addRow("Release", self.release_combo)
        root.addLayout(form)

        root.addWidget(self.refresh_btn)
        root.addWidget(self.status)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._thread: QtCore.QThread | None = None

        # load existing
        if flow.project_id:
            for i in range(self.project_combo.count()):
                if self.project_combo.itemData(i) == flow.project_id:
                    self.project_combo.setCurrentIndex(i)
                    break
        self.source_branch.setText(flow.source_branch)
        self.target_branch.setText(flow.target_branch)

        self.project_combo.currentIndexChanged.connect(lambda _: self._refresh_targets())
        # initial refresh
        self._refresh_targets()

    def result_flow(self) -> FlowTaskConfig | None:
        return self._result

    def _cleanup(self) -> None:
        if self._thread is not None:
            try:
                self._thread.quit()
                self._thread.wait(800)
            except Exception:
                pass
            self._thread = None

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

    def _refresh_targets(self) -> None:
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

        self.build_combo.clear()
        self.release_combo.clear()
        self.status.setText(f"拉取中：{lib.base_url} / {p.collection} ...")
        self.refresh_btn.setEnabled(False)
        self._cleanup()

        worker = FetchTargetsWorker(lib.base_url, p.collection, pat)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.ok.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def ok(targets: list[BuildTarget]) -> None:
            self.refresh_btn.setEnabled(True)
            if not targets:
                self.status.setText("没有拉到 Build 目标（你可以后续改成手填 ID）")
                return
            for t in targets:
                self.build_combo.addItem(f"{t.name} ({t.kind}:{t.id})", userData=t)
                self.release_combo.addItem(f"{t.name} ({t.kind}:{t.id})", userData=t)
            self.build_combo.setCurrentIndex(0)
            self.release_combo.setCurrentIndex(0)
            self.status.setText(f"已拉取 {len(targets)} 个 Build 目标（Release 先复用同一列表）")

        def fail(msg: str) -> None:
            self.refresh_btn.setEnabled(True)
            self.status.setText(f"拉取失败：{msg}")

        worker.ok.connect(ok)
        worker.failed.connect(fail)

        self._thread = thread
        thread.start()

    def accept(self) -> None:
        if not self._settings.projects:
            QtWidgets.QMessageBox.warning(self, "错误", "请先在设置里新增项目")
            return

        pid = self.project_combo.currentData()
        src = self.source_branch.text().strip()
        tgt = self.target_branch.text().strip()
        bt: BuildTarget | None = self.build_combo.currentData()
        rt: BuildTarget | None = self.release_combo.currentData()

        if not pid:
            QtWidgets.QMessageBox.warning(self, "错误", "请选择 Project")
            return
        if not src or not tgt:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 source/target 分支")
            return
        if not bt or not rt:
            QtWidgets.QMessageBox.warning(self, "错误", "请先刷新并选择 Build/Release")
            return

        self._result = self._flow.model_copy(
            update={
                "project_id": pid,
                "source_branch": src,
                "target_branch": tgt,
                "build_kind": bt.kind,
                "build_id": bt.id,
                "build_name": bt.name,
                "release_kind": rt.kind,
                "release_id": rt.id,
                "release_name": rt.name,
            }
        )
        super().accept()
