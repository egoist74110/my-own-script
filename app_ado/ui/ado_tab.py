from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, InfoBar, InfoBarPosition, PushButton

from app_ado.ui.dialogs import show_error_dialog
from ok.gui.widget.Tab import Tab


class AdoReleaseTab(Tab):
    icon = None
    name = "设置"

    def __init__(self):
        super().__init__()
        self._update_auto_checked = False
        self._build_update_card()

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _build_update_card(self) -> None:
        """Update UX over the git channel: check / update (pull) / reinstall (reset)."""
        from app_version import __version__
        from app_ado.updater import (
            check_git_clean,
            get_remote_version,
            get_update_status,
            hard_reset_to_remote,
            pip_sync,
            pull_ff_only,
            repo_root,
            restart_self,
        )

        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.lbl_version = QtWidgets.QLabel(__version__)
        self.lbl_update_status = QtWidgets.QLabel("未检查")

        self.btn_check_update = PushButton("检查更新")
        self.btn_do_update = PushButton("更新")
        self.btn_reinstall = PushButton("重新安装")

        form.addRow("当前版本", self.lbl_version)
        form.addRow("更新状态", self.lbl_update_status)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)  # busy/indeterminate while working
        self.progress.setVisible(False)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.btn_check_update)
        btn_row.addWidget(self.btn_do_update)
        btn_row.addWidget(self.btn_reinstall)
        form.addRow(btn_row)
        form.addRow("进度", self.progress)

        # Remote version discovered by the last check; None until checked.
        self._remote_version: str | None = None
        self._has_update: bool = False
        self.btn_do_update.setEnabled(False)

        def ui(fn) -> None:
            # Ensure UI updates always happen on the Qt main thread.
            QtCore.QTimer.singleShot(0, self, fn)

        def set_busy(busy: bool) -> None:
            self.btn_check_update.setEnabled(not busy)
            self.btn_reinstall.setEnabled(not busy)
            # 【更新】only makes sense when a newer version was found.
            self.btn_do_update.setEnabled((not busy) and self._has_update)

        # ---- 检查更新 ---------------------------------------------------
        def do_check(done: dict) -> None:
            try:
                root = repo_root()
                st = get_update_status(root, branch="main")  # fetches refs internally
                if st.behind <= 0:
                    self._has_update = False
                    self._remote_version = None
                    ui(lambda: self.lbl_update_status.setText("已是最新"))
                else:
                    try:
                        new_ver = get_remote_version(root, branch="main")
                    except Exception:
                        new_ver = f"{st.behind} 个新提交"
                    self._remote_version = new_ver
                    self._has_update = True
                    ui(lambda v=new_ver: self.lbl_update_status.setText(f"发现新版本：{v}"))
            except Exception as e:
                self._has_update = False
                msg = str(e)
                ui(lambda m=msg: show_error_dialog(self, "无法检查更新", m))
                ui(lambda: self.lbl_update_status.setText("检查失败"))
            finally:
                done["v"] = True
                ui(lambda: set_busy(False))

        def on_check_clicked() -> None:
            set_busy(True)
            self.lbl_update_status.setText("检查中…")

            done = {"v": False}

            def watchdog():
                if done["v"]:
                    return
                set_busy(False)
                show_error_dialog(self, "检查更新超时", "检查更新超过 30 秒仍未返回。\n\n建议：稍后再试或检查网络。")

            QtCore.QTimer.singleShot(30000, self, watchdog)

            import threading

            threading.Thread(target=lambda: do_check(done), daemon=True).start()

        # ---- 更新 / 重新安装（共用 git 执行体）--------------------------
        def do_apply(done: dict, *, reinstall: bool) -> None:
            try:
                root = repo_root()
                if reinstall:
                    ui(lambda: self.lbl_update_status.setText("强制对齐 origin/main…"))
                    hard_reset_to_remote(root, branch="main")
                else:
                    ui(lambda: self.lbl_update_status.setText("拉取更新中…"))
                    pull_ff_only(root, branch="main")

                ui(lambda: self.lbl_update_status.setText("同步依赖中…"))
                pip_sync(root)

                ui(lambda: self.lbl_update_status.setText("完成，正在重启…"))
                ui(lambda: QtCore.QTimer.singleShot(400, self, restart_self))
            except Exception as e:
                msg = str(e)
                ui(
                    lambda m=msg: show_error_dialog(
                        self,
                        "重新安装失败" if reinstall else "更新失败",
                        m + "\n\n提示：若本地有未提交改动，git pull/reset 可能失败；可先提交或清理工作区。",
                    )
                )
                ui(lambda: self.lbl_update_status.setText("更新失败"))
            finally:
                done["v"] = True
                ui(lambda: self.progress.setVisible(False))
                ui(lambda: set_busy(False))

        def _start_apply(*, reinstall: bool) -> None:
            set_busy(True)
            self.progress.setVisible(True)
            self.lbl_update_status.setText("更新中…")

            done = {"v": False}

            def watchdog():
                if done["v"]:
                    return
                set_busy(False)
                self.progress.setVisible(False)
                show_error_dialog(self, "更新超时", "更新超过 10 分钟仍未完成。\n\n常见原因：网络慢 / pip 安装卡住。")

            QtCore.QTimer.singleShot(600000, self, watchdog)

            import threading

            threading.Thread(target=lambda: do_apply(done, reinstall=reinstall), daemon=True).start()

        def on_update_clicked() -> None:
            if not self._has_update:
                self._toast("提示", "请先点击【检查更新】", ok=False)
                return

            ok = QtWidgets.QMessageBox.question(
                self,
                "确认更新",
                f"发现新版本：{self._remote_version}\n\n是否现在拉取并重启？\n（git pull --ff-only origin/main + 同步依赖）",
            )
            if ok != QtWidgets.QMessageBox.Yes:
                return

            _start_apply(reinstall=False)

        def on_reinstall_clicked() -> None:
            ok = QtWidgets.QMessageBox.question(
                self,
                "确认重新安装",
                "将强制把本地工作区对齐到 origin/main 并重启。\n\n"
                "⚠️ 本地未提交/未推送的改动会被丢弃（git reset --hard）。\n\n确认继续？",
            )
            if ok != QtWidgets.QMessageBox.Yes:
                return

            _start_apply(reinstall=True)

        self.btn_check_update.clicked.connect(on_check_clicked)
        self.btn_do_update.clicked.connect(on_update_clicked)
        self.btn_reinstall.clicked.connect(on_reinstall_clicked)

        self.add_card("更新", w)

        # Auto check once when entering this page — display only, never prompts
        # (the startup check in app_main is the single place that asks to update).
        def _auto_check_once():
            if getattr(self, "_update_auto_checked", False):
                return
            self._update_auto_checked = True
            on_check_clicked()

        QtCore.QTimer.singleShot(300, self, _auto_check_once)
