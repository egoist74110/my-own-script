from __future__ import annotations

from PySide6 import QtWidgets
from qfluentwidgets import PushButton


def show_confirm_dialog(parent: QtWidgets.QWidget, title: str, details: str) -> bool:
    """Modal confirm dialog with scrollable details.

    Returns True if user confirms.
    """
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.resize(720, 420)

    root = QtWidgets.QVBoxLayout(dlg)
    root.setContentsMargins(16, 16, 16, 16)
    root.setSpacing(12)

    box = QtWidgets.QPlainTextEdit()
    box.setReadOnly(True)
    box.setPlainText(details)
    root.addWidget(box, 1)

    row = QtWidgets.QHBoxLayout()
    row.addStretch(1)

    btn_cancel = PushButton("取消")
    btn_ok = PushButton("确认")
    btn_ok.setDefault(True)

    btn_cancel.clicked.connect(dlg.reject)
    btn_ok.clicked.connect(dlg.accept)

    row.addWidget(btn_cancel)
    row.addWidget(btn_ok)
    root.addLayout(row)

    return dlg.exec() == QtWidgets.QDialog.Accepted
