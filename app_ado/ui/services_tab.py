from __future__ import annotations

import threading

from PySide6 import QtCore, QtGui, QtWidgets
from qfluentwidgets import CardWidget, InfoBar, InfoBarPosition, PushButton

from app_ado import services_panel as svc
from app_ado.ui.dialogs import show_error_dialog
from ok.gui.widget.Tab import Tab


class ServicesTab(Tab):
    """本机服务面板：VPN 地址 / code-server / cloudflared 临时隧道。

    复用 app_ado.services_panel 的后端逻辑，与 Telegram 服务面板共享同一套
    启停/状态/落盘机制（~/.config/my-own-script/services/）。
    """

    icon = None
    name = "服务"

    def __init__(self) -> None:
        super().__init__()
        self._busy = False
        self._build_vpn_card()
        self._build_codeserver_card()
        self._build_cloudflared_card()
        self._build_ccpocket_card()
        self._refresh_all()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh_all)
        self._timer.start()

    # ---------- 通用 ----------

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _copy(self, text: str | None, msg: str) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None or not text:
            self._toast("无可复制内容", "当前没有可复制的值", ok=False)
            return
        app.clipboard().setText(text)
        self._toast("已复制", msg)

    @staticmethod
    def _status_label() -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel("…")
        lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lbl.setWordWrap(True)
        return lbl

    # ---------- VPN ----------

    def _build_vpn_card(self) -> None:
        w = CardWidget(self)
        lay = QtWidgets.QVBoxLayout(w)
        self.lbl_vpn = self._status_label()
        self.btn_vpn_connect = PushButton("🔌 连接")
        self.btn_vpn_refresh = PushButton("刷新")
        self.btn_vpn_copy = PushButton("复制 IP")
        self.btn_vpn_config = PushButton("VPN 配置")
        self.btn_vpn_seed = PushButton("Ente 种子")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_vpn_connect)
        row.addWidget(self.btn_vpn_refresh)
        row.addWidget(self.btn_vpn_copy)
        row.addWidget(self.btn_vpn_config)
        row.addWidget(self.btn_vpn_seed)
        row.addStretch(1)
        lay.addWidget(self.lbl_vpn)
        lay.addLayout(row)
        self.btn_vpn_connect.clicked.connect(self._vpn_connect)
        self.btn_vpn_refresh.clicked.connect(self._refresh_vpn)
        self.btn_vpn_copy.clicked.connect(lambda: self._copy(svc.vpn_ip(), "VPN IP 已复制"))
        self.btn_vpn_config.clicked.connect(self._show_vpn_config)
        self.btn_vpn_seed.clicked.connect(self._vpn_import_seed)
        self.add_card("🌐 VPN", w)

    def _show_vpn_config(self) -> None:
        """编辑并保存 Harmony VPN 登录信息（workspace / 数据驻留区 / 邮箱 / 密码）。

        全部存进系统钥匙串（keyring）；MFA 令牌不在这里存，登录时现取。
        """
        from app_ado.secrets import get_vpn_config, set_vpn_config
        from app_ado.vpn_login import RESIDENCY_OPTIONS

        cfg = get_vpn_config()

        dlg = QtWidgets.QDialog(self.window())
        dlg.setWindowTitle("VPN 配置")
        dlg.setMinimumWidth(360)
        form = QtWidgets.QFormLayout(dlg)

        ed_ws = QtWidgets.QLineEdit(cfg.get("workspace") or "")
        ed_ws.setPlaceholderText("请输入 Workspace 名称")
        cb_res = QtWidgets.QComboBox()
        cb_res.addItems(RESIDENCY_OPTIONS)
        if cfg.get("residency") in RESIDENCY_OPTIONS:
            cb_res.setCurrentText(cfg["residency"])
        ed_email = QtWidgets.QLineEdit(cfg.get("email") or "")
        ed_email.setPlaceholderText("登录邮箱")
        ed_pw = QtWidgets.QLineEdit(cfg.get("password") or "")
        ed_pw.setEchoMode(QtWidgets.QLineEdit.Password)
        ed_pw.setPlaceholderText("登录密码")

        form.addRow("Workspace", ed_ws)
        form.addRow("数据驻留区", cb_res)
        form.addRow("邮箱", ed_email)
        form.addRow("密码", ed_pw)

        tip = QtWidgets.QLabel("令牌(MFA)不在此保存，登录时再输。")
        tip.setStyleSheet("color: gray;")
        form.addRow(tip)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        form.addRow(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        workspace = ed_ws.text().strip()
        email = ed_email.text().strip()
        password = ed_pw.text()
        if not (workspace and email and password):
            self._toast("未保存", "workspace / 邮箱 / 密码都要填", ok=False)
            return
        set_vpn_config(
            workspace=workspace,
            residency=cb_res.currentText(),
            email=email,
            password=password,
        )
        self._toast("已保存", "VPN 登录信息已写入钥匙串")

    def _refresh_vpn(self) -> None:
        ip = svc.vpn_ip()
        self.lbl_vpn.setText(
            f"当前 Harmony VPN IP：{ip}" if ip else "未连接（没找到 10.254.x 地址）"
        )

    def _vpn_import_seed(self) -> None:
        """选 Ente 明文导出文件 → 抽 Harmony 种子存钥匙串 → 读完即删该文件。"""
        from app_ado.vpn_totp import import_from_export

        QtWidgets.QMessageBox.information(
            self.window(), "导入 Ente 种子",
            "请在 Ente Auth 里：设置 → 数据 → 导出验证码（选明文）。\n"
            "选中导出文件后，仅抽取 Harmony 那条种子存入钥匙串，文件随即删除。\n"
            "（该文件含你全部 2FA 种子，记得也清空废纸篓。）",
        )
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window(), "选择 Ente 导出文件（明文 otpauth）", "",
            "文本/JSON (*.txt *.json);;所有文件 (*)",
        )
        if not path:
            return
        r = import_from_export(path)
        if r.get("ok"):
            self._toast("种子已导入", r.get("msg") or "成功；导出文件已删")
        else:
            show_error_dialog(self, "导入失败", r.get("msg") or "未匹配到 Harmony 条目")

    def _vpn_connect(self) -> None:
        """自动登录并连接：自愈阶梯 + 浏览器 SSO（Ente 种子算码）。放线程跑，约 1–2 分钟。"""
        from app_ado.secrets import vpn_config_complete
        from app_ado.vpn_login import playwright_available, playwright_ensure_installed
        from app_ado.vpn_totp import has_secret

        if not vpn_config_complete():
            self._toast("未配置", "请先点「VPN 配置」填 workspace/邮箱/密码", ok=False)
            return
        if not has_secret():
            self._toast("缺少令牌种子", "请先点「Ente 种子」导入，才能自动算 MFA 码", ok=False)
            return
        if not playwright_available():
            ret = QtWidgets.QMessageBox.question(
                self.window(), "需要安装 Playwright",
                "首次自动登录需安装 Playwright（约几十 MB，用系统 Chrome，不下载浏览器）。现在安装？",
            )
            if ret != QtWidgets.QMessageBox.Yes:
                return

        self.btn_vpn_connect.setEnabled(False)
        self.btn_vpn_connect.setText("连接中…")
        self.lbl_vpn.setText("🔄 正在连接 VPN…（自愈/登录，约 1–2 分钟）")
        result: dict[str, object] = {}

        def run() -> None:
            try:
                ok_i, msg_i = playwright_ensure_installed(log=lambda m: None)
                if not ok_i:
                    result["ok"], result["msg"] = False, f"Playwright 安装失败：{msg_i}"
                    return
                from app_ado.vpn_control import ensure_connected, status

                lines: list[str] = []
                ok = ensure_connected(token_provider=lambda: None, log=lambda m: lines.append(m))
                if ok:
                    result["ok"], result["msg"] = True, f"已连上：{status().get('ip')}"
                else:
                    result["ok"], result["msg"] = False, ("\n".join(lines[-5:]) or "未连上")
            except Exception as e:  # noqa: BLE001
                result["ok"], result["msg"] = False, str(e)

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(200, finish)
                return
            self.btn_vpn_connect.setEnabled(True)
            self.btn_vpn_connect.setText("🔌 连接")
            self._refresh_vpn()
            if result.get("ok"):
                self._toast("VPN", str(result.get("msg")))
            else:
                show_error_dialog(self, "VPN 连接失败", str(result.get("msg") or "未知错误"))

        QtCore.QTimer.singleShot(200, finish)

    # ---------- code-server ----------

    def _build_codeserver_card(self) -> None:
        w = CardWidget(self)
        lay = QtWidgets.QVBoxLayout(w)
        self.lbl_cs = self._status_label()
        self.btn_cs_start = PushButton("启动")
        self.btn_cs_stop = PushButton("关闭")
        self.btn_cs_copypw = PushButton("复制密码")
        row = QtWidgets.QHBoxLayout()
        for b in (self.btn_cs_start, self.btn_cs_stop, self.btn_cs_copypw):
            row.addWidget(b)
        row.addStretch(1)
        lay.addWidget(self.lbl_cs)
        lay.addLayout(row)
        self.btn_cs_start.clicked.connect(lambda: self._run_action("code-server 启动", svc.codeserver_start))
        self.btn_cs_stop.clicked.connect(lambda: self._run_action("code-server 关闭", svc.codeserver_stop))
        self.btn_cs_copypw.clicked.connect(lambda: self._copy(svc.codeserver_password(), "code-server 密码已复制"))
        self.add_card("💻 code-server", w)

    # ---------- cloudflared ----------

    def _build_cloudflared_card(self) -> None:
        w = CardWidget(self)
        lay = QtWidgets.QVBoxLayout(w)
        self.lbl_cf = self._status_label()
        self.btn_cf_start = PushButton("启动")
        self.btn_cf_stop = PushButton("关闭")
        self.btn_cf_copy = PushButton("复制域名")
        row = QtWidgets.QHBoxLayout()
        for b in (self.btn_cf_start, self.btn_cf_stop, self.btn_cf_copy):
            row.addWidget(b)
        row.addStretch(1)
        lay.addWidget(self.lbl_cf)
        lay.addLayout(row)
        self.btn_cf_start.clicked.connect(lambda: self._run_action("cloudflared 启动", svc.cloudflared_start))
        self.btn_cf_stop.clicked.connect(lambda: self._run_action("cloudflared 关闭", svc.cloudflared_stop))
        self.btn_cf_copy.clicked.connect(lambda: self._copy(svc.cloudflared_domain(), "cloudflared 域名已复制"))
        self.add_card("☁️ cloudflared 临时隧道", w)

    # ---------- CC Pocket ----------

    def _build_ccpocket_card(self) -> None:
        w = CardWidget(self)
        lay = QtWidgets.QVBoxLayout(w)
        self.lbl_cp = self._status_label()
        self.btn_cp_start = PushButton("启动")
        self.btn_cp_stop = PushButton("关闭")
        self.btn_cp_qr = PushButton("获取二维码")
        row = QtWidgets.QHBoxLayout()
        for b in (self.btn_cp_start, self.btn_cp_stop, self.btn_cp_qr):
            row.addWidget(b)
        row.addStretch(1)
        lay.addWidget(self.lbl_cp)
        lay.addLayout(row)
        self.btn_cp_start.clicked.connect(lambda: self._run_action("CC Pocket 启动", svc.ccpocket_start))
        self.btn_cp_stop.clicked.connect(lambda: self._run_action("CC Pocket 关闭", svc.ccpocket_stop))
        self.btn_cp_qr.clicked.connect(self._show_ccpocket_qr)
        self.add_card("📱 CC Pocket", w)

    def _show_ccpocket_qr(self) -> None:
        png = svc.ccpocket_qr_png(scale=10, border=3)
        if not png:
            self._toast("没有二维码", "请先启动 CC Pocket", ok=False)
            return
        deeplink = svc.ccpocket_deeplink() or ""
        pix = QtGui.QPixmap()
        if not pix.loadFromData(png, "PNG"):
            self._toast("二维码渲染失败", "无法加载图片", ok=False)
            return

        dlg = QtWidgets.QDialog(self.window())
        dlg.setWindowTitle("CC Pocket 连接二维码")
        v = QtWidgets.QVBoxLayout(dlg)
        img = QtWidgets.QLabel()
        img.setPixmap(pix)
        img.setAlignment(QtCore.Qt.AlignCenter)
        tip = QtWidgets.QLabel("用 ccpocket app 扫码连接")
        tip.setAlignment(QtCore.Qt.AlignCenter)
        link = QtWidgets.QLabel(deeplink)
        link.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        link.setWordWrap(True)
        btn_copy = PushButton("复制链接")
        btn_copy.clicked.connect(lambda: self._copy(deeplink, "CC Pocket 链接已复制"))
        v.addWidget(img)
        v.addWidget(tip)
        v.addWidget(link)
        v.addWidget(btn_copy)
        dlg.exec()

    # ---------- 刷新 ----------

    def _refresh_all(self) -> None:
        self._refresh_vpn()
        self.lbl_cs.setText(svc.codeserver_status())
        self.lbl_cf.setText(svc.cloudflared_status())
        self.lbl_cp.setText(svc.ccpocket_status())

    # ---------- 启停（放到线程，避免阻塞 UI；cloudflared 启动会等十几秒抓域名）----------

    def _action_buttons(self) -> list[PushButton]:
        return [
            self.btn_cs_start, self.btn_cs_stop,
            self.btn_cf_start, self.btn_cf_stop,
            self.btn_cp_start, self.btn_cp_stop,
        ]

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for b in self._action_buttons():
            b.setEnabled(not busy)

    def _run_action(self, title: str, fn) -> None:
        if self._busy:
            return
        self._set_busy(True)
        result: dict[str, object] = {}

        def run() -> None:
            try:
                ok, msg = fn()
                result["ok"], result["msg"] = ok, msg
            except Exception as e:  # noqa: BLE001
                result["ok"], result["msg"] = False, str(e)

        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(120, finish)
                return
            self._set_busy(False)
            self._refresh_all()
            ok = bool(result.get("ok"))
            msg = str(result.get("msg") or "")
            if ok:
                self._toast(title, msg or "完成")
            else:
                show_error_dialog(self, f"{title} 失败", msg or "未知错误")

        QtCore.QTimer.singleShot(120, finish)
