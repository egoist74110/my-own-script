from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, ComboBox, LineEdit, PushButton

from app_ado.secrets import get_telegram_token, set_telegram_token
from app_ado.store import load_ui_settings, save_ui_settings


from app_ado.ui.telegram_acl_mixin import TelegramAclMixin


class TelegramCard(CardWidget, TelegramAclMixin):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._settings = load_ui_settings()

        form = QFormLayout(self)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        # 只填 Bot Token：和「AI配置」里专属机器人对齐——不再手填 Chat ID，
        # owner 在机器人收到第一条私聊时自动绑定；@用户名由 Token 自动检测。
        self.token = LineEdit(); self.token.setFixedWidth(260)
        self.token.setEchoMode(LineEdit.Password)
        self.token.setPlaceholderText("BotFather 给的 Bot Token，如 123456:ABC-xxx")

        self.lbl_username = QtWidgets.QLabel("（未检测）")

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

        form.addRow("Bot Token", self.token)
        form.addRow("@用户名", self.lbl_username)
        form.addRow(self.control_enabled)

        form.addRow("权限组", self._row(self.group_combo, self._row(self.btn_new_group, self._row(self.btn_edit_group, self.btn_del_group))))
        form.addRow("组成员", self._row(self.member_combo, self._row(self.btn_new_member, self._row(self.btn_edit_member, self.btn_del_member))))

        self.notify_details = QtWidgets.QCheckBox("通知包含细节（repo/分支/URL 等，可能泄露信息）")
        self.notify_details.setChecked(bool(getattr(self._settings, "telegram_notify_include_details", False)))

        form.addRow("白名单(旧)", self.whitelist)
        form.addRow(self.notify_details)

        self._load()

        # 自动保存：填好 Token 失焦即存进钥匙串并自动识别 @用户名；其余选项一改就存。
        self.token.editingFinished.connect(self._on_token_edited)
        self.control_enabled.toggled.connect(self._save_settings)
        self.notify_details.toggled.connect(self._save_settings)
        self.whitelist.installEventFilter(self)

        # hint
        self.hint = QtWidgets.QLabel(
            "说明：\n"
            "1) 把 BotFather 给的 Bot Token 粘进上面输入框，失焦自动保存到钥匙串并识别 @用户名。\n"
            "2) 去 Telegram 打开该机器人，发一条 /start —— 第一个私聊它的人会自动绑定为 owner，"
            "之后的任务通知就发给你，无需再手填 Chat ID。"
        )
        self.hint.setWordWrap(True)
        form.addRow(self.hint)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt 命名)
        # 注意：Qt 在构造期间就可能回调本方法，此时 whitelist 尚未建好，用 getattr 兜底。
        if obj is getattr(self, "whitelist", None) and event.type() == QtCore.QEvent.FocusOut:
            self._save_settings()
        return super().eventFilter(obj, event)

    def _load(self):
        self._settings = load_ui_settings()
        self.control_enabled.setChecked(bool(self._settings.telegram_control_enabled))
        self.notify_details.setChecked(bool(getattr(self._settings, "telegram_notify_include_details", False)))
        self.whitelist.setPlainText("\n".join(self._settings.telegram_whitelist or []))
        self._refresh_acl_ui()
        if get_telegram_token():
            self.token.setText("********")
            self._detect_username()

    def _save_settings(self):
        s = load_ui_settings()
        s.telegram_control_enabled = bool(self.control_enabled.isChecked())
        s.telegram_notify_include_details = bool(self.notify_details.isChecked())
        s.telegram_whitelist = [x.strip() for x in (self.whitelist.toPlainText() or "").splitlines() if x.strip()]
        save_ui_settings(s)
        self._settings = s

    def _on_token_edited(self):
        token = self.token.text().strip()
        if not token or token == "********":
            return
        set_telegram_token(token)
        self.token.setText("********")
        self._detect_username()

    def _detect_username(self):
        """后台用 get_me 验证 Token 并回填 @用户名（不阻塞 UI）。"""
        token = get_telegram_token()
        if not token:
            self.lbl_username.setText("（未检测）")
            return
        self.lbl_username.setText("检测中…")

        import threading

        result: dict[str, object] = {}

        def run():
            try:
                from app_ado.notifier_telegram_meta import get_me

                info = get_me(bot_token=token)
                result["username"] = ("@" + info.username) if info.username else ""
            except Exception as e:  # noqa: BLE001
                result["error"] = e

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish():
            if th.is_alive():
                QtCore.QTimer.singleShot(150, finish)
                return
            if "error" in result:
                self.lbl_username.setText("（Token 无效或网络错误）")
                return
            self.lbl_username.setText(str(result.get("username") or "（该 Token 无用户名）"))

        QtCore.QTimer.singleShot(150, finish)
