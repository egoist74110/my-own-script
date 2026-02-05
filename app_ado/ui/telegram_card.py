from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, LineEdit, PushButton

from app_ado.notifier_telegram import send_telegram_message
from app_ado.secrets import get_telegram_token, set_telegram_token
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.dialogs import show_error_dialog, toast


class TelegramCard(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._settings = load_ui_settings()

        form = QFormLayout(self)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.chat_id = LineEdit(); self.chat_id.setFixedWidth(260)
        self.token = LineEdit(); self.token.setFixedWidth(260)
        self.token.setEchoMode(LineEdit.Password)
        self.token.setPlaceholderText("Bot Token（保存到钥匙串）")

        self.btn_save = PushButton("保存")
        self.btn_test = PushButton("测试通知")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_test)
        row.addStretch(1)

        form.addRow("Chat ID", self.chat_id)
        form.addRow("Bot Token", self.token)
        form.addRow(row)

        self._load()

        self.btn_save.clicked.connect(self._save)
        self.btn_test.clicked.connect(self._test)

    def _load(self):
        self._settings = load_ui_settings()
        self.chat_id.setText(self._settings.telegram_chat_id or "")
        if get_telegram_token():
            self.token.setText("********")

    def _save(self):
        chat_id = self.chat_id.text().strip()
        token = self.token.text().strip()
        if not chat_id:
            toast(self, "错误", "Chat ID 不能为空", ok=False)
            return
        self._settings.telegram_chat_id = chat_id
        save_ui_settings(self._settings)

        if token and token != "********":
            set_telegram_token(token)
            self.token.setText("********")

        toast(self, "已保存", "Telegram 配置已保存")

    def _test(self):
        s = load_ui_settings()
        token = get_telegram_token()
        if not s.telegram_chat_id:
            show_error_dialog(self, "错误", "请先填写并保存 Chat ID")
            return
        if not token:
            show_error_dialog(self, "错误", "请先填写并保存 Bot Token")
            return

        try:
            send_telegram_message(
                bot_token=token,
                chat_id=s.telegram_chat_id,
                text="my-own-script: 测试通知 ✅",
            )
            toast(self, "成功", "已发送测试通知")
        except Exception as e:
            show_error_dialog(self, "测试失败", str(e))
