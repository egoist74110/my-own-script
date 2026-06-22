from __future__ import annotations

import shlex
import subprocess
import threading
import uuid

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CardWidget, ComboBox, InfoBar, InfoBarPosition, PushButton

from app_ado.ai_headless_session import _augment_path
from app_ado.models import AiCliProfile
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.dialogs import (
    show_error_dialog,
    show_text_result_dialog,
)
from ok.gui.widget.Tab import Tab

# 三个内置（预留）AI：可以改名称/命令/升级命令，但不能删除。
# 注：id "gemini" 现在对应 Antigravity CLI（谷歌已废弃 Gemini CLI，命令 agy）。
# 内部 id 保持 "gemini" 不动，这样老用户绑的专属机器人 Token、模型协作映射都不会断。
_BUILTIN_IDS: frozenset[str] = frozenset({"codex", "gemini", "claude_code"})


class AiProfileDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self._result: AiCliProfile | None = None
        self.setWindowTitle("新增 AI 配置")
        self.setModal(True)
        self.resize(520, 200)

        root = QtWidgets.QFormLayout(self)
        root.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.name_edit = QtWidgets.QLineEdit()
        self.command_edit = QtWidgets.QLineEdit()
        self.command_edit.setPlaceholderText("例如：my-ai-cli")
        self.upgrade_edit = QtWidgets.QLineEdit()
        self.upgrade_edit.setPlaceholderText("可选，例如：npm install -g xxx@latest")
        root.addRow("名称", self.name_edit)
        root.addRow("启动命令", self.command_edit)
        root.addRow("升级命令", self.upgrade_edit)

        row = QtWidgets.QHBoxLayout()
        self.btn_cancel = PushButton("取消")
        self.btn_ok = PushButton("保存")
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        root.addRow(row)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._on_ok)

    def result_profile(self) -> AiCliProfile | None:
        return self._result

    def _on_ok(self) -> None:
        name = self.name_edit.text().strip()
        command = self.command_edit.text().strip()
        if not name:
            show_error_dialog(self, "错误", "名称不能为空")
            return
        if not command:
            show_error_dialog(self, "错误", "启动命令不能为空")
            return
        self._result = AiCliProfile(
            id=f"custom:{uuid.uuid4()}",
            name=name,
            command=command,
            upgrade_command=self.upgrade_edit.text().strip(),
            builtin=False,
        )
        self.accept()


