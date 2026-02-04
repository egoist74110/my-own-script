from __future__ import annotations

import uuid

import httpx
import keyring
from PySide6 import QtCore, QtGui, QtWidgets

from runner_app.config import APP_ID
from ui_app.azuredevops_client import AzureDevOpsClient
from ui_app.settings_store import RepoEntry


class FetchWorker(QtCore.QObject):
    collections_ready = QtCore.Signal(list)
    projects_ready = QtCore.Signal(str, list)
    failed = QtCore.Signal(str)

    def __init__(self, base_url: str, pat: str, api_version: str = "7.0") -> None:
        super().__init__()
        self._base_url = base_url
        self._pat = pat
        self._api_version = api_version

    @QtCore.Slot()
    def fetch_collections(self) -> None:
        try:
            c = AzureDevOpsClient(base_url=self._base_url, pat=self._pat, api_version=self._api_version)
            cols = c.list_collections()
            self.collections_ready.emit(cols)
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:400]
            self.failed.emit(f"HTTP {e.response.status_code}: {body}")
        except Exception as e:
            self.failed.emit(str(e))

    @QtCore.Slot(str)
    def fetch_projects(self, collection: str) -> None:
        try:
            c = AzureDevOpsClient(base_url=self._base_url, pat=self._pat, api_version=self._api_version)
            projects = c.list_projects(collection)
            self.projects_ready.emit(collection, projects)
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:400]
            self.failed.emit(f"HTTP {e.response.status_code}: {body}")
        except Exception as e:
            self.failed.emit(str(e))


