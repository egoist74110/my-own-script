from __future__ import annotations

import uuid

import httpx
from PySide6 import QtCore, QtGui, QtWidgets

from ui_app.azuredevops_ops import list_collections, list_projects
from ui_app.library_store import get_pat
from ui_app.settings_store import LibraryEntry, ProjectEntry


class FetchWorker(QtCore.QObject):
    collections_ok = QtCore.Signal(list)
    projects_ok = QtCore.Signal(list)
    failed = QtCore.Signal(str)

    def __init__(self, base_url: str, pat: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.pat = pat

    @QtCore.Slot()
    def fetch_collections(self) -> None:
        try:
            cols = list_collections(self.base_url, self.pat)
            self.collections_ok.emit(cols)
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:400]
            self.failed.emit(f"HTTP {e.response.status_code}: {body}")
        except Exception as e:
            self.failed.emit(str(e))

    @QtCore.Slot(str)
    def fetch_projects(self, collection: str) -> None:
        try:
            ps = list_projects(self.base_url, self.pat, collection)
            self.projects_ok.emit(ps)
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:400]
            self.failed.emit(f"HTTP {e.response.status_code}: {body}")
        except Exception as e:
            self.failed.emit(str(e))


class ProjectDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, *, libraries: list[LibraryEntry], existing: ProjectEntry | None = None) -> None:
        super().__init__(parent)
        self._existing = existing
        self._result: ProjectEntry | None = None
        self._libraries = libraries

        self.setWindowTitle("编辑项目" if existing else "新增项目")
        self.setModal(True)
        self.resize(700, 420)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.lib_combo = QtWidgets.QComboBox()
        for lib in libraries:
            self.lib_combo.addItem(lib.name, userData=lib.id)
        self.lib_combo.currentIndexChanged.connect(self._on_lib_changed)

        self.collection_combo = QtWidgets.QComboBox()
        self.collection_combo.setEnabled(False)
        self.collection_input = QtWidgets.QLineEdit()
        self.collection_input.setPlaceholderText("手动输入 Collection（例如 DefaultCollection）")
        self.collection_input.setEnabled(False)
        self.collection_input.editingFinished.connect(self._on_collection_input)

        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.setEnabled(False)

        form.addRow("代码库", self.lib_combo)
        form.addRow("Collection(下拉)", self.collection_combo)
        form.addRow("Collection(手填)", self.collection_input)
        form.addRow("Project", self.project_combo)
        root.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        self.fetch_btn = QtWidgets.QPushButton("拉取Collections")
        self.fetch_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.fetch_btn.clicked.connect(self._fetch_collections)
        self.pick_default_btn = QtWidgets.QPushButton("尝试 DefaultCollection")
        self.pick_default_btn.clicked.connect(lambda: self._use_collection("DefaultCollection"))
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("Muted")
        row.addWidget(self.fetch_btn)
        row.addWidget(self.pick_default_btn)
        row.addWidget(self.status, 1)
        root.addLayout(row)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._thread: QtCore.QThread | None = None
        self._worker: FetchWorker | None = None

        if existing:
            # select library
            idx = 0
            for i in range(self.lib_combo.count()):
                if self.lib_combo.itemData(i) == existing.library_id:
                    idx = i
                    break
            self.lib_combo.setCurrentIndex(idx)
            self.collection_input.setText(existing.collection)
            self.project_combo.addItem(existing.project, userData=existing.project)
            self.project_combo.setEnabled(True)

    def result_entry(self) -> ProjectEntry | None:
        return self._result

    def _cleanup(self) -> None:
        if self._thread is not None:
            try:
                self._thread.quit()
                self._thread.wait(800)
            except Exception:
                pass
            self._thread = None
            self._worker = None

    def _current_lib(self) -> LibraryEntry | None:
        lid = self.lib_combo.currentData()
        for lib in self._libraries:
            if lib.id == lid:
                return lib
        return None

    def _on_lib_changed(self, idx: int) -> None:
        # reset UI
        self.collection_combo.clear()
        self.project_combo.clear()
        self.collection_combo.setEnabled(False)
        self.project_combo.setEnabled(False)
        self.collection_input.setEnabled(True)

    def _fetch_collections(self) -> None:
        lib = self._current_lib()
        if not lib:
            return
        pat = get_pat(lib.id)
        if not pat:
            QtWidgets.QMessageBox.warning(self, "错误", "该代码库没有保存 PAT，请先去代码库里编辑保存")
            return

        self.status.setText("拉取 Collections 中...")
        self.fetch_btn.setEnabled(False)
        self._cleanup()

        worker = FetchWorker(lib.base_url, pat)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.fetch_collections)
        worker.collections_ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.collections_ok.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def ok(cols: list[str]) -> None:
            self.fetch_btn.setEnabled(True)
            if cols:
                self.collection_combo.setEnabled(True)
                self.collection_combo.clear()
                for c in cols:
                    self.collection_combo.addItem(c, userData=c)
                # pick first by default
                self.collection_combo.setCurrentIndex(0)
                self._use_collection(cols[0])
                self.status.setText(f"已拉取 {len(cols)} 个 Collections，默认选第一个")
            else:
                self.collection_input.setEnabled(True)
                self.status.setText("未拉取到 Collections，请手动输入 DefaultCollection")

        def fail(msg: str) -> None:
            self.fetch_btn.setEnabled(True)
            self.collection_input.setEnabled(True)
            self.status.setText(f"无法拉取 Collections（可忽略）：{msg}")

        worker.collections_ok.connect(ok)
        worker.failed.connect(fail)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _use_collection(self, collection: str) -> None:
        self.collection_input.setText(collection)
        self._fetch_projects(collection)

    def _on_collection_input(self) -> None:
        c = self.collection_input.text().strip()
        if c:
            self._fetch_projects(c)

    def _fetch_projects(self, collection: str) -> None:
        lib = self._current_lib()
        if not lib:
            return
        pat = get_pat(lib.id)
        if not pat:
            return

        self.project_combo.clear()
        self.project_combo.setEnabled(False)
        self.status.setText(f"拉取 Projects（{collection}）...")
        self._cleanup()

        worker = FetchWorker(lib.base_url, pat)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(lambda: worker.fetch_projects(collection))
        worker.projects_ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.projects_ok.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def ok(ps: list[str]) -> None:
            if ps:
                self.project_combo.setEnabled(True)
                for p in ps:
                    self.project_combo.addItem(p, userData=p)
                self.project_combo.setCurrentIndex(0)
                self.status.setText(f"已拉取 {len(ps)} 个 Projects，默认选第一个")
            else:
                self.status.setText("未拉取到 Projects")

        def fail(msg: str) -> None:
            self.status.setText(f"拉取 Projects 失败：{msg}")

        worker.projects_ok.connect(ok)
        worker.failed.connect(fail)

        self._thread = thread
        self._worker = worker
        thread.start()

    def accept(self) -> None:
        lib = self._current_lib()
        if not lib:
            QtWidgets.QMessageBox.warning(self, "错误", "请选择代码库")
            return

        collection = self.collection_input.text().strip()
        project = self.project_combo.currentData() if self.project_combo.isEnabled() else None
        if not collection:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 Collection")
            return
        if not project:
            QtWidgets.QMessageBox.warning(self, "错误", "请先拉取并选择 Project")
            return

        pid = self._existing.id if self._existing else f"proj:{uuid.uuid4()}"
        self._result = ProjectEntry(
            id=pid,
            library_id=lib.id,
            collection=collection,
            project=str(project),
        )
        super().accept()
