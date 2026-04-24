from __future__ import annotations

import uuid
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CardWidget, ComboBox, InfoBar, InfoBarPosition, PushButton

from app_ado.models import LocalRepoEntry, UiSettings, project_entry_id, project_entry_name
from app_ado.store import load_ui_settings, save_ui_settings
from app_ado.ui.dialogs import LibraryDialog, ProjectDialog, show_error_dialog
from ok.gui.widget.Tab import Tab


class CodeConfigTab(Tab):
    icon = None
    name = "代码配置"

    def __init__(self):
        super().__init__()
        self._settings: UiSettings = load_ui_settings()
        self._build_library_card()
        self._build_project_card()
        self._build_local_repo_card()

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        if ok:
            InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
        else:
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _build_library_card(self) -> None:
        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.lib_combo = ComboBox()
        self.lib_combo.setFixedWidth(260)
        self.btn_new_lib = PushButton("新增")
        self.btn_edit_lib = PushButton("编辑")
        self.btn_del_lib = PushButton("删除")

        self.btn_new_lib.clicked.connect(self._new_library)
        self.btn_edit_lib.clicked.connect(self._edit_library)
        self.btn_del_lib.clicked.connect(self._delete_library)

        form.addRow("代码库", self.lib_combo)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.btn_new_lib)
        btn_row.addWidget(self.btn_edit_lib)
        btn_row.addWidget(self.btn_del_lib)
        form.addRow(btn_row)

        self.add_card("代码库（本地配置）", w)
        self._refresh_lib_combo()

    def _build_project_card(self) -> None:
        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.proj_combo = ComboBox()
        self.proj_combo.setFixedWidth(260)

        self.btn_new_proj = PushButton("新增")
        self.btn_edit_proj = PushButton("编辑")
        self.btn_del_proj = PushButton("删除")

        self.btn_new_proj.clicked.connect(self._new_project)
        self.btn_edit_proj.clicked.connect(self._edit_project)
        self.btn_del_proj.clicked.connect(self._delete_project)

        form.addRow("项目", self.proj_combo)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.btn_new_proj)
        btn_row.addWidget(self.btn_edit_proj)
        btn_row.addWidget(self.btn_del_proj)
        form.addRow(btn_row)

        self.add_card("项目（本地配置）", w)
        self._refresh_proj_combo()

    def _build_local_repo_card(self) -> None:
        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.local_repo_combo = QtWidgets.QComboBox()
        self.local_repo_combo.setFixedWidth(360)
        self.btn_new_local_repo = PushButton("新增")
        self.btn_edit_local_repo = PushButton("编辑")
        self.btn_del_local_repo = PushButton("删除")

        self.btn_new_local_repo.clicked.connect(self._new_local_repo)
        self.btn_edit_local_repo.clicked.connect(self._edit_local_repo)
        self.btn_del_local_repo.clicked.connect(self._delete_local_repo)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.local_repo_combo)
        row.addWidget(self.btn_new_local_repo)
        row.addWidget(self.btn_edit_local_repo)
        row.addWidget(self.btn_del_local_repo)
        row.addStretch(1)
        form.addRow("本地仓库", row)

        self.add_card("本地仓库（仅本地路径）", w)
        self._refresh_local_repo_combo()

    def _refresh_lib_combo(self, *, select_id: str | None = None) -> None:
        self._settings = load_ui_settings()
        active = select_id or self._settings.active_library_id
        self.lib_combo.blockSignals(True)
        self.lib_combo.clear()
        idx = 0
        for i, lib in enumerate(self._settings.libraries):
            self.lib_combo.addItem(lib.name, userData=lib.id)
            if active and lib.id == active:
                idx = i
        if self._settings.libraries:
            self.lib_combo.setCurrentIndex(idx)
        self.lib_combo.blockSignals(False)

    def _active_library(self):
        lid = self.lib_combo.currentData()
        return next((x for x in self._settings.libraries if x.id == lid), None)

    def _new_library(self) -> None:
        dlg = LibraryDialog(self, settings=self._settings)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        entry = dlg.result_entry()
        if not entry:
            return
        self._settings.libraries.append(entry)
        self._settings.active_library_id = entry.id
        save_ui_settings(self._settings)
        self._toast("已新增", f"代码库已创建：{entry.name}")
        self._refresh_lib_combo(select_id=entry.id)

    def _edit_library(self) -> None:
        lib = self._active_library()
        if not lib:
            self._toast("提示", "请先选择代码库", ok=False)
            return
        dlg = LibraryDialog(self, settings=self._settings, existing=lib)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        entry = dlg.result_entry()
        if not entry:
            return
        self._settings.libraries = [entry if x.id == lib.id else x for x in self._settings.libraries]
        self._settings.active_library_id = entry.id
        save_ui_settings(self._settings)
        self._toast("已保存", "代码库配置已保存")
        self._refresh_lib_combo(select_id=entry.id)

    def _delete_library(self) -> None:
        lib = self._active_library()
        if not lib:
            self._toast("提示", "请先选择代码库", ok=False)
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除代码库：{lib.name} ？\n（会同时删除关联项目）")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self._settings.libraries = [x for x in self._settings.libraries if x.id != lib.id]
        self._settings.projects = [p for p in self._settings.projects if p.library_id != lib.id]
        save_ui_settings(self._settings)
        self._toast("已删除", f"代码库已删除：{lib.name}")
        self._refresh_lib_combo()
        self._refresh_proj_combo()

    def _refresh_proj_combo(self, *, select_id: str | None = None) -> None:
        self._settings = load_ui_settings()
        active = select_id or self._settings.active_project_id
        self.proj_combo.blockSignals(True)
        self.proj_combo.clear()
        idx = 0
        for p in self._settings.projects:
            project_id = project_entry_id(p)
            project_name = project_entry_name(p)
            if not project_id or not project_name:
                continue
            i = self.proj_combo.count()
            self.proj_combo.addItem(project_name, userData=project_id)
            if active and project_id == active:
                idx = i
        if self._settings.projects:
            self.proj_combo.setCurrentIndex(idx)
        self.proj_combo.blockSignals(False)

    def _active_project(self):
        pid = self.proj_combo.currentData()
        return next((x for x in self._settings.projects if project_entry_id(x) == pid), None)

    def _new_project(self) -> None:
        if not self._settings.libraries:
            self._toast("错误", "请先新增代码库", ok=False)
            return
        lib = self._active_library()
        if not lib:
            self._toast("错误", "请先选择代码库，再新增项目", ok=False)
            return
        dlg = ProjectDialog(self, settings=self._settings, library_id=lib.id)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        entry = dlg.result_entry()
        if not entry:
            return
        self._settings.projects.append(entry)
        self._settings.active_project_id = entry.id
        save_ui_settings(self._settings)
        self._toast("已新增", f"项目已创建：{entry.project}")
        self._refresh_proj_combo(select_id=entry.id)

    def _edit_project(self) -> None:
        p = self._active_project()
        if not p:
            self._toast("提示", "请先选择项目", ok=False)
            return
        lib = self._active_library()
        if not lib:
            self._toast("错误", "请先选择代码库", ok=False)
            return
        dlg = ProjectDialog(self, settings=self._settings, existing=p, library_id=lib.id)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        entry = dlg.result_entry()
        if not entry:
            return
        self._settings.projects = [entry if x.id == p.id else x for x in self._settings.projects]
        self._settings.active_project_id = entry.id
        save_ui_settings(self._settings)
        self._toast("已保存", "项目配置已保存")
        self._refresh_proj_combo(select_id=entry.id)

    def _delete_project(self) -> None:
        p = self._active_project()
        if not p:
            self._toast("提示", "请先选择项目", ok=False)
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除项目：{p.project} ？")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self._settings.projects = [x for x in self._settings.projects if x.id != p.id]
        save_ui_settings(self._settings)
        self._toast("已删除", f"项目已删除：{p.project}")
        self._refresh_proj_combo()

    def _refresh_local_repo_combo(self, *, select_id: str | None = None) -> None:
        self._settings = load_ui_settings()
        active = select_id or self._settings.work_items_local_repo_id
        self.local_repo_combo.blockSignals(True)
        self.local_repo_combo.clear()
        idx = 0
        for i, repo in enumerate(self._settings.local_repos):
            self.local_repo_combo.addItem(f"{repo.name}  ({repo.path})", userData=repo.id)
            if active and repo.id == active:
                idx = i
        if self._settings.local_repos:
            self.local_repo_combo.setCurrentIndex(idx)
        self.local_repo_combo.blockSignals(False)

    def _new_local_repo(self) -> None:
        repo_path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择本地仓库目录")
        if not repo_path:
            return
        repo_path = str(Path(repo_path).expanduser().resolve())
        if not (Path(repo_path) / ".git").exists():
            show_error_dialog(self, "错误", "选择的目录不是 Git 仓库")
            return

        self._settings = load_ui_settings()
        if any(Path(x.path).expanduser().resolve() == Path(repo_path).resolve() for x in self._settings.local_repos):
            show_error_dialog(self, "错误", "该本地仓库已存在")
            return

        entry = LocalRepoEntry(id=f"repo:{uuid.uuid4()}", name=Path(repo_path).name, path=repo_path)
        self._settings.local_repos.append(entry)
        self._settings.work_items_local_repo_id = entry.id
        save_ui_settings(self._settings)
        self._refresh_local_repo_combo(select_id=entry.id)
        self._toast("已新增", f"本地仓库已创建：{entry.name}")

    def _edit_local_repo(self) -> None:
        repo_id = self.local_repo_combo.currentData()
        if not repo_id:
            self._toast("提示", "请先选择本地仓库", ok=False)
            return
        self._settings = load_ui_settings()
        repo = next((x for x in self._settings.local_repos if x.id == repo_id), None)
        if repo is None:
            return

        repo_path = QtWidgets.QFileDialog.getExistingDirectory(self, "重新选择本地仓库目录", repo.path)
        if not repo_path:
            return
        repo_path = str(Path(repo_path).expanduser().resolve())
        if not (Path(repo_path) / ".git").exists():
            show_error_dialog(self, "错误", "选择的目录不是 Git 仓库")
            return
        if any(x.id != repo.id and Path(x.path).expanduser().resolve() == Path(repo_path).resolve() for x in self._settings.local_repos):
            show_error_dialog(self, "错误", "该本地仓库已存在")
            return

        repo.path = repo_path
        repo.name = Path(repo_path).name
        save_ui_settings(self._settings)
        self._refresh_local_repo_combo(select_id=repo.id)
        self._toast("已保存", f"本地仓库已更新：{repo.name}")

    def _delete_local_repo(self) -> None:
        repo_id = self.local_repo_combo.currentData()
        if not repo_id:
            self._toast("提示", "请先选择本地仓库", ok=False)
            return
        self._settings = load_ui_settings()
        repo = next((x for x in self._settings.local_repos if x.id == repo_id), None)
        if repo is None:
            return
        ok = QtWidgets.QMessageBox.question(self, "确认删除", f"删除本地仓库：{repo.name} ？")
        if ok != QtWidgets.QMessageBox.Yes:
            return
        self._settings.local_repos = [x for x in self._settings.local_repos if x.id != repo_id]
        if self._settings.work_items_local_repo_id == repo_id:
            self._settings.work_items_local_repo_id = self._settings.local_repos[0].id if self._settings.local_repos else ""
        save_ui_settings(self._settings)
        self._refresh_local_repo_combo()
        self._toast("已删除", f"本地仓库已删除：{repo.name}")
