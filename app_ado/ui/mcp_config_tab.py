from __future__ import annotations

import threading
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CardWidget, InfoBar, InfoBarPosition, PushButton

from app_ado.ai_work_item_flow import (
    ado_work_items_mcp_claude_cli_command,
    ado_work_items_mcp_codex_toml,
    ado_work_items_mcp_gemini_json_fragment,
    ado_work_items_mcp_launch_command,
    tool_workspace_root,
)
from app_ado.mcp_server_manager import (
    is_ado_work_items_mcp_running,
    start_ado_work_items_mcp,
    stop_ado_work_items_mcp,
)
from app_ado.ui.dialogs import show_error_dialog
from ok.gui.widget.Tab import Tab


class McpConfigTab(Tab):
    icon = None
    name = "MCP配置"

    def __init__(self):
        super().__init__()
        self._build_ado_work_items_mcp_card()
        self._load_all()
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._update_ado_work_items_mcp_status)
        self._status_timer.start()

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _build_ado_work_items_mcp_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.ado_work_items_mcp_command_edit = QtWidgets.QLineEdit()
        self.ado_work_items_mcp_command_edit.setReadOnly(True)
        self.ado_work_items_mcp_command_edit.setPlaceholderText("ADO工单MCP 启动命令")
        self.lbl_ado_work_items_mcp_status = QtWidgets.QLabel("已关闭")

        self.btn_toggle_ado_work_items_mcp = PushButton("开启 ADO工单MCP")
        self.btn_copy_ado_work_items_mcp_command = PushButton("复制启动命令")
        self.btn_copy_ado_work_items_mcp_claude = PushButton("复制Claude Code配置")
        self.btn_copy_ado_work_items_mcp_codex = PushButton("复制Codex配置")
        self.btn_copy_ado_work_items_mcp_gemini = PushButton("复制Gemini CLI配置")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_toggle_ado_work_items_mcp)
        row.addWidget(self.btn_copy_ado_work_items_mcp_command)
        row.addWidget(self.btn_copy_ado_work_items_mcp_claude)
        row.addWidget(self.btn_copy_ado_work_items_mcp_codex)
        row.addWidget(self.btn_copy_ado_work_items_mcp_gemini)
        row.addStretch(1)

        form.addRow("MCP名称", QtWidgets.QLabel("ADO工单MCP"))
        form.addRow("运行状态", self.lbl_ado_work_items_mcp_status)
        form.addRow("启动命令", self.ado_work_items_mcp_command_edit)
        form.addRow(row)

        self.btn_toggle_ado_work_items_mcp.clicked.connect(self._toggle_ado_work_items_mcp)
        self.btn_copy_ado_work_items_mcp_command.clicked.connect(self._copy_ado_work_items_mcp_command)
        self.btn_copy_ado_work_items_mcp_claude.clicked.connect(self._copy_ado_work_items_mcp_claude)
        self.btn_copy_ado_work_items_mcp_codex.clicked.connect(self._copy_ado_work_items_mcp_codex)
        self.btn_copy_ado_work_items_mcp_gemini.clicked.connect(self._copy_ado_work_items_mcp_gemini)

        self.add_card("ADO工单MCP", w)

    def _load_all(self) -> None:
        self.ado_work_items_mcp_command_edit.setText(ado_work_items_mcp_launch_command())
        self._update_ado_work_items_mcp_status()

    def _repo_root(self) -> Path:
        return tool_workspace_root()

    def _copy_text(self, text: str, ok_message: str) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.clipboard().setText(text)
        self._toast("已复制", ok_message)

    def _copy_ado_work_items_mcp_command(self) -> None:
        self._copy_text(ado_work_items_mcp_launch_command(), "ADO工单MCP 启动命令已复制")

    def _copy_ado_work_items_mcp_claude(self) -> None:
        self._copy_text(
            ado_work_items_mcp_claude_cli_command(),
            "Claude Code 接入命令已复制，粘贴到终端执行后重启 Claude Code 生效",
        )

    def _copy_ado_work_items_mcp_codex(self) -> None:
        self._copy_text(ado_work_items_mcp_codex_toml(), "ADO工单MCP 的 Codex 配置已复制")

    def _copy_ado_work_items_mcp_gemini(self) -> None:
        self._copy_text(
            ado_work_items_mcp_gemini_json_fragment(),
            "Gemini CLI 配置片段已复制，合并到 ~/.gemini/settings.json 的 mcpServers 段",
        )

    def _update_ado_work_items_mcp_status(self) -> None:
        if is_ado_work_items_mcp_running():
            self.lbl_ado_work_items_mcp_status.setText("已开启")
            self.btn_toggle_ado_work_items_mcp.setText("关闭 ADO工单MCP")
        else:
            self.lbl_ado_work_items_mcp_status.setText("已关闭")
            self.btn_toggle_ado_work_items_mcp.setText("开启 ADO工单MCP")

    def _toggle_ado_work_items_mcp(self) -> None:
        if is_ado_work_items_mcp_running():
            self._stop_ado_work_items_mcp()
        else:
            self._start_ado_work_items_mcp()

    def _start_ado_work_items_mcp(self) -> None:
        result: dict[str, object] = {}

        def run() -> None:
            ok, msg = start_ado_work_items_mcp()
            result["ok"] = ok
            result["message"] = msg

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            self._update_ado_work_items_mcp_status()
            if bool(result.get("ok")):
                self._toast("ADO工单MCP", "ADO工单MCP 已开启")
            else:
                show_error_dialog(self, "ADO工单MCP 启动失败", str(result.get("message") or "未知错误"))

        QtCore.QTimer.singleShot(80, finish)

    def _stop_ado_work_items_mcp(self) -> None:
        ok, msg = stop_ado_work_items_mcp()
        self._update_ado_work_items_mcp_status()
        if ok:
            self._toast("ADO工单MCP", "ADO工单MCP 已关闭")
        else:
            show_error_dialog(self, "ADO工单MCP 关闭失败", msg)
