from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import ExpandSettingCard, FluentIcon, PushButton


class TaskCard(ExpandSettingCard):
    """Reusable task card with built-in expand panel and per-task run log."""

    run_clicked = QtCore.Signal()
    rollback_clicked = QtCore.Signal()
    config_clicked = QtCore.Signal()
    stop_clicked = QtCore.Signal()
    delete_clicked = QtCore.Signal()
    history_clicked = QtCore.Signal()

    def __init__(self, *, title: str, subtitle: str = "", show_delete: bool = False, show_history: bool = False) -> None:
        super().__init__(FluentIcon.APPLICATION, title, subtitle)

        self.btn_config = PushButton("配置")
        self.btn_run = PushButton("运行")
        self.btn_rollback = PushButton("回退")
        self.btn_stop = PushButton("停止")
        self.btn_history = PushButton("历史")
        self.btn_delete = PushButton("删除")
        self.btn_history.setVisible(bool(show_history))
        self.btn_delete.setVisible(bool(show_delete))
        self.btn_stop.setEnabled(False)

        # Use the card's built-in expand button; do NOT add extra dropdown arrow.
        # Put action buttons on the right, just to the left of the expand button.
        layout = self.card.hBoxLayout
        expand_btn = self.card.expandButton
        idx = layout.indexOf(expand_btn)
        if idx < 0:
            # fallback
            layout.addWidget(self.btn_config)
            layout.addWidget(self.btn_run)
            layout.addWidget(self.btn_stop)
        else:
            layout.insertWidget(idx, self.btn_stop, 0, QtCore.Qt.AlignRight)
            layout.insertWidget(idx, self.btn_run, 0, QtCore.Qt.AlignRight)
            layout.insertWidget(idx, self.btn_rollback, 0, QtCore.Qt.AlignRight)
            layout.insertWidget(idx, self.btn_config, 0, QtCore.Qt.AlignRight)
            layout.insertWidget(idx, self.btn_history, 0, QtCore.Qt.AlignRight)
            layout.insertWidget(idx, self.btn_delete, 0, QtCore.Qt.AlignRight)

        self.btn_config.clicked.connect(self.config_clicked.emit)
        self.btn_run.clicked.connect(self.run_clicked.emit)
        self.btn_rollback.clicked.connect(self.rollback_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_history.clicked.connect(self.history_clicked.emit)
        self.btn_delete.clicked.connect(self.delete_clicked.emit)

        # Per-task log box in expandable panel
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("运行日志（每次运行会清空并写入新日志）")
        # prevent the card from looking "extra long" when collapsed/expanded
        self.log_box.setFixedHeight(220)
        self.viewLayout.addWidget(self.log_box)

        # Make header actions less cramped
        self.btn_config.setFixedWidth(72)
        self.btn_run.setFixedWidth(72)
        self.btn_rollback.setFixedWidth(72)
        self.btn_history.setFixedWidth(72)
        self.btn_delete.setFixedWidth(72)
        self.card.hBoxLayout.setSpacing(12)

        self.setExpand(False)
        self._adjustViewSize()

    def set_actions_enabled(self, on: bool) -> None:
        self.btn_config.setEnabled(on)
        self.btn_run.setEnabled(on)
        self.btn_rollback.setEnabled(on)
        self.btn_stop.setEnabled(not on)

    def clear_log(self) -> None:
        self.log_box.clear()

    def append_log(self, text: str) -> None:
        self.log_box.appendPlainText(text)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())
