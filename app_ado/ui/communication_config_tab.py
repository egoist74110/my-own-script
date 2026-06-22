from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, ComboBox, LineEdit, PushButton

from app_ado.ui.telegram_card import TelegramCard
from ok.gui.widget.Tab import Tab


class CommunicationConfigTab(Tab):
    icon = None
    name = "通讯配置"

    def __init__(self):
        super().__init__()
        self._build_telegram_card()
        self._build_ai_bot_card()
        self._build_tg_status_card()

    def _build_telegram_card(self) -> None:
        w = TelegramCard(self)
        self.add_card("Telegram 通知（本地配置）", w)

    # ---------- AI 机器人配置 ----------

    def _build_ai_bot_card(self) -> None:
        """给每个 AI 配一个独立 Telegram 机器人：左标题 / 中选择栏 / 右编辑。

        选择栏复用「AI配置」里的 AI 工具列表（ai.tool.profiles）；点「编辑」弹窗填该
        AI 的 Bot Token（存钥匙串）和可选 @用户名。配置后该 AI 的对话只走它自己的机器人。
        """
        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.ai_bot_combo = ComboBox()
        self.ai_bot_combo.setFixedWidth(220)
        self.lbl_ai_bot_state = QtWidgets.QLabel("-")
        self.lbl_ai_bot_state.setWordWrap(True)
        self.btn_ai_bot_edit = PushButton("编辑")

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.ai_bot_combo)
        row.addWidget(self.lbl_ai_bot_state, 1)
        row.addWidget(self.btn_ai_bot_edit)
        cont = QtWidgets.QWidget()
        cont.setLayout(row)
        form.addRow("AI 机器人", cont)

        tip = QtWidgets.QLabel(
            "给每个 AI 配一个独立 Telegram 机器人（BotFather 的 Bot Token）。"
            "配置后该 AI 的对话只走它自己的机器人，不再和任务通知混在一起。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: gray;")
        form.addRow(tip)

        self.ai_bot_combo.currentIndexChanged.connect(self._refresh_ai_bot_state)
        self.btn_ai_bot_edit.clicked.connect(self._edit_ai_bot)
        self._reload_ai_bot_combo()
        self.add_card("AI 机器人配置", w)

    def _reload_ai_bot_combo(self) -> None:
        from app_ado.store import load_ui_settings

        s = load_ui_settings()
        cur = self.ai_bot_combo.currentData()
        self.ai_bot_combo.blockSignals(True)
        self.ai_bot_combo.clear()
        for p in (s.ai.tool.profiles or []):
            self.ai_bot_combo.addItem(p.name, userData=p.id)
        if cur is not None:
            idx = self.ai_bot_combo.findData(cur)
            if idx >= 0:
                self.ai_bot_combo.setCurrentIndex(idx)
        self.ai_bot_combo.blockSignals(False)
        self._refresh_ai_bot_state()

    def _current_ai_id(self) -> str | None:
        data = self.ai_bot_combo.currentData()
        return str(data) if data else None

    def _refresh_ai_bot_state(self) -> None:
        from app_ado.secrets import get_ai_bot_token
        from app_ado.store import load_ui_settings

        ai_id = self._current_ai_id()
        if not ai_id:
            self.lbl_ai_bot_state.setText("（未配置任何 AI 工具，请先到「AI配置」添加）")
            return
        has_token = bool(get_ai_bot_token(ai_id))
        s = load_ui_settings()
        username = ""
        for b in (s.ai.bots or []):
            if b.ai_id == ai_id:
                username = (b.username or "").strip()
                break
        if has_token:
            self.lbl_ai_bot_state.setText("🟢 已配置机器人" + (f"（{username}）" if username else ""))
        else:
            self.lbl_ai_bot_state.setText("⚪ 未配置机器人")

    def _edit_ai_bot(self) -> None:
        """和主机器人一样的配法：只填 Bot Token，点【检查】自动识别 @用户名。

        说明给用户：机器人必须有 Token 才能收发消息，Token 是 BotFather 创建机器人时
        给的（和当初配主机器人填的是同一类东西）；Telegram 没有「用户名换 Token」的接口，
        所以这里也只能填 Token，@用户名由 Token 自动检测、无需手输。
        """
        from app_ado.secrets import (
            delete_ai_bot_token,
            get_ai_bot_token,
            set_ai_bot_token,
        )
        from app_ado.models import AiBotBinding
        from app_ado.store import load_ui_settings, save_ui_settings

        ai_id = self._current_ai_id()
        if not ai_id:
            return
        ai_name = self.ai_bot_combo.currentText()
        has_token = bool(get_ai_bot_token(ai_id))
        s = load_ui_settings()
        username = ""
        for b in (s.ai.bots or []):
            if b.ai_id == ai_id:
                username = (b.username or "").strip()
                break

        dlg = QtWidgets.QDialog(self.window())
        dlg.setWindowTitle(f"{ai_name} 机器人配置")
        dlg.setMinimumWidth(420)
        form = QFormLayout(dlg)

        ed_token = LineEdit()
        ed_token.setEchoMode(LineEdit.Password)
        ed_token.setPlaceholderText("BotFather 给的 Bot Token，如 123456:ABC-xxx")
        if has_token:
            ed_token.setText("********")

        lbl_user = QtWidgets.QLabel(username or "（未检测）")
        btn_check = PushButton("检查 Bot Token（自动识别 @用户名）")

        form.addRow("Bot Token", ed_token)
        form.addRow("@用户名", lbl_user)
        form.addRow(btn_check)

        tip = QtWidgets.QLabel(
            "怎么拿 Token：在 Telegram 找 @BotFather → /newbot 建机器人（或 /mybots 选已有的 →"
            " API Token）→ 复制那串 Token 贴到上面（和当初配主机器人一样）。\n"
            "贴好后点【检查 Bot Token】，会自动识别并填好 @用户名。\n"
            "Token 存系统钥匙串；光有 @用户名无法收发消息，必须有 Token。"
        )
        tip.setStyleSheet("color: gray;")
        tip.setWordWrap(True)
        form.addRow(tip)

        detected = {"username": username}

        def _effective_token() -> str | None:
            t = ed_token.text().strip()
            if t and t != "********":
                return t
            return get_ai_bot_token(ai_id)

        def _do_check() -> None:
            from app_ado.notifier_telegram_meta import get_me

            tok = _effective_token()
            if not tok:
                QtWidgets.QMessageBox.warning(self.window(), "缺 Token", "请先填入 Bot Token。")
                return
            btn_check.setEnabled(False)
            try:
                info = get_me(bot_token=tok)
            except Exception as e:  # noqa: BLE001
                from app_ado.ui.dialogs import show_error_dialog
                show_error_dialog(self, "检查失败", str(e))
                return
            finally:
                btn_check.setEnabled(True)
            uname = ("@" + info.username) if info.username else ""
            detected["username"] = uname
            lbl_user.setText(uname or "（该 Token 没有用户名）")
            QtWidgets.QMessageBox.information(
                self.window(), "Token 正常",
                f"bot_id={info.id} {uname}\n"
                f"接下来去 Telegram 打开 {uname or '该机器人'} 发一条 /start，AI 对话就会走它。",
            )

        btn_check.clicked.connect(_do_check)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_clear = btns.addButton("清除绑定", QtWidgets.QDialogButtonBox.DestructiveRole)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        cleared = {"v": False}

        def _do_clear() -> None:
            cleared["v"] = True
            dlg.accept()

        btn_clear.clicked.connect(_do_clear)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        s = load_ui_settings()
        bots = [b for b in (s.ai.bots or []) if b.ai_id != ai_id]

        if cleared["v"]:
            delete_ai_bot_token(ai_id)
            s.ai.bots = bots  # 同时清掉用户名绑定
            save_ui_settings(s)
            self._refresh_ai_bot_state()
            QtWidgets.QMessageBox.information(self.window(), "已清除", f"{ai_name} 的机器人绑定已清除。")
            return

        token = ed_token.text().strip()
        if token and token != "********":
            set_ai_bot_token(ai_id, token)
        elif not has_token:
            QtWidgets.QMessageBox.warning(self.window(), "未保存", "请填入 Bot Token。")
            return

        # @用户名：优先用刚检测到的；没检测过就尽力自动跑一次 getMe 补上（失败不阻断保存）
        new_user = (detected.get("username") or "").strip()
        if not new_user:
            tok = get_ai_bot_token(ai_id)
            if tok:
                try:
                    from app_ado.notifier_telegram_meta import get_me

                    info = get_me(bot_token=tok)
                    new_user = ("@" + info.username) if info.username else ""
                except Exception:
                    new_user = username  # 保留旧值

        bots.append(AiBotBinding(ai_id=ai_id, username=new_user))
        s.ai.bots = bots
        save_ui_settings(s)
        self._refresh_ai_bot_state()
        QtWidgets.QMessageBox.information(
            self.window(), "已保存", f"{ai_name} 的专属机器人已保存。重启应用后生效。"
        )

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
