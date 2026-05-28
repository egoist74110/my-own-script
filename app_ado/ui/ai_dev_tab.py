"""AI 开发 Tab：本地启动 AI CLI 会话，并通过 TG 桥支持远程对话。

布局上下分区：
  上：三个运行按钮 + 会话列表 + 删除按钮
  下：聚焦会话的真终端面板（自绘彩色终端，可直接敲键盘进 PTY + 一个粘长 prompt 的输入框）

只读 UiSettings.ai.tool.profiles 和 UiSettings.local_repos，不修改这些配置。
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CardWidget, InfoBar, InfoBarPosition, PushButton

from app_ado.ai_dev_session import (
    AiDevSession,
    AiDevSessionManager,
    resolve_command_executable,
)
from app_ado.models import AiCliProfile, LocalRepoEntry
from app_ado.store import load_ui_settings
from app_ado.ui.ai_dev_repo_dialog import PickLocalRepoDialog
from app_ado.ui.ai_dev_terminal import TerminalWidget
from ok.gui.widget.Tab import Tab


_BUTTON_MODELS: list[tuple[str, str]] = [
    ("claude_code", "Claude Code"),
    ("codex", "Codex"),
]


_STATUS_ZH = {
    "starting": "启动中",
    "running": "运行中",
    "waiting": "等Y/N",
    "exited": "已退出",
}


class AiDevTab(Tab):
    icon = None
    name = "AI开发"

    # 跨线程：session listener 在 reader 线程触发，UI 必须在主线程更新
    _sig_session_update = QtCore.Signal(str)  # sid
    _sig_session_exit = QtCore.Signal(str)    # sid

    def __init__(self, manager: AiDevSessionManager) -> None:
        super().__init__()
        self._manager = manager
        self._current_sid: Optional[str] = None
        self._listener_for: dict[str, callable] = {}  # sid -> listener fn
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_list_status)

        self._build_buttons_card()
        self._build_sessions_card()
        self._build_terminal_card()

        self._sig_session_update.connect(self._on_session_update_main)
        self._sig_session_exit.connect(self._on_session_exit_main)
        self._refresh_list()
        self._refresh_timer.start()

    # ------------------------------------------------------------------
    # build UI
    # ------------------------------------------------------------------

    def _build_buttons_card(self) -> None:
        w = CardWidget(self)
        row = QtWidgets.QHBoxLayout(w)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(10)

        self._btn_map: dict[str, PushButton] = {}
        for model_id, label in _BUTTON_MODELS:
            btn = PushButton(f"▶ {label} 运行")
            btn.setMinimumWidth(160)
            btn.clicked.connect(lambda _=False, mid=model_id: self._on_run_clicked(mid))
            self._btn_map[model_id] = btn
            row.addWidget(btn)

        row.addStretch(1)

        self._platform_hint = QtWidgets.QLabel()
        self._platform_hint.setStyleSheet("color: #888")
        row.addWidget(self._platform_hint)

        self.add_card("AI CLI 运行", w)
        self._refresh_buttons_state()

    def _build_sessions_card(self) -> None:
        w = CardWidget(self)
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        self._list = QtWidgets.QListWidget()
        self._list.setMinimumHeight(140)
        self._list.itemSelectionChanged.connect(self._on_list_selection_changed)
        v.addWidget(self._list)

        row = QtWidgets.QHBoxLayout()
        self._btn_delete = PushButton("删除选中会话")
        self._btn_delete.clicked.connect(self._on_delete_clicked)
        row.addWidget(self._btn_delete)
        row.addStretch(1)
        v.addLayout(row)

        self.add_card("会话列表", w)

    def _build_terminal_card(self) -> None:
        w = CardWidget(self)
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        self._term_header = QtWidgets.QLabel("（未选中会话）")
        self._term_header.setStyleSheet("font-weight:600;")
        v.addWidget(self._term_header)

        # 真终端：直接敲键盘进 PTY，彩色渲染 + 光标 + 跟随窗口 resize
        self._term_view = TerminalWidget()
        self._term_view.key_bytes.connect(self._on_term_key_bytes)
        self._term_view.paste_text.connect(self._on_term_paste)
        self._term_view.resized.connect(self._on_term_resized)
        v.addWidget(self._term_view, 1)

        self._term_hint = QtWidgets.QLabel(
            "点终端可直接敲键盘（方向键/Ctrl+C/Tab 等实时生效）；滚轮或 Shift+PgUp/PgDn 翻历史；"
            "框选后 " + ("Cmd+C 复制、Cmd+V 粘贴" if sys.platform == "darwin" else "Ctrl+Shift+C/V 复制粘贴")
        )
        self._term_hint.setStyleSheet("color:#888; font-size:11px;")
        v.addWidget(self._term_hint)

        # 输入框：粘长 prompt 用（bracketed-paste，避免被 TUI 吃掉换行）
        in_row = QtWidgets.QHBoxLayout()
        self._input = QtWidgets.QLineEdit()
        self._input.setPlaceholderText("贴长提示词，回车发送（自动追加换行）")
        self._input.returnPressed.connect(self._on_send_clicked)
        self._btn_send = PushButton("发送")
        self._btn_send.clicked.connect(self._on_send_clicked)
        in_row.addWidget(self._input, 1)
        in_row.addWidget(self._btn_send)
        v.addLayout(in_row)

        self.add_card("终端", w)
        self._set_terminal_enabled(False)

    # ------------------------------------------------------------------
    # state refresh
    # ------------------------------------------------------------------

    def _refresh_buttons_state(self) -> None:
        if sys.platform == "win32":
            for b in self._btn_map.values():
                b.setEnabled(False)
            self._platform_hint.setText("⚠ AI 开发模块当前仅支持 macOS / Linux")
            return
        self._platform_hint.setText("")
        settings = load_ui_settings()
        profiles = {p.id: p for p in (settings.ai.tool.profiles or [])}
        for model_id, label in _BUTTON_MODELS:
            btn = self._btn_map[model_id]
            profile = profiles.get(model_id)
            if profile is None or not (profile.command or "").strip():
                btn.setEnabled(False)
                btn.setToolTip(f"未配置 {label} 的启动命令（前往“AI配置”）")
                continue
            if not resolve_command_executable(profile.command):
                btn.setEnabled(False)
                btn.setToolTip(f"未找到可执行：{profile.command}（请检查 PATH 或 AI 配置）")
                continue
            btn.setEnabled(True)
            btn.setToolTip(f"启动 {label}（{profile.command}）")

    def _refresh_list(self, *, select_sid: Optional[str] = None) -> None:
        keep = select_sid or self._current_sid
        self._list.blockSignals(True)
        self._list.clear()
        infos = self._manager.list()
        target_row = -1
        for i, info in enumerate(infos):
            status_zh = _STATUS_ZH.get(info.status, info.status)
            if info.status == "exited" and info.exit_code is not None:
                status_zh = f"已退出({info.exit_code})"
            text = f"#{info.sid}  {info.model_label}   {info.repo_name}   [{status_zh}]"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, info.sid)
            self._list.addItem(item)
            if keep and info.sid == keep:
                target_row = i
        if target_row < 0 and self._list.count() > 0:
            target_row = self._list.count() - 1
        if target_row >= 0:
            self._list.setCurrentRow(target_row)
        self._list.blockSignals(False)
        self._on_list_selection_changed()

    def _refresh_list_status(self) -> None:
        # 先看 manager 和 UI 的 sid 集合是否一致；不一致说明 TG 端新建/删除过会话，整体重建
        ui_sids = {self._list.item(i).data(QtCore.Qt.UserRole) for i in range(self._list.count())}
        mgr_sids = {info.sid for info in self._manager.list()}
        if ui_sids != mgr_sids:
            # 新增的会话也要挂监听器（用于跨线程屏幕更新）
            for info in self._manager.list():
                if info.sid not in self._listener_for:
                    sess = self._manager.get(info.sid)
                    if sess:
                        self._attach_session(sess)
            self._refresh_list()
            return
        # 仅更新文本，不重建（避免选中丢失）
        for i in range(self._list.count()):
            item = self._list.item(i)
            sid = item.data(QtCore.Qt.UserRole)
            sess = self._manager.get(sid)
            if not sess:
                continue
            info = sess.info
            status_zh = _STATUS_ZH.get(info.status, info.status)
            if info.status == "exited" and info.exit_code is not None:
                status_zh = f"已退出({info.exit_code})"
            text = f"#{info.sid}  {info.model_label}   {info.repo_name}   [{status_zh}]"
            if item.text() != text:
                item.setText(text)

    def _set_terminal_enabled(self, enabled: bool) -> None:
        self._input.setEnabled(enabled)
        self._btn_send.setEnabled(enabled)
        self._term_view.set_input_enabled(enabled)

    # ------------------------------------------------------------------
    # event handlers
    # ------------------------------------------------------------------

    def _on_run_clicked(self, model_id: str) -> None:
        settings = load_ui_settings()
        profile = next((p for p in settings.ai.tool.profiles or [] if p.id == model_id), None)
        if profile is None or not (profile.command or "").strip():
            self._toast("无法运行", "AI CLI 未配置启动命令", ok=False)
            return
        if not resolve_command_executable(profile.command):
            self._toast("无法运行", f"未找到可执行：{profile.command}", ok=False)
            return
        repos = list(settings.local_repos or [])
        if not repos:
            self._toast("无法运行", "尚未配置本地仓库（请先到“代码配置 - 本地仓库”添加）", ok=False)
            return
        dlg = PickLocalRepoDialog(self, repos)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        repo = dlg.result_repo()
        if repo is None:
            return
        try:
            sess = self._manager.new(
                model_id=profile.id,
                model_label=profile.name,
                repo_id=repo.id,
                repo_name=repo.name,
                cwd=repo.path,
                command=profile.command,
            )
        except Exception as e:
            self._toast("启动失败", str(e), ok=False)
            return
        self._attach_session(sess)
        self._refresh_list(select_sid=sess.info.sid)
        self._toast("已启动", f"会话 #{sess.info.sid}（{profile.name} / {repo.name}）")

    def launch_session_with_prompt(
        self,
        *,
        profile_id: str,
        repo: LocalRepoEntry,
        initial_prompt: str,
        prompt_delay_ms: int = 2500,
    ) -> bool:
        """外部入口：在 AI 开发模块新开一个会话并自动发送 prompt。

        - 校验 profile 与可执行；不弹仓库选择对话框（仓库由调用方挑好传进来）。
        - 进程起来后延迟 ~2.5s 再灌 prompt，避免 TUI 还没准备好就被吞键。
        """
        if sys.platform == "win32":
            self._toast("无法运行", "AI 开发模块当前仅支持 macOS / Linux", ok=False)
            return False
        settings = load_ui_settings()
        profile = next((p for p in settings.ai.tool.profiles or [] if p.id == profile_id), None)
        if profile is None or not (profile.command or "").strip():
            self._toast("无法运行", f"未配置 {profile_id} 的启动命令（前往“AI配置”）", ok=False)
            return False
        if not resolve_command_executable(profile.command):
            self._toast("无法运行", f"未找到可执行：{profile.command}", ok=False)
            return False
        try:
            sess = self._manager.new(
                model_id=profile.id,
                model_label=profile.name,
                repo_id=repo.id,
                repo_name=repo.name,
                cwd=repo.path,
                command=profile.command,
            )
        except Exception as e:
            self._toast("启动失败", str(e), ok=False)
            return False
        self._attach_session(sess)
        self._refresh_list(select_sid=sess.info.sid)

        prompt = initial_prompt or ""
        if prompt:
            sid = sess.info.sid

            def _send_initial() -> None:
                target = self._manager.get(sid)
                if target is None or target.info.status == "exited":
                    return
                target.write_text(prompt, append_enter=True)

            QtCore.QTimer.singleShot(max(0, int(prompt_delay_ms)), _send_initial)

        self._toast("已启动", f"会话 #{sess.info.sid}（{profile.name} / {repo.name}）")
        return True

    def _on_list_selection_changed(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._current_sid = None
            self._term_header.setText("（未选中会话）")
            self._term_view.clear_screen()
            self._set_terminal_enabled(False)
            return
        sid = item.data(QtCore.Qt.UserRole)
        self._current_sid = sid
        sess = self._manager.get(sid)
        if not sess:
            self._term_header.setText(f"#{sid}（会话已不存在）")
            self._term_view.clear_screen()
            self._set_terminal_enabled(False)
            return
        self._term_header.setText(
            f"#{sess.info.sid}   {sess.info.model_label}   {sess.info.repo_name}   "
            f"cmd: {sess.info.command}"
        )
        live = sess.info.status != "exited"
        self._set_terminal_enabled(live)
        if live:
            rows, cols = self._term_view.grid_size()
            sess.resize(rows, cols)
        # 绑定取片接口；set_provider 内部会贴底刷新（退出的会话也能滚动回看最终输出）
        self._term_view.set_provider(sess.screen_view)
        if live:
            self._term_view.setFocus()

    def _on_delete_clicked(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._toast("提示", "请先选中要删除的会话", ok=False)
            return
        sid = item.data(QtCore.Qt.UserRole)
        sess = self._manager.get(sid)
        if not sess:
            self._refresh_list()
            return
        ok = QtWidgets.QMessageBox.question(
            self,
            "确认删除",
            f"删除会话 #{sid}（{sess.info.model_label} / {sess.info.repo_name}）？\n"
            f"将终止 PTY 进程（SIGTERM → 2s → SIGKILL）。",
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self._detach_session_listener(sid)
        self._manager.remove(sid)
        if self._current_sid == sid:
            self._current_sid = None
        self._refresh_list()
        self._toast("已删除", f"会话 #{sid} 已删除")

    def _on_send_clicked(self) -> None:
        if not self._current_sid:
            return
        sess = self._manager.get(self._current_sid)
        if not sess or sess.info.status == "exited":
            return
        text = self._input.text()
        if not text:
            return
        if not sess.write_text(text, append_enter=True):
            self._toast("发送失败", "会话可能已关闭", ok=False)
            return
        self._input.clear()

    def _current_live_session(self) -> Optional[AiDevSession]:
        if not self._current_sid:
            return None
        sess = self._manager.get(self._current_sid)
        if not sess or sess.info.status == "exited":
            return None
        return sess

    def _on_term_key_bytes(self, data: bytes) -> None:
        sess = self._current_live_session()
        if sess is not None:
            sess.write_bytes(data)

    def _on_term_paste(self, text: str) -> None:
        sess = self._current_live_session()
        if sess is not None and text:
            sess.write_text(text, append_enter=False)

    def _on_term_resized(self, rows: int, cols: int) -> None:
        sess = self._current_live_session()
        if sess is not None:
            sess.resize(rows, cols)
            self._render_screen(sess)

    # ------------------------------------------------------------------
    # session listener (cross-thread)
    # ------------------------------------------------------------------

    def _attach_session(self, sess: AiDevSession) -> None:
        sid = sess.info.sid
        if sid in self._listener_for:
            return

        def _cb(snapshot: str, awaiting_yn: bool, _sid=sid) -> None:
            self._sig_session_update.emit(_sid)
            if self._manager.get(_sid) and self._manager.get(_sid).info.status == "exited":
                self._sig_session_exit.emit(_sid)

        self._listener_for[sid] = _cb
        sess.add_listener(_cb)

    def _detach_session_listener(self, sid: str) -> None:
        cb = self._listener_for.pop(sid, None)
        if cb is None:
            return
        sess = self._manager.get(sid)
        if sess:
            sess.remove_listener(cb)

    @QtCore.Slot(str)
    def _on_session_update_main(self, sid: str) -> None:
        if sid == self._current_sid:
            sess = self._manager.get(sid)
            if sess:
                self._render_screen(sess)

    @QtCore.Slot(str)
    def _on_session_exit_main(self, sid: str) -> None:
        if sid == self._current_sid:
            self._set_terminal_enabled(False)

    def _render_screen(self, sess: AiDevSession) -> None:
        # provider 已绑定到该会话，直接重取可视片重绘
        self._term_view.refresh()

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def shutdown(self) -> None:
        for sid in list(self._listener_for.keys()):
            self._detach_session_listener(sid)
        self._refresh_timer.stop()
