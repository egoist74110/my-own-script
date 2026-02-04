from __future__ import annotations

import uuid

from PySide6 import QtCore
from PySide6.QtWidgets import QWidget, QFormLayout
from qfluentwidgets import LineEdit, ComboBox, PushButton, InfoBar, InfoBarPosition, CardWidget

from app_ado.models import LibraryEntry, ProjectEntry, UiSettings
from app_ado.secrets import set_pat
from app_ado.store import load_ui_settings, save_ui_settings
from ok.gui.widget.Tab import Tab


class AdoReleaseTab(Tab):
    """Minimal bootstrap tab: local settings + PAT save.

    Network/ADO discovery intentionally omitted for stability.
    """

    icon = None
    name = "ADO 发布工具"

    def __init__(self):
        super().__init__()
        self._settings: UiSettings = load_ui_settings()

        self._build_library_card()
        self._build_project_card()

    def _toast(self, title: str, content: str, ok: bool = True) -> None:
        InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window()) if ok else \
            InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _build_library_card(self) -> None:
        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.lib_combo = ComboBox()
        self.lib_name = LineEdit()
        self.lib_url = LineEdit()
        self.lib_pat = LineEdit()
        self.lib_pat.setEchoMode(LineEdit.Password)

        self.btn_new_lib = PushButton("新增")
        self.btn_save_lib = PushButton("保存配置")
        self.btn_del_lib = PushButton("删除")
        self.btn_save_pat = PushButton("保存PAT(写入钥匙串)")

        self.btn_new_lib.clicked.connect(self._new_library)
        self.btn_save_lib.clicked.connect(self._save_library)
        self.btn_del_lib.clicked.connect(self._delete_library)
        self.btn_save_pat.clicked.connect(self._save_pat)
        self.lib_combo.currentIndexChanged.connect(self._load_selected_library)

        form.addRow("代码库", self.lib_combo)
        form.addRow("名称", self.lib_name)
        form.addRow("URL", self.lib_url)
        form.addRow("PAT", self.lib_pat)
        form.addRow(self.btn_new_lib, self.btn_save_lib)
        form.addRow(self.btn_del_lib, self.btn_save_pat)

        self.add_card("代码库（本地配置）", w)
        self._refresh_lib_combo()

    def _build_project_card(self) -> None:
        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.proj_combo = ComboBox()
        self.proj_collection = LineEdit()
        self.proj_project = LineEdit()

        self.btn_new_proj = PushButton("新增")
        self.btn_save_proj = PushButton("保存配置")
        self.btn_del_proj = PushButton("删除")

        self.btn_new_proj.clicked.connect(self._new_project)
        self.btn_save_proj.clicked.connect(self._save_project)
        self.btn_del_proj.clicked.connect(self._delete_project)
        self.proj_combo.currentIndexChanged.connect(self._load_selected_project)

        form.addRow("项目", self.proj_combo)
        form.addRow("Collection", self.proj_collection)
        form.addRow("Project", self.proj_project)
        form.addRow(self.btn_new_proj, self.btn_save_proj)
        form.addRow(self.btn_del_proj)

        self.add_card("项目（本地配置）", w)
        self._refresh_proj_combo()

    # --- libraries ---
    def _refresh_lib_combo(self) -> None:
        self.lib_combo.blockSignals(True)
        self.lib_combo.clear()
        for lib in self._settings.libraries:
            self.lib_combo.addItem(lib.name, userData=lib.id)
        if self._settings.libraries:
            self.lib_combo.setCurrentIndex(0)
        self.lib_combo.blockSignals(False)
        self._load_selected_library()

    def _load_selected_library(self) -> None:
        lid = self.lib_combo.currentData()
        lib = next((x for x in self._settings.libraries if x.id == lid), None)
        if not lib:
            return
        self.lib_name.setText(lib.name)
        self.lib_url.setText(lib.base_url)

    def _new_library(self) -> None:
        lib = LibraryEntry(id=f"lib:{uuid.uuid4()}", name="manka", base_url="https://azuredevops.cg1alias.com")
        self._settings.libraries.append(lib)
        save_ui_settings(self._settings)
        self._toast("已新增", "代码库已创建（请保存PAT）")
        self._refresh_lib_combo()

    def _save_library(self) -> None:
        lid = self.lib_combo.currentData()
        lib = next((x for x in self._settings.libraries if x.id == lid), None)
        if not lib:
            return
        name = self.lib_name.text().strip()
        url = self.lib_url.text().strip().rstrip("/")
        if not name:
            self._toast("错误", "代码库名称不能为空", ok=False)
            return
        if not url:
            self._toast("错误", "代码库 URL 不能为空", ok=False)
            return
        # name unique
        for x in self._settings.libraries:
            if x.id != lib.id and x.name == name:
                self._toast("错误", f"代码库名称重复：{name}", ok=False)
                return

        lib.name = name
        lib.base_url = url
        save_ui_settings(self._settings)
        self._toast("已保存", "代码库配置已保存")
        self._refresh_lib_combo()

    def _delete_library(self) -> None:
        lid = self.lib_combo.currentData()
        lib = next((x for x in self._settings.libraries if x.id == lid), None)
        if not lib:
            return
        self._settings.libraries = [x for x in self._settings.libraries if x.id != lib.id]
        # remove linked projects too
        self._settings.projects = [p for p in self._settings.projects if p.library_id != lib.id]
        save_ui_settings(self._settings)
        self._toast("已删除", f"代码库已删除：{lib.name}")
        self._refresh_lib_combo()
        self._refresh_proj_combo()

    def _save_pat(self) -> None:
        lid = self.lib_combo.currentData()
        if not lid:
            self._toast("错误", "请选择代码库", ok=False)
            return
        pat = self.lib_pat.text().strip()
        if not pat:
            self._toast("错误", "请输入PAT", ok=False)
            return
        set_pat(str(lid), pat)
        self.lib_pat.setText("")
        self._toast("已保存", "PAT 已写入钥匙串（Keychain）")

    # --- projects ---
    def _refresh_proj_combo(self) -> None:
        self.proj_combo.blockSignals(True)
        self.proj_combo.clear()
        for p in self._settings.projects:
            self.proj_combo.addItem(p.project, userData=p.id)
        if self._settings.projects:
            self.proj_combo.setCurrentIndex(0)
        self.proj_combo.blockSignals(False)
        self._load_selected_project()

    def _load_selected_project(self) -> None:
        pid = self.proj_combo.currentData()
        p = next((x for x in self._settings.projects if x.id == pid), None)
        if not p:
            return
        self.proj_collection.setText(p.collection)
        self.proj_project.setText(p.project)

    def _new_project(self) -> None:
        if not self._settings.libraries:
            self._toast("错误", "请先新增代码库", ok=False)
            return
        lib_id = self._settings.libraries[0].id
        p = ProjectEntry(id=f"proj:{uuid.uuid4()}", library_id=lib_id, collection="DefaultCollection", project="CG")
        self._settings.projects.append(p)
        save_ui_settings(self._settings)
        self._toast("已新增", "项目已创建")
        self._refresh_proj_combo()

    def _save_project(self) -> None:
        pid = self.proj_combo.currentData()
        p = next((x for x in self._settings.projects if x.id == pid), None)
        if not p:
            return
        collection = self.proj_collection.text().strip()
        project = self.proj_project.text().strip()
        if not collection:
            self._toast("错误", "Collection 不能为空", ok=False)
            return
        if not project:
            self._toast("错误", "Project 不能为空", ok=False)
            return
        # project name unique within all projects
        for x in self._settings.projects:
            if x.id != p.id and x.project == project:
                self._toast("错误", f"项目名称重复：{project}", ok=False)
                return

        p.collection = collection
        p.project = project
        save_ui_settings(self._settings)
        self._toast("已保存", "项目配置已保存")
        self._refresh_proj_combo()

    def _delete_project(self) -> None:
        pid = self.proj_combo.currentData()
        p = next((x for x in self._settings.projects if x.id == pid), None)
        if not p:
            return
        self._settings.projects = [x for x in self._settings.projects if x.id != p.id]
        save_ui_settings(self._settings)
        self._toast("已删除", f"项目已删除：{p.project}")
        self._refresh_proj_combo()
