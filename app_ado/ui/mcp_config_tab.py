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
from app_lark.lark_mcp_flow import (
    lark_mcp_claude_cli_command,
    lark_mcp_codex_toml,
    lark_mcp_gemini_json_fragment,
    lark_mcp_launch_command,
)
from app_lark.mcp_server_manager import (
    LOGIN_CANCELLED_SENTINEL,
    cancel_lark_login,
    is_lark_login_running,
    is_lark_logged_in,
    is_lark_mcp_running,
    lark_logout,
    start_lark_login,
    start_lark_mcp,
    stop_lark_mcp,
)
from app_lark.node_bootstrap import (
    NODE_VERSION,
    bootstrap_node,
    find_npx,
)
from app_lark.secrets import get_app_secret, set_app_secret
from app_lark.store import (
    DEFAULT_DOMAIN,
    DEFAULT_OAUTH_PORT,
    load_lark_settings,
    oauth_redirect_url,
    save_lark_settings,
)


LARK_HELP_HTML_TEMPLATE = """
<h3>Lark MCP 配置说明</h3>

<p><b>一、开发者后台</b>(配 App + 权限 + 回调):<br>
<a href="https://open.larksuite.com/app">https://open.larksuite.com/app</a></p>
<ol>
  <li>选你的自建应用 → <b>凭证与基础信息</b> → 拿到 <b>App ID</b> 和 <b>App Secret</b>,填到本卡片上面对应的输入框并 <b>保存配置</b></li>
  <li><b>权限管理</b> → 添加下列权限点(scope),然后 <b>创建版本 → 申请发布</b>:
    <ul>
      <li><code>offline_access</code></li>
      <li><code>docx:document</code></li>
      <li><code>wiki:wiki</code></li>
    </ul>
  </li>
  <li><b>安全设置 → 重定向 URL</b> → 添加:<br>
    <code>{redirect_url}</code><br>
    (端口和卡片上的"OAuth 回调端口"保持一致)
  </li>
</ol>

<p><b>二、管理后台</b>(应用授权,<i>易漏</i>):<br>
<a href="https://www.larksuite.com/admin">https://www.larksuite.com/admin</a></p>
<p>工作台 → 应用管理 → 自建应用 / 已安装应用 → 搜索 <b>你的应用</b> → 配置 → 应用可用范围 → <b>添加你自己</b></p>

<p><b>三、回到本程序</b></p>
<ol>
  <li>填好 App ID / App Secret → 点 <b>保存配置</b></li>
  <li>点 <b>登录</b> → 浏览器完成 OAuth 授权</li>
  <li>点 <b>开启 Lark MCP</b></li>
</ol>
"""
from ok.gui.widget.Tab import Tab