class AddRepoDialog(QtWidgets.QDialog):
    """Wizard-ish dialog for adding a code repo connection.

    v1: only Azure DevOps.
    User provides PAT, then we fetch orgs/projects for selection.
    Token is stored in OS keychain via keyring.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增代码仓库")
        self.setModal(True)
        self.resize(560, 420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.provider = QtWidgets.QComboBox()
        self.provider.addItem("Azure DevOps", userData="azuredevops")
        self.provider.setEnabled(False)  # v1 fixed

        self.display_name = QtWidgets.QLineEdit()
        self.display_name.setPlaceholderText("例如：公司 ADO")

        self.base_url = QtWidgets.QLineEdit()
        self.base_url.setPlaceholderText("例如：https://azuredevops.your-company.com")

        self.collection_combo = QtWidgets.QComboBox()
        self.collection_combo.setEditable(True)
        self.collection_combo.setEnabled(False)
        self.collection_combo.currentIndexChanged.connect(self._on_collection_changed)
        # If user types a collection manually, fetch projects.
        self.collection_combo.lineEdit().editingFinished.connect(lambda: self._on_collection_changed(self.collection_combo.currentIndex()))

        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.setEnabled(False)

        form.addRow("类型", self.provider)
        form.addRow("名称", self.display_name)
        form.addRow("Server URL", self.base_url)
        form.addRow("Collection", self.collection_combo)
        form.addRow("Project", self.project_combo)

        layout.addLayout(form)

        guide = QtWidgets.QLabel(
            "<b>个人访问令牌 (PAT)</b><br>"
            "1) 在 Azure DevOps 创建 PAT（建议最小权限）。<br>"
            "2) 输入 PAT 后点击【验证并拉取】，我们会拉取你可访问的 Org/Project 供选择。<br>"
            "3) 保存时 token 通过 <code>keyring</code> 写入系统钥匙串(Keychain)，不落盘明文。"
        )
        guide.setWordWrap(True)
        guide.setTextFormat(QtCore.Qt.RichText)
        guide.setObjectName("Muted")
        layout.addWidget(guide)

        token_row = QtWidgets.QHBoxLayout()
        token_row.setSpacing(10)

        self.token = QtWidgets.QLineEdit()
        self.token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.token.setPlaceholderText("粘贴 Azure DevOps PAT（不会回显）")

        self.fetch_btn = QtWidgets.QPushButton("验证并拉取")
        self.fetch_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.fetch_btn.clicked.connect(self._start_fetch_collections)

        token_row.addWidget(self.token, 1)
        token_row.addWidget(self.fetch_btn, 0)
        layout.addLayout(token_row)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save
        )
        self._save_btn = btns.button(QtWidgets.QDialogButtonBox.Save)
        self._save_btn.setEnabled(False)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._repo: RepoEntry | None = None
        self._collections: list = []
        self._projects_by_collection: dict[str, list] = {}
        self._worker: FetchWorker | None = None
        self._thread: QtCore.QThread | None = None

    def repo(self) -> RepoEntry | None:
        return self._repo

    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self.fetch_btn.setEnabled(not busy)
        self.token.setEnabled(not busy)
        self.base_url.setEnabled(not busy)
        self.collection_combo.setEnabled(not busy and self.collection_combo.count() > 0)
        self.project_combo.setEnabled(not busy and self.project_combo.count() > 0)
        self.status.setText(msg)

    def _cleanup_thread(self) -> None:
        # QThread objects can be deleted by Qt when finished + deleteLater.
        # Guard against double-cleanup.
        if self._thread is None:
            self._worker = None
            return

        try:
            from shiboken6 import isValid  # bundled with PySide6

            valid = isValid(self._thread)
        except Exception:
            valid = True

        try:
            if valid:
                self._thread.quit()
                self._thread.wait(1000)
        except RuntimeError:
            # already deleted
            pass
        finally:
            self._thread = None
            self._worker = None

    def _start_fetch_collections(self) -> None:
        raw_base = self.base_url.text().strip()
        pat = self.token.text().strip()
        if not raw_base:
            QtWidgets.QMessageBox.warning(self, "错误", "请先填写 Server URL")
            return
        if not pat:
            QtWidgets.QMessageBox.warning(self, "错误", "请先粘贴 PAT")
            return

        # If user pasted a URL containing a collection path, split it.
        base_url = raw_base.rstrip("/")
        maybe_collection = None
        if "/_apis/" in base_url:
            base_url = base_url.split("/_apis/")[0]
        parts = base_url.split("/")
        if len(parts) > 3 and parts[-1].lower().endswith("collection"):
            maybe_collection = parts[-1]
            base_url = "/".join(parts[:-1])

        if maybe_collection:
            self.collection_combo.setEnabled(True)
            self.collection_combo.clear()
            self.collection_combo.addItem(maybe_collection, userData=maybe_collection)
            self.collection_combo.setCurrentIndex(0)

        self._cleanup_thread()
        self._set_busy(True, "正在验证 PAT 并拉取 Collection 列表...")

        worker = FetchWorker(base_url, pat, "7.0")
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        worker.collections_ready.connect(self._on_collections_ready)
        # If listing collections fails (common on locked-down servers), we allow manual collection entry.
        worker.failed.connect(self._on_fetch_collections_failed)
        thread.started.connect(worker.fetch_collections)
        worker.collections_ready.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.collections_ready.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._worker = worker
        self._thread = thread
        thread.finished.connect(self._cleanup_thread)
        thread.start()

    def _on_collections_ready(self, cols: list) -> None:
        self._collections = cols
        self.collection_combo.clear()
        for c in cols:
            # c: AzureDevOpsCollection
            self.collection_combo.addItem(c.name, userData=c.name)

        ok = bool(cols)
        self.collection_combo.setEnabled(True)  # editable, allow manual entry
        self.project_combo.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._set_busy(False, f"拉取成功：发现 {len(cols)} 个 Collection。请选择一个继续拉取 Project。" if ok else "未发现 Collection（可能需要手动输入 Collection 名称，如 DefaultCollection）。")

        if ok:
            self._start_fetch_projects(self.collection_combo.currentData())

    def _start_fetch_projects(self, collection: str) -> None:
        base_url = self.base_url.text().strip().rstrip("/")
        pat = self.token.text().strip()
        if not base_url or not pat or not collection:
            return

        self._cleanup_thread()
        self._set_busy(True, f"正在拉取 Collection={collection} 的 Project 列表...")

        worker = FetchWorker(base_url, pat, "7.0")
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        worker.projects_ready.connect(self._on_projects_ready)
        worker.failed.connect(self._on_fetch_failed)
        thread.started.connect(lambda: worker.fetch_projects(collection))
        worker.projects_ready.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.projects_ready.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._worker = worker
        self._thread = thread
        thread.finished.connect(self._cleanup_thread)
        thread.start()

    def _on_projects_ready(self, collection: str, projects: list) -> None:
        self._projects_by_collection[collection] = projects
        self.project_combo.clear()
        for p in projects:
            self.project_combo.addItem(p.name, userData=p.name)

        self.project_combo.setEnabled(bool(projects))
        self._save_btn.setEnabled(True)
        self._set_busy(False, f"拉取成功：Collection={collection} 共有 {len(projects)} 个 Project。现在可以保存。")

    def _on_fetch_failed(self, msg: str) -> None:
        self._save_btn.setEnabled(False)
        self._set_busy(False, f"拉取失败：{msg}")

    def _on_fetch_collections_failed(self, msg: str) -> None:
        # Some ADO servers block listing collections. Allow user to type collection manually.
        self._save_btn.setEnabled(False)
        self.collection_combo.setEnabled(True)
        self.collection_combo.setEditable(True)
        self._set_busy(
            False,
            "无法自动拉取 Collection（常见原因：服务器禁用该接口/权限限制）。\n"
            "请手动输入 Collection（例如：DefaultCollection）后回车/切换焦点，我会尝试拉取 Projects。\n"
            f"原始错误：{msg}",
        )

    def _on_collection_changed(self, idx: int) -> None:
        collection = self.collection_combo.currentData() or self.collection_combo.currentText().strip()
        if not collection:
            return
        cached = self._projects_by_collection.get(collection)
        if cached is not None:
            self.project_combo.clear()
            for p in cached:
                self.project_combo.addItem(p.name, userData=p.name)
            self.project_combo.setEnabled(bool(cached))
            self._save_btn.setEnabled(True)
            self.status.setText(f"Collection={collection} 已缓存 {len(cached)} 个 Project。")
            return
        self._start_fetch_projects(collection)

    def accept(self) -> None:
        display_name = self.display_name.text().strip()
        token = self.token.text().strip()
        base_url = self.base_url.text().strip().rstrip("/")
        collection = self.collection_combo.currentData() or self.collection_combo.currentText().strip()
        project = self.project_combo.currentData() if self.project_combo.isEnabled() else None

        if not display_name:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写名称")
            return
        if not base_url:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 Server URL")
            return
        if not token:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 PAT")
            return
        if not collection:
            QtWidgets.QMessageBox.warning(self, "错误", "请先拉取并选择/输入 Collection")
            return

        repo_id = f"ado:{uuid.uuid4()}"
        entry = RepoEntry(
            id=repo_id,
            provider="azuredevops",
            display_name=display_name,
            base_url=base_url,
            collection=str(collection),
            project=str(project) if project else None,
        )

        # store token securely in keychain
        keyring.set_password(APP_ID, f"azuredevops_pat:{repo_id}", token)

        # clear token field after save (basic safety)
        self.token.setText("")

        self._repo = entry
        super().accept()
