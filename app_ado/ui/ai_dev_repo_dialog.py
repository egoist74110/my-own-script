"""AI 开发：选择本地仓库的小弹窗。

只读 UiSettings.local_repos，不增改任何配置。
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import PushButton

from app_ado.models import LocalRepoEntry


class PickLocalRepoDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget, repos: list[LocalRepoEntry]) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择本地仓库")
        self.setModal(True)
        self.resize(520, 380)
        self._result: Optional[LocalRepoEntry] = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        tip = QtWidgets.QLabel("选择要运行 AI CLI 的本地仓库（来自“代码配置 - 本地仓库”）：")
        root.addWidget(tip)

        self.list_widget = QtWidgets.QListWidget()
        for repo in repos:
            item = QtWidgets.QListWidgetItem(f"{repo.name}   ({repo.path})")
            item.setData(QtCore.Qt.UserRole, repo)
            self.list_widget.addItem(item)
        if repos:
            self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(self._accept_current)
        root.addWidget(self.list_widget, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = PushButton("取消")
        self.btn_ok = PushButton("确定")
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        root.addLayout(row)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._accept_current)

    def _accept_current(self, *_) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._result = item.data(QtCore.Qt.UserRole)
        self.accept()

    def result_repo(self) -> Optional[LocalRepoEntry]:
        return self._result
