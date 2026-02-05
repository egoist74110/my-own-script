from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import ExpandSettingCard, FluentIcon, PushButton


class TaskCard(ExpandSettingCard):
    """Reusable task card with built-in expand panel and per-task run log."""

    run_clicked = QtCore.Signal()
    config_clicked = QtCore.Signal()

    def __init__(self, *, title: str, subtitle: str = "") -> None:
        super().__init__(FluentIcon.APPLICATION, title, subtitle)

        self.btn_config = PushButton("配置")
        self.btn_run = PushButton("运行")

        # Use the card's built-in expand button; do NOT add extra dropdown arrow.
        # Buttons belong to the header card layout.
        self.card.hBoxLayout.addStretch(1)
        self.card.hBoxLayout.addWidget(self.btn_config)
        self.card.hBoxLayout.addWidget(self.btn_run)

        self.btn_config.clicked.connect(self.config_clicked.emit)
        self.btn_run.clicked.connect(self.run_clicked.emit)

        # Per-task log box in expandable panel
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("运行日志（每次运行会清空并写入新日志）")
        self.viewLayout.addWidget(self.log_box)

        self.setExpand(False)

    def clear_log(self) -> None:
        self.log_box.clear()

    def append_log(self, text: str) -> None:
        self.log_box.appendPlainText(text)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())
