from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, PushButton

from app_ado.ui.telegram_card import TelegramCard
from ok.gui.widget.Tab import Tab


class CommunicationConfigTab(Tab):
    icon = None
    name = "通讯配置"

    def __init__(self):
        super().__init__()
        self._build_telegram_card()
        self._build_tg_status_card()

    def _build_telegram_card(self) -> None:
        w = TelegramCard(self)
        self.add_card("Telegram 通知（本地配置）", w)

    def _build_tg_status_card(self) -> None:
        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.lbl_tg_state = QtWidgets.QLabel("未知")
        self.lbl_tg_last = QtWidgets.QLabel("-")
        self.lbl_tg_err = QtWidgets.QLabel("-")
        self.lbl_tg_err.setWordWrap(True)

        self.btn_tg_refresh = PushButton("刷新")

        form.addRow("TG 控制状态", self.lbl_tg_state)
        form.addRow("最近轮询", self.lbl_tg_last)
        form.addRow("最后错误", self.lbl_tg_err)
        form.addRow(self.btn_tg_refresh)

        self.btn_tg_refresh.clicked.connect(self._refresh_tg_status)
        self._refresh_tg_status()

        self.add_card("TG 控制（状态）", w)

    def _refresh_tg_status(self) -> None:
        try:
            from app_ado.store import config_dir

            p = config_dir() / "tg_control_state.json"
            if not p.exists():
                self.lbl_tg_state.setText("未运行")
                self.lbl_tg_last.setText("-")
                self.lbl_tg_err.setText("-")
                return
            import json

            j = json.loads(p.read_text("utf-8"))
            self.lbl_tg_state.setText(j.get("state") or "未知")
            self.lbl_tg_last.setText(j.get("last_poll") or "-")
            self.lbl_tg_err.setText(j.get("last_error") or "-")
        except Exception as e:
            self.lbl_tg_err.setText(str(e))
