from __future__ import annotations

import threading

from PySide6 import QtCore, QtWidgets
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
        self.btn_vpn_refresh = PushButton("刷新")
        self.btn_vpn_copy = PushButton("复制 IP")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_vpn_refresh)
        row.addWidget(self.btn_vpn_copy)
        row.addStretch(1)
        lay.addWidget(self.lbl_vpn)
        lay.addLayout(row)
        self.btn_vpn_refresh.clicked.connect(self._refresh_vpn)
        self.btn_vpn_copy.clicked.connect(lambda: self._copy(svc.vpn_ip(), "VPN IP 已复制"))
        self.add_card("🌐 VPN 地址", w)

    def _refresh_vpn(self) -> None:
        ip = svc.vpn_ip()
        self.lbl_vpn.setText(
            f"当前 Harmony VPN IP：{ip}" if ip else "未连接（没找到 10.254.x 地址）"
        )

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

    # ---------- 刷新 ----------

    def _refresh_all(self) -> None:
        self._refresh_vpn()
        self.lbl_cs.setText(svc.codeserver_status())
        self.lbl_cf.setText(svc.cloudflared_status())

    # ---------- 启停（放到线程，避免阻塞 UI；cloudflared 启动会等十几秒抓域名）----------

    def _action_buttons(self) -> list[PushButton]:
        return [self.btn_cs_start, self.btn_cs_stop, self.btn_cf_start, self.btn_cf_stop]

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