class AiConfigTab(Tab):
    icon = None
    name = "AI配置"

    def __init__(self):
        super().__init__()
        self._settings = load_ui_settings()
        self._current_pid: str = ""
        self._migrate_and_seed_profiles()

        self._build_tool_card()
        self._refresh_profile_combo()

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, duration=1500, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    # ------------------------------------------------------------------
    # 内置 AI 的默认值（仅用于新装/补空，不覆盖用户已改过的命令）
    # ------------------------------------------------------------------

    def _default_profiles(self) -> list[AiCliProfile]:
        return [
            AiCliProfile(id="codex", name="Codex", command="codex",
                         upgrade_command="npm install -g @openai/codex@latest", builtin=True),
            AiCliProfile(id="gemini", name="Antigravity CLI", command="agy",
                         upgrade_command="agy update", builtin=True),
            AiCliProfile(id="claude_code", name="Claude Code", command="claude",
                         upgrade_command="claude update", builtin=True),
        ]

    def _migrate_and_seed_profiles(self) -> None:
        tool = self._settings.ai.tool
        existing = {x.id: x for x in (tool.profiles or [])}
        changed = False
        for profile in self._default_profiles():
            cur = existing.get(profile.id)
            if cur is None:
                existing[profile.id] = profile
                changed = True
                continue
            if not cur.builtin:
                cur.builtin = True
                changed = True
            if not cur.command.strip():
                cur.command = profile.command
                changed = True
            if not cur.name.strip():
                cur.name = profile.name
                changed = True
            # 谷歌废弃 Gemini CLI → Antigravity CLI：把内置项里残留的死名称/死命令换掉，
            # 但用户自己改过的命令（如已是 agy 或自定义）不动。
            if profile.id == "gemini":
                if cur.name.strip() in ("Gemini CLI", "Gemini"):
                    cur.name = profile.name
                    changed = True
                if cur.command.strip() == "gemini":
                    cur.command = profile.command
                    changed = True
            # 升级命令是新字段：仅在为空时补默认，已填的不动
            if not (cur.upgrade_command or "").strip() and profile.upgrade_command:
                cur.upgrade_command = profile.upgrade_command
                changed = True

        # 内置 AI 排前面、保持稳定顺序，自定义在后
        order = ["codex", "gemini", "claude_code"]
        builtins = [existing[i] for i in order if i in existing]
        customs = [p for pid, p in existing.items() if pid not in order]
        tool.profiles = builtins + customs

        if not tool.selected_profile_id or tool.selected_profile_id not in existing:
            tool.selected_profile_id = "codex"
            changed = True

        if changed:
            save_ui_settings(self._settings)
            self._settings = load_ui_settings()

    # ------------------------------------------------------------------
    # AI 工具接入卡片
    # ------------------------------------------------------------------

    def _build_tool_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.profile_combo = ComboBox()
        self.profile_combo.setFixedWidth(280)

        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("显示名称")
        self.command_edit = QtWidgets.QLineEdit()
        self.command_edit.setPlaceholderText("启动命令，例如：codex / claude")
        self.upgrade_edit = QtWidgets.QLineEdit()
        self.upgrade_edit.setPlaceholderText("升级命令，例如：npm install -g @openai/codex@latest / claude update")

        self.btn_upgrade = PushButton("升级")
        self.btn_test_tool = PushButton("测试工具")
        self.btn_add_profile = PushButton("新增")
        self.btn_delete_profile = PushButton("删除")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_upgrade)
        row.addWidget(self.btn_test_tool)
        row.addWidget(self.btn_add_profile)
        row.addWidget(self.btn_delete_profile)
        row.addStretch(1)

        # 专属机器人：和选中的这个 AI 绑定（Bot Token 存钥匙串），AI 对话走它自己的机器人。
        self.lbl_bot_state = QtWidgets.QLabel("-")
        self.lbl_bot_state.setWordWrap(True)
        self.btn_bot_edit = PushButton("编辑专属机器人")
        bot_row = QtWidgets.QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)
        bot_row.setSpacing(8)
        bot_row.addWidget(self.lbl_bot_state, 1)
        bot_row.addWidget(self.btn_bot_edit)
        bot_cont = QtWidgets.QWidget()
        bot_cont.setLayout(bot_row)

        form.addRow("AI工具", self.profile_combo)
        form.addRow("名称", self.name_edit)
        form.addRow("启动命令", self.command_edit)
        form.addRow("升级命令", self.upgrade_edit)
        form.addRow(row)
        form.addRow("专属机器人", bot_cont)

        tip = QtWidgets.QLabel(
            "三个内置 AI（Codex / Antigravity CLI / Claude Code）可改名称、命令、升级命令，但不能删除；"
            "改完移开光标即自动生效，无需确认。点「升级」会跑上面的升级命令。\n"
            "「专属机器人」给当前选中的 AI 绑一个 Telegram 机器人，它的对话只走自己的机器人，不和任务通知混在一起。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: gray;")
        form.addRow(tip)

        self.profile_combo.currentIndexChanged.connect(self._load_selected_profile)
        self.btn_bot_edit.clicked.connect(self._edit_bot)
        # 改完即生效（移开光标 / 回车触发），不需要保存按钮
        self.name_edit.editingFinished.connect(self._autosave)
        self.command_edit.editingFinished.connect(self._autosave)
        self.upgrade_edit.editingFinished.connect(self._autosave)
        self.btn_upgrade.clicked.connect(self._upgrade_tool)
        self.btn_test_tool.clicked.connect(self._test_tool)
        self.btn_add_profile.clicked.connect(self._add_profile)
        self.btn_delete_profile.clicked.connect(self._delete_profile)

        self.add_card("AI工具接入", w)

    # ------------------------------------------------------------------
    # 读取 / 选择
    # ------------------------------------------------------------------

    def _refresh_profile_combo(self) -> None:
        self._settings = load_ui_settings()
        selected = self._settings.ai.tool.selected_profile_id
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        idx = 0
        for i, profile in enumerate(self._settings.ai.tool.profiles or []):
            self.profile_combo.addItem(profile.name, userData=profile.id)
            if profile.id == selected:
                idx = i
        if self.profile_combo.count() > 0:
            self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._load_selected_profile()

    def _selected_profile(self) -> AiCliProfile | None:
        pid = self.profile_combo.currentData()
        return next((x for x in (self._settings.ai.tool.profiles or []) if x.id == pid), None)

    def _load_selected_profile(self) -> None:
        self._settings = load_ui_settings()
        profile = self._selected_profile()
        if profile is None:
            self._current_pid = ""
            for ed in (self.name_edit, self.command_edit, self.upgrade_edit):
                ed.blockSignals(True); ed.setText(""); ed.blockSignals(False)
            self.btn_delete_profile.setEnabled(False)
            self.btn_upgrade.setEnabled(False)
            self._refresh_bot_state()
            return
        self._current_pid = profile.id
        for ed, val in (
            (self.name_edit, profile.name),
            (self.command_edit, profile.command),
            (self.upgrade_edit, profile.upgrade_command),
        ):
            ed.blockSignals(True)
            ed.setText(val or "")
            ed.blockSignals(False)
        # 内置 AI 不能删；其余可删
        self.btn_delete_profile.setEnabled(profile.id not in _BUILTIN_IDS and not bool(profile.builtin))
        self.btn_upgrade.setEnabled(True)
        self._refresh_bot_state()
        # 切换 AI 即记住选择
        if self._settings.ai.tool.selected_profile_id != profile.id:
            self._settings.ai.tool.selected_profile_id = profile.id
            save_ui_settings(self._settings)

    # ------------------------------------------------------------------
    # 自动保存（改了就生效，不用确认）
    # ------------------------------------------------------------------

    def _autosave(self) -> None:
        pid = self._current_pid
        if not pid:
            return
        self._settings = load_ui_settings()
        profile = next((x for x in (self._settings.ai.tool.profiles or []) if x.id == pid), None)
        if profile is None:
            return

        new_name = self.name_edit.text().strip()
        new_cmd = self.command_edit.text().strip()
        new_up = self.upgrade_edit.text().strip()

        # 名称不能清空：空了就还原显示
        if not new_name:
            self.name_edit.blockSignals(True)
            self.name_edit.setText(profile.name)
            self.name_edit.blockSignals(False)
            new_name = profile.name

        if (new_name == profile.name and new_cmd == profile.command
                and new_up == (profile.upgrade_command or "")):
            return  # 没变化，别瞎存

        profile.name = new_name
        profile.command = new_cmd
        profile.upgrade_command = new_up
        save_ui_settings(self._settings)

        # 同步下拉里显示的名称
        i = self.profile_combo.currentIndex()
        if i >= 0:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setItemText(i, new_name)
            self.profile_combo.blockSignals(False)
        self._toast("已生效", f"{new_name} 已更新")

    # ------------------------------------------------------------------
    # 升级 / 测试 / 新增 / 删除
    # ------------------------------------------------------------------

    def _run_command_async(
        self, title: str, command: str, *, timeout: int,
        busy_button: PushButton | None = None, busy_text: str = "升级中…",
    ) -> None:
        """后台跑一条命令，跑完弹结果。用于升级（耗时）/测试。

        busy_button：跑命令期间禁用并显示 loading 文案，跑完恢复。
        """
        parts = shlex.split(command)
        if not parts:
            show_error_dialog(self, title, "命令格式无效")
            return
        self._toast("执行中", f"正在运行：{command}")

        old_text = ""
        if busy_button is not None:
            old_text = busy_button.text()
            busy_button.setEnabled(False)
            busy_button.setText(busy_text)

        result: dict[str, object] = {}

        def run() -> None:
            try:
                env = _augment_path(__import__("os").environ.copy())
                cp = subprocess.run(
                    parts, capture_output=True, text=True, timeout=timeout, env=env,
                )
                out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
                result["ok"] = cp.returncode == 0
                result["code"] = cp.returncode
                result["out"] = out.strip() or "(无输出)"
            except Exception as e:
                result["ok"] = False
                result["out"] = str(e)

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(120, finish)
                return
            if busy_button is not None:
                busy_button.setEnabled(True)
                busy_button.setText(old_text)
            ok = bool(result.get("ok"))
            summary = ("成功" if ok else f"失败（退出码 {result.get('code', '?')}）")
            show_text_result_dialog(self, title, f"命令：{command}\n结果：{summary}", str(result.get("out") or ""))
            self._toast(title, summary, ok=ok)

        QtCore.QTimer.singleShot(120, finish)

    def _upgrade_tool(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            show_error_dialog(self, "升级失败", "请先选择 AI 工具")
            return
        command = self.upgrade_edit.text().strip()
        if not command:
            show_error_dialog(self, "升级失败", "请先填写升级命令（保存后再点升级）")
            return
        self._autosave()  # 确保升级命令已落盘
        self._run_command_async(
            f"升级 {profile.name}", command, timeout=600,
            busy_button=self.btn_upgrade, busy_text="升级中…",
        )

    def _test_tool(self) -> None:
        command = self.command_edit.text().strip()
        if not command:
            show_error_dialog(self, "测试失败", "请先填写启动命令")
            return
        parts = shlex.split(command)
        if not parts:
            show_error_dialog(self, "测试失败", "命令格式无效")
            return
        self._toast("测试中", "正在检测命令是否可用")
        result: dict[str, object] = {}

        def run() -> None:
            try:
                env = _augment_path(__import__("os").environ.copy())
                cp = subprocess.run(parts[:1] + ["--help"], capture_output=True, text=True, timeout=15, env=env)
                result["ok"] = cp.returncode == 0
            except Exception as e:
                result["ok"] = False
                result["message"] = str(e)

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            if bool(result.get("ok")):
                self._toast("测试结果", "测试正常")
            else:
                show_error_dialog(self, "测试结果", str(result.get("message") or "命令不可用"))

        QtCore.QTimer.singleShot(80, finish)

    # ------------------------------------------------------------------
    # 专属机器人（绑到当前选中的 AI；Bot Token 存钥匙串，@用户名存 ai.bots）
    # ------------------------------------------------------------------

    def _refresh_bot_state(self) -> None:
        from app_ado.secrets import get_ai_bot_token

        pid = self._current_pid
        if not pid:
            self.lbl_bot_state.setText("（未选择 AI）")
            self.btn_bot_edit.setEnabled(False)
            return
        self.btn_bot_edit.setEnabled(True)
        has_token = bool(get_ai_bot_token(pid))
        username = ""
        for b in (self._settings.ai.bots or []):
            if b.ai_id == pid:
                username = (b.username or "").strip()
                break
        if has_token:
            self.lbl_bot_state.setText("🟢 已配置机器人" + (f"（{username}）" if username else ""))
        else:
            self.lbl_bot_state.setText("⚪ 未配置机器人")

    def _edit_bot(self) -> None:
        """给当前选中的 AI 配专属机器人：只填 Bot Token，点【检查】自动识别 @用户名。

        机器人必须有 Token 才能收发消息（BotFather 给的，和主机器人一样）；Telegram 没有
        「用户名换 Token」的接口，所以这里只填 Token，@用户名由 Token 自动检测、无需手输。
        """
        from app_ado.secrets import (
            delete_ai_bot_token,
            get_ai_bot_token,
            set_ai_bot_token,
        )
        from app_ado.models import AiBotBinding

        profile = self._selected_profile()
        if profile is None:
            return
        ai_id = profile.id
        ai_name = profile.name
        has_token = bool(get_ai_bot_token(ai_id))
        self._settings = load_ui_settings()
        username = ""
        for b in (self._settings.ai.bots or []):
            if b.ai_id == ai_id:
                username = (b.username or "").strip()
                break

        dlg = QtWidgets.QDialog(self.window())
        dlg.setWindowTitle(f"{ai_name} 专属机器人")
        dlg.setMinimumWidth(440)
        form = QtWidgets.QFormLayout(dlg)

        ed_token = QtWidgets.QLineEdit()
        ed_token.setEchoMode(QtWidgets.QLineEdit.Password)
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

        def _dlg_toast(title: str, content: str, ok: bool = True) -> None:
            # 弹窗对齐全局风格：用 InfoBar（不用 Qt 自带 QMessageBox）；在模态对话框内就挂到 dlg 上才看得见。
            if ok:
                InfoBar.success(title, content, duration=2500, position=InfoBarPosition.TOP, parent=dlg)
            else:
                InfoBar.error(title, content, duration=3500, position=InfoBarPosition.TOP, parent=dlg)

        def _do_check() -> None:
            tok = _effective_token()
            if not tok:
                _dlg_toast("缺 Token", "请先填入 Bot Token。", ok=False)
                return

            # 异步检查：不在 UI 线程里跑 get_me，避免卡住主程序；按钮给 loading 态。
            btn_check.setEnabled(False)
            old_text = btn_check.text()
            btn_check.setText("检查中…")

            result: dict[str, object] = {}

            def run() -> None:
                try:
                    from app_ado.notifier_telegram_meta import get_me

                    result["info"] = get_me(bot_token=tok)
                except Exception as e:  # noqa: BLE001
                    result["error"] = e

            th = threading.Thread(target=run, daemon=True)
            th.start()

            def finish() -> None:
                if th.is_alive():
                    QtCore.QTimer.singleShot(150, finish)
                    return
                btn_check.setEnabled(True)
                btn_check.setText(old_text)
                if "error" in result:
                    show_error_dialog(self, "检查失败", str(result["error"]))
                    return
                info = result["info"]
                uname = ("@" + info.username) if info.username else ""
                detected["username"] = uname
                lbl_user.setText(uname or "（该 Token 没有用户名）")
                _dlg_toast(
                    "Token 正常",
                    f"bot_id={info.id} {uname}；去 Telegram 给 {uname or '该机器人'} 发一条 /start，AI 对话就会走它。",
                )

            QtCore.QTimer.singleShot(150, finish)

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

        self._settings = load_ui_settings()
        bots = [b for b in (self._settings.ai.bots or []) if b.ai_id != ai_id]

        if cleared["v"]:
            delete_ai_bot_token(ai_id)
            self._settings.ai.bots = bots
            save_ui_settings(self._settings)
            self._refresh_bot_state()
            self._toast("已清除", f"{ai_name} 的机器人绑定已清除。")
            return

        token = ed_token.text().strip()
        if token and token != "********":
            set_ai_bot_token(ai_id, token)
        elif not has_token:
            self._toast("未保存", "请填入 Bot Token。", ok=False)
            return

        # @用户名只用于显示：优先用「检查」时检测到的，没有就沿用旧值，绝不在这里同步联网（会卡主程序）。
        new_user = (detected.get("username") or "").strip() or username

        bots.append(AiBotBinding(ai_id=ai_id, username=new_user))
        self._settings.ai.bots = bots
        save_ui_settings(self._settings)
        self._refresh_bot_state()
        self._toast("已保存", f"{ai_name} 的专属机器人已保存。重启应用后生效。")

    def _add_profile(self) -> None:
        dlg = AiProfileDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        profile = dlg.result_profile()
        if profile is None:
            return
        self._settings = load_ui_settings()
        self._settings.ai.tool.profiles.append(profile)
        self._settings.ai.tool.selected_profile_id = profile.id
        save_ui_settings(self._settings)
        self._refresh_profile_combo()
        self._toast("已新增", f"AI 工具已创建：{profile.name}")

    def _delete_profile(self) -> None:
        self._settings = load_ui_settings()
        profile = self._selected_profile()
        if profile is None:
            return
        if profile.id in _BUILTIN_IDS or profile.builtin:
            show_error_dialog(self, "提示", "内置 AI 不能删除（只能改名称/命令/升级命令）")
            return
        from app_ado.ui.confirm import show_confirm_dialog

        if not show_confirm_dialog(self, "确认删除", f"删除 AI 工具：{profile.name}？"):
            return
        self._settings.ai.tool.profiles = [x for x in (self._settings.ai.tool.profiles or []) if x.id != profile.id]
        if self._settings.ai.tool.selected_profile_id == profile.id:
            self._settings.ai.tool.selected_profile_id = "codex"
        save_ui_settings(self._settings)
        self._refresh_profile_combo()
        self._toast("已删除", f"AI 工具已删除：{profile.name}")
