from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, LineEdit, PushButton

from app_ado.notifier_telegram import send_telegram_message
from app_ado.secrets import get_telegram_token, set_telegram_token
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.dialogs import show_error_dialog, toast


from app_ado.ui.telegram_acl_mixin import TelegramAclMixin


class TelegramCard(CardWidget, TelegramAclMixin):
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

        self.control_enabled = QtWidgets.QCheckBox("启用 Telegram 触发任务（仅程序运行期间有效）")
        self.control_enabled.setChecked(bool(self._settings.telegram_control_enabled))

        # ACL UI
        self.group_combo = ComboBox(); self.group_combo.setFixedWidth(260)
        self.btn_new_group = PushButton("新增")
        self.btn_edit_group = PushButton("编辑")
        self.btn_del_group = PushButton("删除")

        self.member_combo = ComboBox(); self.member_combo.setFixedWidth(260)
        self.btn_new_member = PushButton("新增")
        self.btn_edit_member = PushButton("编辑")
        self.btn_del_member = PushButton("删除")

        self.btn_new_group.clicked.connect(self._new_group)
        self.btn_edit_group.clicked.connect(self._edit_group)
        self.btn_del_group.clicked.connect(self._del_group)

        self.btn_new_member.clicked.connect(self._new_member)
        self.btn_edit_member.clicked.connect(self._edit_member)
        self.btn_del_member.clicked.connect(self._del_member)

        self.whitelist = QtWidgets.QPlainTextEdit()
        self.whitelist.setPlaceholderText("白名单（兼容旧用法，默认仅允许 status/help）：\n每行一个 chat_id 或 @username")
        self.whitelist.setFixedHeight(80)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_test)
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_detect)
        row.addStretch(1)

        form.addRow("Chat ID", self.chat_id)
        form.addRow("Bot Token", self.token)
        form.addRow(row)
        form.addRow(self.control_enabled)

        form.addRow("权限组", self._row(self.group_combo, self._row(self.btn_new_group, self._row(self.btn_edit_group, self.btn_del_group))))
        form.addRow("组成员", self._row(self.member_combo, self._row(self.btn_new_member, self._row(self.btn_edit_member, self.btn_del_member))))

        form.addRow("白名单(旧)", self.whitelist)

        self._load()

        self.btn_save.clicked.connect(self._save)
        self.btn_test.clicked.connect(self._test)
        self.btn_check.clicked.connect(self._check)
        self.btn_detect.clicked.connect(self._detect)

        # hint
        self.hint = QtWidgets.QLabel(
            "说明：\n"
            "1) 先保存 Bot Token，然后点【检查 Bot Token】确认 @username。\n"
            "2) 去 Telegram 打开该机器人，发一条消息（hi / /start）。\n"
            "3) 回来点【获取 Chat ID】即可自动填入。\n"
            "（私聊时 Chat ID 会是你的数字 id；群聊则是群 id -100...）"
        )
        self.hint.setWordWrap(True)
        form.addRow(self.hint)

    def _load(self):
        self._settings = load_ui_settings()
        self.chat_id.setText(self._settings.telegram_chat_id or "")
        self.control_enabled.setChecked(bool(self._settings.telegram_control_enabled))
        self.whitelist.setPlainText("\n".join(self._settings.telegram_whitelist or []))
        self._refresh_acl_ui()
        if get_telegram_token():
            self.token.setText("********")

    def _save(self):
        chat_id = self.chat_id.text().strip()
        token = self.token.text().strip()

        # Save token first
        if token and token != "********":
            set_telegram_token(token)
            self.token.setText("********")

        # save settings
        self._settings = load_ui_settings()
        self._settings.telegram_control_enabled = bool(self.control_enabled.isChecked())
        wl = [x.strip() for x in (self.whitelist.toPlainText() or "").splitlines() if x.strip()]
        self._settings.telegram_whitelist = wl

        if not chat_id:
            toast(self, "提示", "Chat ID 为空：你可以先检查 Token，然后发消息后用【获取 Chat ID】自动填入", ok=False)
        else:
            self._settings.telegram_chat_id = chat_id

        save_ui_settings(self._settings)
        toast(self, "已保存", "Telegram 配置已保存")

    def _effective_token(self) -> str | None:
        t = self.token.text().strip()
        if t and t != "********":
            return t
        return get_telegram_token()

    def _check(self):
        token = self._effective_token()
        if not token:
            show_error_dialog(self, "错误", "请先填写并保存 Bot Token")
            return
        try:
            from app_ado.notifier_telegram_meta import get_me

            info = get_me(bot_token=token)
            toast(self, "Token 正常", f"bot_id={info.id} @{info.username or ''}\n请去 Telegram 打开 @{info.username or ''} 并发一条消息，然后点【获取 Chat ID】")
        except Exception as e:
            show_error_dialog(self, "检查失败", str(e))

    def _detect(self):
        token = self._effective_token()
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
