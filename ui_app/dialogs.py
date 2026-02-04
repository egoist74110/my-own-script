from __future__ import annotations

import uuid

import keyring
from PySide6 import QtCore, QtGui, QtWidgets

from runner_app.config import APP_ID
from ui_app.settings_store import RepoEntry


class AddRepoDialog(QtWidgets.QDialog):
    """Wizard-ish dialog for adding a code repo connection.

    v1: only Azure DevOps.
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

        self.org = QtWidgets.QLineEdit()
        self.org.setPlaceholderText("你的 org（dev.azure.com/{org}）")

        self.project = QtWidgets.QLineEdit()
        self.project.setPlaceholderText("你的 project（可选）")

        form.addRow("类型", self.provider)
        form.addRow("名称", self.display_name)
        form.addRow("Org", self.org)
        form.addRow("Project", self.project)

        layout.addLayout(form)

        guide = QtWidgets.QLabel(
            "<b>个人访问令牌 (PAT) 保存指引</b><br>"
            "1) 在 Azure DevOps 里创建 PAT（按你需要的权限最小化）。<br>"
            "2) 下面输入 PAT 后，我们会通过 <code>keyring</code> 写入系统钥匙串(Keychain)。<br>"
            "3) 本工具不会把 token 写进 git 仓库/配置文件，也不会在界面中明文展示。"
        )
        guide.setWordWrap(True)
        guide.setTextFormat(QtCore.Qt.RichText)
        guide.setObjectName("Muted")
        layout.addWidget(guide)

        self.token = QtWidgets.QLineEdit()
        self.token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.token.setPlaceholderText("粘贴 Azure DevOps PAT（不会回显）")
        layout.addWidget(self.token)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._repo: RepoEntry | None = None

    def repo(self) -> RepoEntry | None:
        return self._repo

    def accept(self) -> None:
        display_name = self.display_name.text().strip()
        org = self.org.text().strip()
        project = self.project.text().strip() or None
        token = self.token.text().strip()

        if not display_name:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写名称")
            return
        if not org:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 Org")
            return
        if not token:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 PAT")
            return

        repo_id = f"ado:{uuid.uuid4()}"
        entry = RepoEntry(
            id=repo_id,
            provider="azuredevops",
            display_name=display_name,
            org=org,
            project=project,
        )

        # store token securely in keychain
        keyring.set_password(APP_ID, f"azuredevops_pat:{repo_id}", token)

        self._repo = entry
        super().accept()
