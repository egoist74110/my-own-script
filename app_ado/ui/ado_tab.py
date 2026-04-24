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
        """Manual update UX: check updates + update now."""
        from app_version import __version__
        from app_ado.release_updater import get_latest_release
        from app_ado.app_installer import default_update_cache_dir, download_file, find_app_in_volume, install_app_from_volume, mount_dmg, unmount_dmg

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
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.btn_check_update)
        btn_row.addWidget(self.btn_do_update)
        btn_row.addWidget(self.btn_reinstall)
        form.addRow(btn_row)
        form.addRow("进度", self.progress)

        def ui(fn) -> None:
            # Ensure UI updates always happen on the Qt main thread.
            QtCore.QTimer.singleShot(0, self, fn)

        def set_busy(busy: bool) -> None:
            self.btn_check_update.setEnabled(not busy)
            if busy:
                self.btn_do_update.setEnabled(False)
                self.btn_reinstall.setEnabled(False)
            else:
                has_rel = bool(self._latest_release_asset_url or self._latest_release_url)
                self.btn_do_update.setEnabled(has_rel and self.lbl_update_status.text().startswith("发现新版本"))
                self.btn_reinstall.setEnabled(has_rel)

        self._latest_release_url: str | None = None
        self._latest_release_asset_url: str | None = None
        self._latest_release_version: str | None = None
        self.btn_do_update.setEnabled(False)
        self.btn_reinstall.setEnabled(False)

        def do_check(done: dict, *, auto: bool = False) -> None:
            try:
                rel = get_latest_release()
                self._latest_release_url = rel.html_url
                self._latest_release_asset_url = rel.asset_url
                self._latest_release_version = rel.version

                if rel.version == __version__:
                    ui(lambda: self.lbl_update_status.setText("已是最新"))
                    ui(lambda: self.btn_do_update.setEnabled(False))
                else:
                    new_ver = rel.version
                    ui(lambda: self.lbl_update_status.setText(f"发现新版本：{new_ver}"))
                    ui(lambda: self.btn_do_update.setEnabled(True))

                    if auto:
                        # Auto prompt only once per app launch.
                        def _prompt(v=new_ver):
                            ok = QtWidgets.QMessageBox.question(
                                self,
                                "发现新版本",
                                f"发现新版本：{v}\n\n是否现在更新？",
                            )
                            if ok == QtWidgets.QMessageBox.Yes:
                                _start_update(force=False)

                        ui(_prompt)
            except Exception as e:
                msg = str(e)
                ui(lambda m=msg: show_error_dialog(self, "无法检查更新", m))
                ui(lambda: self.lbl_update_status.setText("检查失败"))
                ui(lambda: self.btn_do_update.setEnabled(False))
            finally:
                done["v"] = True
                ui(lambda: set_busy(False))

        def on_check_clicked(*, auto: bool = False) -> None:
            set_busy(True)
            self.lbl_update_status.setText("检查中…")

            # watchdog
            done = {"v": False}

            def watchdog():
                if done["v"]:
                    return
                set_busy(False)
                show_error_dialog(self, "检查更新超时", "检查更新超过 12 秒仍未返回。\n\n建议：稍后再试或检查网络。")

            QtCore.QTimer.singleShot(12000, self, watchdog)

            import threading

            threading.Thread(target=lambda: do_check(done, auto=auto), daemon=True).start()

        def do_update(done: dict, *, force: bool = False) -> None:
            mp = None
            try:
                url = self._latest_release_asset_url
                ver = self._latest_release_version
                if not url or not ver:
                    raise RuntimeError("请先点击【检查更新】")

                dmg_path = default_update_cache_dir() / f"代码工具箱-{ver}-mac.dmg"

                ui(lambda: self.progress.setVisible(True))
                ui(lambda: self.progress.setRange(0, 100))
                ui(lambda: self.progress.setValue(0))
                ui(lambda: self.lbl_update_status.setText("下载更新中…"))

                def on_prog(p):
                    if p.total and p.total > 0:
                        pct = int(p.downloaded * 100 / p.total)
                        ui(lambda v=pct: self.progress.setValue(max(0, min(100, v))))

                download_file(url, dmg_path, on_progress=on_prog, timeout=30.0)

                ui(lambda: self.progress.setRange(0, 0))
                ui(lambda: self.lbl_update_status.setText("挂载安装包…"))
                mp = mount_dmg(dmg_path)
                src_app = find_app_in_volume(mp)

                ui(lambda: self.lbl_update_status.setText("安装中…（可能会弹出系统授权）"))
                install_app_from_volume(src_app)

                ui(lambda: self.lbl_update_status.setText("安装完成，正在退出旧版本…"))

                # Ensure the old instance really exits even if Qt event delivery is flaky.
                import threading
                import os

                def _hard_exit():
                    os._exit(0)

                threading.Timer(1.2, _hard_exit).start()

                def _soft_exit():
                    try:
                        from PySide6.QtWidgets import QApplication

                        inst = QApplication.instance()
                        if inst is not None:
                            inst.quit()
                    except Exception:
                        pass

                ui(_soft_exit)
            except Exception as e:
                msg = str(e)
                ui(
                    lambda m=msg: show_error_dialog(
                        self,
                        "更新失败",
                        m
                        + "\n\n你可以：\n1) 打开 GitHub Releases 手动下载并安装\n2) 或点击【重新安装】重试\n",
                    )
                )
                if self._latest_release_url:
                    ui(lambda: open_url(self._latest_release_url))
            finally:
                if mp is not None:
                    try:
                        unmount_dmg(mp)
                    except Exception:
                        pass
                done["v"] = True
                ui(lambda: self.progress.setVisible(False))
                ui(lambda: set_busy(False))

        def _start_update(*, force: bool) -> None:
            set_busy(True)
            self.lbl_update_status.setText("更新中…")

            done = {"v": False}

            def watchdog():
                if done["v"]:
                    return
                set_busy(False)
                show_error_dialog(self, "更新超时", "更新超过 10 分钟仍未完成。\n\n常见原因：网络慢/DMG 挂载失败/安装需要授权。")

            QtCore.QTimer.singleShot(600000, self, watchdog)

            import threading

            threading.Thread(target=lambda: do_update(done, force=force), daemon=True).start()

        def on_update_clicked() -> None:
            if not self._latest_release_asset_url:
                self._toast("提示", "请先点击【检查更新】", ok=False)
                return

            ok = QtWidgets.QMessageBox.question(
                self,
                "确认更新",
                "发现新版本，是否现在下载并安装？\n\n（将覆盖 /Applications/代码工具箱.app，并可能弹出系统授权）",
            )
            if ok != QtWidgets.QMessageBox.Yes:
                return

            _start_update(force=False)

        def on_reinstall_clicked() -> None:
            if not self._latest_release_asset_url:
                self._toast("提示", "请先点击【检查更新】", ok=False)
                return

            ok = QtWidgets.QMessageBox.question(
                self,
                "确认重新安装",
                "将重新下载并覆盖安装当前最新版本。\n\n确认继续？",
            )
            if ok != QtWidgets.QMessageBox.Yes:
                return

            _start_update(force=True)

        self.btn_check_update.clicked.connect(lambda: on_check_clicked(auto=False))
        self.btn_do_update.clicked.connect(on_update_clicked)
        self.btn_reinstall.clicked.connect(on_reinstall_clicked)

        self.add_card("更新", w)

        # Auto check once when entering this page.
        def _auto_check_once():
            if getattr(self, "_update_auto_checked", False):
                return
            self._update_auto_checked = True
            on_check_clicked(auto=True)

        QtCore.QTimer.singleShot(300, self, _auto_check_once)