class McpConfigTab(Tab):
    icon = None
    name = "MCP配置"

    def __init__(self):
        super().__init__()
        self._build_ado_work_items_mcp_card()
        self._build_lark_mcp_card()
        self._load_all()
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._update_all_status)
        self._status_timer.start()

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    # ---------------- ADO 工单 MCP 卡 ----------------

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

    # ---------------- Lark MCP 卡 ----------------

    def _build_lark_mcp_card(self) -> None:
        w = CardWidget(self)
        form = QtWidgets.QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.lark_app_id_edit = QtWidgets.QLineEdit()
        self.lark_app_id_edit.setPlaceholderText("在 open.larksuite.com 创建自建应用后获取")

        self.lark_app_secret_edit = QtWidgets.QLineEdit()
        self.lark_app_secret_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.lark_app_secret_edit.setPlaceholderText("应用密钥,保存到系统钥匙串(不写入磁盘明文)")

        self.lark_domain_combo = QtWidgets.QComboBox()
        self.lark_domain_combo.addItem("国际版 Lark(open.larksuite.com)", "https://open.larksuite.com")
        self.lark_domain_combo.addItem("国内版 飞书(open.feishu.cn)", "https://open.feishu.cn")

        self.lark_oauth_port_edit = QtWidgets.QSpinBox()
        self.lark_oauth_port_edit.setRange(1024, 65535)
        self.lark_oauth_port_edit.setValue(DEFAULT_OAUTH_PORT)

        self.lbl_lark_mcp_status = QtWidgets.QLabel("已关闭")
        self.lbl_lark_login_status = QtWidgets.QLabel("未登录")

        self.btn_lark_help = PushButton("配置说明")
        self.btn_save_lark = PushButton("保存配置")
        self.btn_lark_auth = PushButton("登录")
        self.btn_toggle_lark_mcp = PushButton("开启 Lark MCP")
        self.btn_copy_lark_mcp_command = PushButton("复制启动命令")
        self.btn_copy_lark_mcp_claude = PushButton("复制Claude Code配置")
        self.btn_copy_lark_mcp_codex = PushButton("复制Codex配置")
        self.btn_copy_lark_mcp_gemini = PushButton("复制Gemini CLI配置")

        row1 = QtWidgets.QHBoxLayout()
        row1.addWidget(self.btn_lark_help)
        row1.addWidget(self.btn_save_lark)
        row1.addWidget(self.btn_lark_auth)
        row1.addWidget(self.btn_toggle_lark_mcp)
        row1.addStretch(1)

        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(self.btn_copy_lark_mcp_command)
        row2.addWidget(self.btn_copy_lark_mcp_claude)
        row2.addWidget(self.btn_copy_lark_mcp_codex)
        row2.addWidget(self.btn_copy_lark_mcp_gemini)
        row2.addStretch(1)

        form.addRow("MCP 名称", QtWidgets.QLabel("Lark MCP"))
        form.addRow("运行状态", self.lbl_lark_mcp_status)
        form.addRow("登录状态", self.lbl_lark_login_status)
        form.addRow("应用 ID(App ID)", self.lark_app_id_edit)
        form.addRow("应用密钥(App Secret)", self.lark_app_secret_edit)
        form.addRow("服务地区", self.lark_domain_combo)
        form.addRow("OAuth 回调端口", self.lark_oauth_port_edit)
        form.addRow(row1)
        form.addRow(row2)

        self.btn_lark_help.clicked.connect(self._show_lark_help)
        self.btn_save_lark.clicked.connect(self._save_lark)
        self.btn_lark_auth.clicked.connect(self._toggle_lark_auth)
        self.btn_toggle_lark_mcp.clicked.connect(self._toggle_lark_mcp)
        self.btn_copy_lark_mcp_command.clicked.connect(self._copy_lark_mcp_command)
        self.btn_copy_lark_mcp_claude.clicked.connect(self._copy_lark_mcp_claude)
        self.btn_copy_lark_mcp_codex.clicked.connect(self._copy_lark_mcp_codex)
        self.btn_copy_lark_mcp_gemini.clicked.connect(self._copy_lark_mcp_gemini)

        self.add_card("Lark MCP", w)

    def _show_lark_help(self) -> None:
        s = load_lark_settings()
        redirect_url = oauth_redirect_url(int(s.oauth_port or DEFAULT_OAUTH_PORT))
        html = LARK_HELP_HTML_TEMPLATE.format(redirect_url=redirect_url)

        dlg = QtWidgets.QDialog(self.window())
        dlg.setWindowTitle("Lark MCP 配置说明")
        dlg.resize(640, 560)
        layout = QtWidgets.QVBoxLayout(dlg)
        browser = QtWidgets.QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        layout.addWidget(browser)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
        dlg.exec()

    # ---------------- 公共 ----------------

    def _load_all(self) -> None:
        self.ado_work_items_mcp_command_edit.setText(ado_work_items_mcp_launch_command())
        self._load_lark_form()
        self._update_all_status()

    def _load_lark_form(self) -> None:
        s = load_lark_settings()
        self.lark_app_id_edit.setText(s.app_id or "")
        idx = self.lark_domain_combo.findData(s.domain or DEFAULT_DOMAIN)
        self.lark_domain_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.lark_oauth_port_edit.setValue(int(s.oauth_port or DEFAULT_OAUTH_PORT))
        existing_secret = get_app_secret(s.app_id) if s.app_id else None
        self.lark_app_secret_edit.setPlaceholderText(
            "已保存到系统钥匙串(留空保持不变)" if existing_secret else "应用密钥,保存到系统钥匙串(不写入磁盘明文)"
        )
        self.lark_app_secret_edit.clear()

    def _repo_root(self) -> Path:
        return tool_workspace_root()

    def _copy_text(self, text: str, ok_message: str) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.clipboard().setText(text)
        self._toast("已复制", ok_message)

    def _update_all_status(self) -> None:
        self._update_ado_work_items_mcp_status()
        self._update_lark_mcp_status()
        self._update_lark_login_status()

    # ---------------- ADO 卡 handlers ----------------

    def _copy_ado_work_items_mcp_command(self) -> None:
        self._copy_text(ado_work_items_mcp_launch_command(), "ADO工单MCP 启动命令已复制")

    def _copy_ado_work_items_mcp_claude(self) -> None:
        self._copy_text(
            ado_work_items_mcp_claude_cli_command(),
            "Claude Code 接入命令已复制,粘贴到终端执行后重启 Claude Code 生效",
        )

    def _copy_ado_work_items_mcp_codex(self) -> None:
        self._copy_text(ado_work_items_mcp_codex_toml(), "ADO工单MCP 的 Codex 配置已复制")

    def _copy_ado_work_items_mcp_gemini(self) -> None:
        self._copy_text(
            ado_work_items_mcp_gemini_json_fragment(),
            "Gemini CLI 配置片段已复制,合并到 ~/.gemini/settings.json 的 mcpServers 段",
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

    # ---------------- Lark 卡 handlers ----------------

    def _save_lark(self) -> None:
        app_id = self.lark_app_id_edit.text().strip()
        if not app_id:
            show_error_dialog(self, "Lark MCP", "应用 ID(App ID)不能为空")
            return

        s = load_lark_settings()
        s.app_id = app_id
        s.domain = (self.lark_domain_combo.currentData() or DEFAULT_DOMAIN)
        s.oauth_port = int(self.lark_oauth_port_edit.value())
        save_lark_settings(s)

        new_secret = self.lark_app_secret_edit.text().strip()
        if new_secret:
            set_app_secret(app_id, new_secret)
            self.lark_app_secret_edit.clear()

        self._load_lark_form()
        self._toast("Lark MCP", "配置已保存")

    def _toggle_lark_auth(self) -> None:
        """三态分发:未登录 → 开始登录;登录中 → 取消登录;已登录 → 登出。"""
        if is_lark_login_running():
            ok, msg = cancel_lark_login()
            self._update_lark_login_status()
            if not ok:
                show_error_dialog(self, "Lark MCP", msg)
            return
        if is_lark_logged_in():
            self._do_logout_lark()
            return
        self._begin_lark_login()

    def _begin_lark_login(self) -> None:
        # 先把当前 UI 上的改动落盘,避免用户改了端口/scope 没保存就登录
        if self.lark_app_id_edit.text().strip():
            try:
                self._save_lark_silent()
            except Exception:
                pass

        self._update_lark_login_status()

        result: dict[str, object] = {}

        def run() -> None:
            ok, msg = start_lark_login()
            result["ok"] = ok
            result["message"] = msg

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(200, finish)
                return
            self._update_lark_login_status()
            if bool(result.get("ok")):
                self._toast("Lark MCP", "登录成功,可开启 MCP")
                return
            msg = str(result.get("message") or "未知错误")
            if msg == LOGIN_CANCELLED_SENTINEL:
                self._toast("Lark MCP", "已取消登录", ok=False)
                return
            show_error_dialog(self, "Lark MCP 登录失败", msg)

        QtCore.QTimer.singleShot(200, finish)

    def _do_logout_lark(self) -> None:
        ok, msg = lark_logout()
        self._update_lark_login_status()
        if ok:
            self._toast("Lark MCP", msg)
        else:
            show_error_dialog(self, "Lark MCP 登出失败", msg)

    def _save_lark_silent(self) -> None:
        s = load_lark_settings()
        app_id = self.lark_app_id_edit.text().strip()
        if not app_id:
            return
        s.app_id = app_id
        s.domain = (self.lark_domain_combo.currentData() or DEFAULT_DOMAIN)
        s.oauth_port = int(self.lark_oauth_port_edit.value())
        save_lark_settings(s)
        new_secret = self.lark_app_secret_edit.text().strip()
        if new_secret:
            set_app_secret(app_id, new_secret)
            self.lark_app_secret_edit.clear()

    def _update_lark_login_status(self) -> None:
        if is_lark_login_running():
            self.lbl_lark_login_status.setText("登录中…浏览器应已弹出")
            self.btn_lark_auth.setText("取消登录")
        elif is_lark_logged_in():
            self.lbl_lark_login_status.setText("已登录")
            self.btn_lark_auth.setText("登出")
        else:
            self.lbl_lark_login_status.setText("未登录")
            self.btn_lark_auth.setText("登录")

    def _copy_lark_mcp_command(self) -> None:
        self._copy_text(lark_mcp_launch_command(), "Lark MCP 启动命令已复制")

    def _copy_lark_mcp_claude(self) -> None:
        self._copy_text(
            lark_mcp_claude_cli_command(),
            "Claude Code 接入命令已复制,粘贴到终端执行后重启 Claude Code 生效",
        )

    def _copy_lark_mcp_codex(self) -> None:
        self._copy_text(lark_mcp_codex_toml(), "Lark MCP 的 Codex 配置已复制")

    def _copy_lark_mcp_gemini(self) -> None:
        self._copy_text(
            lark_mcp_gemini_json_fragment(),
            "Gemini CLI 配置片段已复制,合并到 ~/.gemini/settings.json 的 mcpServers 段",
        )

    def _update_lark_mcp_status(self) -> None:
        if is_lark_mcp_running():
            self.lbl_lark_mcp_status.setText("已开启")
            self.btn_toggle_lark_mcp.setText("关闭 Lark MCP")
        else:
            self.lbl_lark_mcp_status.setText("已关闭")
            self.btn_toggle_lark_mcp.setText("开启 Lark MCP")

    def _toggle_lark_mcp(self) -> None:
        if is_lark_mcp_running():
            self._stop_lark_mcp()
        else:
            self._start_lark_mcp()

    def _start_lark_mcp(self) -> None:
        if not is_lark_logged_in():
            show_error_dialog(
                self,
                "Lark MCP 未登录",
                "搜索 / 深度文档读取需要 user_access_token。请先点击 \"登录\" 完成 OAuth 授权,再开启 MCP。",
            )
            return

        # Node 不在就先弹「安装 / 取消」；安装完了再继续开 MCP
        if find_npx() is None:
            self._prompt_install_node_then(self._actually_start_lark_mcp)
            return
        self._actually_start_lark_mcp()

    def _actually_start_lark_mcp(self) -> None:
        result: dict[str, object] = {}

        def run() -> None:
            ok, msg = start_lark_mcp()
            result["ok"] = ok
            result["message"] = msg

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            self._update_lark_mcp_status()
            if bool(result.get("ok")):
                self._toast("Lark MCP", "Lark MCP 已开启")
            else:
                show_error_dialog(self, "Lark MCP 启动失败", str(result.get("message") or "未知错误"))

        QtCore.QTimer.singleShot(80, finish)

    def _stop_lark_mcp(self) -> None:
        ok, msg = stop_lark_mcp()
        self._update_lark_mcp_status()
        if ok:
            self._toast("Lark MCP", "Lark MCP 已关闭")
        else:
            show_error_dialog(self, "Lark MCP 关闭失败", msg)

    # ---------------- 内置 Node 下载（开启 Lark MCP 缺 Node 时触发） ----------------

    def _prompt_install_node_then(self, on_success) -> None:
        """弹「安装 / 取消」。安装成功后回调 ``on_success``；取消或失败就什么也不做。"""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle("Lark MCP 需要 Node 运行时")
        box.setText(
            f"Lark MCP 依赖 Node.js {NODE_VERSION}（约 30MB），当前没检测到。\n"
            "下载到本地缓存，不动你的系统。"
        )
        btn_install = box.addButton("安装", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(btn_install)
        box.exec()
        if box.clickedButton() is not btn_install:
            return
        self._run_node_bootstrap(on_success)

    def _run_node_bootstrap(self, on_success) -> None:
        dlg = QtWidgets.QProgressDialog(
            f"正在下载 Node.js {NODE_VERSION} …",
            "取消",
            0, 100,
            self,
        )
        dlg.setWindowTitle("下载内置 Node 运行时")
        dlg.setWindowModality(QtCore.Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoReset(False)
        dlg.setAutoClose(False)
        dlg.setValue(0)

        cancel_flag = threading.Event()

        def on_cancel() -> None:
            cancel_flag.set()

        dlg.canceled.connect(on_cancel)

        # 跨线程：worker 报进度 → 主线程刷 UI
        progress_sig = _BootstrapSignals()

        def on_progress(done: int, total: int, phase: str) -> None:
            progress_sig.tick.emit(done, total, phase)

        def on_done(ok: bool, message: str) -> None:
            dlg.close()
            if ok:
                self._toast("Lark MCP", message)
                # 自动接力：装好就接着开 MCP
                if on_success is not None:
                    on_success()
            else:
                if "用户取消" in message:
                    self._toast("Lark MCP", "已取消下载", ok=False)
                else:
                    show_error_dialog(self, "下载 Node 失败", message)

        def tick(done: int, total: int, phase: str) -> None:
            if phase == "downloading":
                if total > 0:
                    pct = int(done * 100 / total)
                    dlg.setValue(pct)
                    dlg.setLabelText(
                        f"正在下载 Node.js {NODE_VERSION} … {_human_mb(done)} / {_human_mb(total)}"
                    )
                else:
                    dlg.setLabelText(f"正在下载 Node.js {NODE_VERSION} … {_human_mb(done)}")
            elif phase == "extracting":
                dlg.setLabelText("正在解压 …")
                dlg.setValue(99)
            elif phase == "done":
                dlg.setValue(100)
                dlg.setLabelText("完成")

        progress_sig.tick.connect(tick)
        progress_sig.done.connect(on_done)

        def worker() -> None:
            ok, msg = bootstrap_node(progress=on_progress, cancel_flag=cancel_flag)
            progress_sig.done.emit(ok, msg)

        threading.Thread(target=worker, daemon=True).start()


def _human_mb(n: int) -> str:
    if n <= 0:
        return "?"
    return f"{n / (1024 * 1024):.1f} MB"


class _BootstrapSignals(QtCore.QObject):
    """跨线程信号：worker 线程不能直接动 UI，必须经 signal 跳回主线程。"""
    tick = QtCore.Signal(int, int, str)
    done = QtCore.Signal(bool, str)
