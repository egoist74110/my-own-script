from __future__ import annotations

import uuid

import httpx
import keyring
from PySide6 import QtCore, QtGui, QtWidgets

from runner_app.config import APP_ID
from ui_app.azuredevops_client import AzureDevOpsClient
from ui_app.settings_store import RepoEntry


class FetchWorker(QtCore.QObject):
    accounts_ready = QtCore.Signal(list)
    projects_ready = QtCore.Signal(str, list)
    failed = QtCore.Signal(str)

    def __init__(self, pat: str) -> None:
        super().__init__()
        self._pat = pat

    @QtCore.Slot()
    def fetch_accounts(self) -> None:
        try:
            c = AzureDevOpsClient(pat=self._pat)
            accounts = c.list_accounts()
            self.accounts_ready.emit(accounts)
        except httpx.HTTPStatusError as e:
            self.failed.emit(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            self.failed.emit(str(e))

    @QtCore.Slot(str)
    def fetch_projects(self, org: str) -> None:
        try:
            c = AzureDevOpsClient(pat=self._pat)
            projects = c.list_projects(org)
            self.projects_ready.emit(org, projects)
        except httpx.HTTPStatusError as e:
            self.failed.emit(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
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

        self.org_combo = QtWidgets.QComboBox()
        self.org_combo.setEnabled(False)
        self.org_combo.currentIndexChanged.connect(self._on_org_changed)

        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.setEnabled(False)

        form.addRow("类型", self.provider)
        form.addRow("名称", self.display_name)
        form.addRow("组织/公司(Org)", self.org_combo)
        form.addRow("项目(Project)", self.project_combo)

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
        self.fetch_btn.clicked.connect(self._start_fetch_accounts)

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
        self._accounts: list = []
        self._projects_by_org: dict[str, list] = {}
        self._worker: FetchWorker | None = None
        self._thread: QtCore.QThread | None = None

    def repo(self) -> RepoEntry | None:
        return self._repo

    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self.fetch_btn.setEnabled(not busy)
        self.token.setEnabled(not busy)
        self.org_combo.setEnabled(not busy and self.org_combo.count() > 0)
        self.project_combo.setEnabled(not busy and self.project_combo.count() > 0)
        self.status.setText(msg)

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(1000)
            self._thread = None
            self._worker = None

    def _start_fetch_accounts(self) -> None:
        pat = self.token.text().strip()
        if not pat:
            QtWidgets.QMessageBox.warning(self, "错误", "请先粘贴 PAT")
            return

        self._cleanup_thread()
        self._set_busy(True, "正在验证 PAT 并拉取 Org 列表...")

        worker = FetchWorker(pat)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        worker.accounts_ready.connect(self._on_accounts_ready)
        worker.failed.connect(self._on_fetch_failed)
        thread.started.connect(worker.fetch_accounts)
        worker.accounts_ready.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.accounts_ready.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._worker = worker
        self._thread = thread
        thread.start()

    def _on_accounts_ready(self, accounts: list) -> None:
        self._accounts = accounts
        self.org_combo.clear()
        for a in accounts:
            # a: AzureDevOpsAccount
            self.org_combo.addItem(a.account_name, userData=a.account_name)

        ok = bool(accounts)
        self.org_combo.setEnabled(ok)
        self.project_combo.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._set_busy(False, f"拉取成功：发现 {len(accounts)} 个 Org。请选择 Org 继续拉取 Project。" if ok else "未发现任何可访问的 Org（检查 PAT 权限/账号）。")

        if ok:
            # auto trigger projects fetch for first org
            self._start_fetch_projects(self.org_combo.currentData())

    def _start_fetch_projects(self, org: str) -> None:
        pat = self.token.text().strip()
        if not pat or not org:
            return
        self._cleanup_thread()
        self._set_busy(True, f"正在拉取 Org={org} 的 Project 列表...")

        worker = FetchWorker(pat)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        worker.projects_ready.connect(self._on_projects_ready)
        worker.failed.connect(self._on_fetch_failed)
        thread.started.connect(lambda: worker.fetch_projects(org))
        worker.projects_ready.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.projects_ready.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._worker = worker
        self._thread = thread
        thread.start()

    def _on_projects_ready(self, org: str, projects: list) -> None:
        self._projects_by_org[org] = projects
        self.project_combo.clear()
        for p in projects:
            self.project_combo.addItem(p.name, userData=p.name)

        self.project_combo.setEnabled(bool(projects))
        self._save_btn.setEnabled(True)  # allow saving even if project empty
        self._set_busy(False, f"拉取成功：Org={org} 共有 {len(projects)} 个 Project。现在可以保存。")

    def _on_fetch_failed(self, msg: str) -> None:
        self._save_btn.setEnabled(False)
        self._set_busy(False, f"拉取失败：{msg}")

    def _on_org_changed(self, idx: int) -> None:
        org = self.org_combo.currentData()
        if not org:
            return
        # if cached, use cached list
        cached = self._projects_by_org.get(org)
        if cached is not None:
            self.project_combo.clear()
            for p in cached:
                self.project_combo.addItem(p.name, userData=p.name)
            self.project_combo.setEnabled(bool(cached))
            self._save_btn.setEnabled(True)
            self.status.setText(f"Org={org} 已缓存 {len(cached)} 个 Project。")
            return
        self._start_fetch_projects(org)

    def accept(self) -> None:
        display_name = self.display_name.text().strip()
        token = self.token.text().strip()
        org = self.org_combo.currentData()
        project = self.project_combo.currentData() if self.project_combo.isEnabled() else None

        if not display_name:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写名称")
            return
        if not token:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 PAT")
            return
        if not org:
            QtWidgets.QMessageBox.warning(self, "错误", "请先验证并选择 Org")
            return

        repo_id = f"ado:{uuid.uuid4()}"
        entry = RepoEntry(
            id=repo_id,
            provider="azuredevops",
            display_name=display_name,
            org=str(org),
            project=str(project) if project else None,
        )

        # store token securely in keychain
        keyring.set_password(APP_ID, f"azuredevops_pat:{repo_id}", token)

        # clear token field after save (basic safety)
        self.token.setText("")

        self._repo = entry
        super().accept()
