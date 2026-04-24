from __future__ import annotations

import shlex
import subprocess
import threading
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CardWidget, InfoBar, InfoBarPosition, PushButton

from app_ado.ui.dialogs import show_error_dialog
from ok.gui.widget.Tab import Tab


class McpConfigTab(Tab):
    icon = None
    name = "MCP配置"

    def __init__(self):
        super().__init__()
        self._ado_work_items_mcp_process: subprocess.Popen[str] | None = None
        self._build_ado_work_items_mcp_card()
        self._load_all()

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
        self.btn_copy_ado_work_items_mcp_codex = PushButton("复制Codex配置")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_toggle_ado_work_items_mcp)
        row.addWidget(self.btn_copy_ado_work_items_mcp_command)
        row.addWidget(self.btn_copy_ado_work_items_mcp_codex)
        row.addStretch(1)

        form.addRow("MCP名称", QtWidgets.QLabel("ADO工单MCP"))
        form.addRow("运行状态", self.lbl_ado_work_items_mcp_status)
        form.addRow("启动命令", self.ado_work_items_mcp_command_edit)
        form.addRow(row)

        self.btn_toggle_ado_work_items_mcp.clicked.connect(self._toggle_ado_work_items_mcp)
        self.btn_copy_ado_work_items_mcp_command.clicked.connect(self._copy_ado_work_items_mcp_command)
        self.btn_copy_ado_work_items_mcp_codex.clicked.connect(self._copy_ado_work_items_mcp_codex)

        self.add_card("ADO工单MCP", w)

    def _load_all(self) -> None:
        self.ado_work_items_mcp_command_edit.setText(self._ado_work_items_mcp_launch_command())
        self._update_ado_work_items_mcp_status()

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    def _mcp_python(self) -> str:
        venv_python = self._repo_root() / ".venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        return "python"

    def _ado_work_items_mcp_server_script(self) -> str:
        return str(self._repo_root() / "app_ado" / "mcp_ado_work_items_server.py")

    def _ado_work_items_mcp_launch_command(self) -> str:
        return f"{self._mcp_python()} {shlex.quote(self._ado_work_items_mcp_server_script())}"

    def _copy_text(self, text: str, ok_message: str) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.clipboard().setText(text)
        self._toast("已复制", ok_message)

    def _copy_ado_work_items_mcp_command(self) -> None:
        self._copy_text(self._ado_work_items_mcp_launch_command(), "ADO工单MCP 启动命令已复制")

    def _copy_ado_work_items_mcp_codex(self) -> None:
        text = (
            "[mcp_servers.adoWorkItems]\n"
            f'command = "{self._mcp_python()}"\n'
            f'args = ["{self._ado_work_items_mcp_server_script()}"]\n'
        )
        self._copy_text(text, "ADO工单MCP 的 Codex 配置已复制")

    def _is_ado_work_items_mcp_running(self) -> bool:
        return self._ado_work_items_mcp_process is not None and self._ado_work_items_mcp_process.poll() is None

    def _update_ado_work_items_mcp_status(self) -> None:
        if self._is_ado_work_items_mcp_running():
            self.lbl_ado_work_items_mcp_status.setText("已开启")
            self.btn_toggle_ado_work_items_mcp.setText("关闭 ADO工单MCP")
        else:
            self.lbl_ado_work_items_mcp_status.setText("已关闭")
            self.btn_toggle_ado_work_items_mcp.setText("开启 ADO工单MCP")

    def _toggle_ado_work_items_mcp(self) -> None:
        if self._is_ado_work_items_mcp_running():
            self._stop_ado_work_items_mcp()
        else:
            self._start_ado_work_items_mcp()

    def _start_ado_work_items_mcp(self) -> None:
        result: dict[str, object] = {}

        def run() -> None:
            try:
                cp = subprocess.Popen(
                    [self._mcp_python(), self._ado_work_items_mcp_server_script()],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(self._repo_root()),
                )
                if cp.stdin is None or cp.stdout is None:
                    raise RuntimeError("ADO工单MCP 进程启动失败")
                cp.stdin.write('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"toolbox","version":"1.0"}}}\n')
                cp.stdin.flush()
                line = cp.stdout.readline().strip()
                if not line:
                    cp.terminate()
                    cp.wait(timeout=5)
                    raise RuntimeError("ADO工单MCP 无响应")
                if '"result"' not in line or '"serverInfo"' not in line:
                    cp.terminate()
                    cp.wait(timeout=5)
                    raise RuntimeError("ADO工单MCP 初始化失败")
                result["ok"] = True
                result["process"] = cp
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
                self._ado_work_items_mcp_process = result.get("process")  # type: ignore[assignment]
                self._update_ado_work_items_mcp_status()
                self._toast("ADO工单MCP", "ADO工单MCP 已开启")
            else:
                self._ado_work_items_mcp_process = None
                self._update_ado_work_items_mcp_status()
                show_error_dialog(self, "ADO工单MCP 启动失败", str(result.get("message") or "ADO工单MCP 启动失败"))

        QtCore.QTimer.singleShot(80, finish)

    def _stop_ado_work_items_mcp(self) -> None:
        try:
            if self._ado_work_items_mcp_process is not None and self._ado_work_items_mcp_process.poll() is None:
                self._ado_work_items_mcp_process.terminate()
                self._ado_work_items_mcp_process.wait(timeout=5)
            self._ado_work_items_mcp_process = None
            self._update_ado_work_items_mcp_status()
            self._toast("ADO工单MCP", "ADO工单MCP 已关闭")
        except Exception as e:
            show_error_dialog(self, "ADO工单MCP 关闭失败", str(e))
