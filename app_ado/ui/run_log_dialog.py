from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import PushButton


class RunLogDialog(QtWidgets.QDialog):
    def __init__(self, parent, *, title: str = "运行日志"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(900, 520)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self.box = QtWidgets.QPlainTextEdit()
        self.box.setReadOnly(True)
        root.addWidget(self.box, 1)

        btn = PushButton("关闭")
        btn.clicked.connect(self.accept)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        root.addLayout(row)

    def log(self, text: str) -> None:
        from shiboken6 import isValid
        if not isValid(self) or not isValid(self.box):
            return
        self.box.appendPlainText(text)
        self.box.verticalScrollBar().setValue(self.box.verticalScrollBar().maximum())
