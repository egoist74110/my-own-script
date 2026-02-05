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
        self.btn_check = PushButton("检查 Bot Token")
        self.btn_detect = PushButton("获取 Chat ID（短轮询）")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_test)
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_detect)
        row.addStretch(1)

        form.addRow("Chat ID", self.chat_id)
        form.addRow("Bot Token", self.token)
        form.addRow(row)

        self._load()

        self.btn_save.clicked.connect(self._save)
        self.btn_test.clicked.connect(self._test)
        self.btn_check.clicked.connect(self._check)
        self.btn_detect.clicked.connect(self._detect)

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

    def _check(self):
        token = get_telegram_token()
        if not token:
            show_error_dialog(self, "错误", "请先填写并保存 Bot Token")
            return
        try:
            from app_ado.notifier_telegram_meta import get_me

            info = get_me(bot_token=token)
            toast(self, "Token 正常", f"bot_id={info.id} @{info.username or ''}")
        except Exception as e:
            show_error_dialog(self, "检查失败", str(e))

    def _detect(self):
        token = get_telegram_token()
        if not token:
            show_error_dialog(self, "错误", "请先填写并保存 Bot Token")
            return

        toast(
            self,
            "提示",
            "请先在 Telegram 里给该机器人发一条新消息（如：hi），然后点此按钮。\n"
            "（短轮询，不会长时间占用 getUpdates）",
            ok=True,
        )

        import threading
        result = None

        def run():
            nonlocal result
            try:
                from app_ado.notifier_telegram_updates import list_chat_candidates

                result = list_chat_candidates(bot_token=token, limit=30)
            except Exception as e:
                result = e

        self.btn_detect.setEnabled(False)
        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish():
            nonlocal result
            if th.is_alive():
                QtCore.QTimer.singleShot(120, finish)
                return
            self.btn_detect.setEnabled(True)
            if isinstance(result, Exception):
                show_error_dialog(self, "获取失败", str(result))
                return
            candidates = result or []
            if not candidates:
                show_error_dialog(self, "未找到", "没有从 getUpdates 里读到任何 chat。\n\n请确认：\n- 你已经给机器人发过消息\n- 机器人 Token 正确\n- 机器人没有被 Privacy Mode 限制（群里需要 @bot 或给权限）")
                return

            items = [f"{c.title} ({c.kind})" + (f" @{c.username}" if c.username else "") + f"\nchat_id={c.chat_id}" for c in candidates]
            choice, ok = QtWidgets.QInputDialog.getItem(self, "选择 Chat", "从最近消息检测到以下 Chat：", items, 0, False)
            if not ok or not choice:
                return
            # parse chat_id from last line
            chat_id = choice.split("chat_id=", 1)[-1].strip()
            self.chat_id.setText(chat_id)
            toast(self, "已填入", f"Chat ID 已填入：{chat_id}")

        QtCore.QTimer.singleShot(120, finish)

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
