from __future__ import annotations

import uuid

from PySide6 import QtCore
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QWidget
from qfluentwidgets import LineEdit, PushButton, InfoBar, InfoBarPosition

from app_ado.models import LibraryEntry, ProjectEntry, UiSettings
from app_ado.secrets import set_pat


def toast(parent: QWidget, title: str, content: str, ok: bool = True) -> None:
    if ok:
        InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=parent)
    else:
        InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=parent)


class LibraryDialog(QDialog):
    def __init__(self, parent: QWidget, *, settings: UiSettings, existing: LibraryEntry | None = None):
        super().__init__(parent)
        self._settings = settings
        self._existing = existing
        self._result: LibraryEntry | None = None

        self.setWindowTitle("编辑代码库" if existing else "新增代码库")
        self.setModal(True)
        self.resize(560, 260)

        root = QFormLayout(self)
        root.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.name = LineEdit()
        self.url = LineEdit()
        self.pat = LineEdit()
        self.pat.setEchoMode(LineEdit.Password)
        self.pat.setPlaceholderText("PAT（可选；保存后写入钥匙串）")

        root.addRow("名称", self.name)
        root.addRow("URL", self.url)
        root.addRow("PAT", self.pat)

        btn_row = QHBoxLayout()
        self.btn_cancel = PushButton("取消")
        self.btn_ok = PushButton("保存")
        self.btn_ok.setDefault(True)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        root.addRow(btn_row)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._on_ok)

        if existing:
            self.name.setText(existing.name)
            self.url.setText(existing.base_url)

    def result_entry(self) -> LibraryEntry | None:
        return self._result

    def _on_ok(self) -> None:
        name = self.name.text().strip()
        url = self.url.text().strip().rstrip("/")
        pat = self.pat.text().strip()

        if not name:
            toast(self, "错误", "名称不能为空", ok=False)
            return
        if not url:
            toast(self, "错误", "URL 不能为空", ok=False)
            return

        # unique name
        for x in self._settings.libraries:
            if self._existing and x.id == self._existing.id:
                continue
            if x.name == name:
                toast(self, "错误", f"名称重复：{name}", ok=False)
                return

        lid = self._existing.id if self._existing else f"lib:{uuid.uuid4()}"
        self._result = LibraryEntry(id=lid, name=name, base_url=url)

        if pat:
            set_pat(lid, pat)
            self.pat.setText("")

        self.accept()


class ProjectDialog(QDialog):
    def __init__(self, parent: QWidget, *, settings: UiSettings, existing: ProjectEntry | None = None):
        super().__init__(parent)
        self._settings = settings
        self._existing = existing
        self._result: ProjectEntry | None = None

        self.setWindowTitle("编辑项目" if existing else "新增项目")
        self.setModal(True)
        self.resize(560, 240)

        root = QFormLayout(self)
        root.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.collection = LineEdit()
        self.project = LineEdit()

        root.addRow("Collection", self.collection)
        root.addRow("Project", self.project)

        btn_row = QHBoxLayout()
        self.btn_cancel = PushButton("取消")
        self.btn_ok = PushButton("保存")
        self.btn_ok.setDefault(True)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        root.addRow(btn_row)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._on_ok)

        if existing:
            self.collection.setText(existing.collection)
            self.project.setText(existing.project)

    def result_entry(self) -> ProjectEntry | None:
        return self._result

    def _on_ok(self) -> None:
        collection = self.collection.text().strip()
        project = self.project.text().strip()

        if not collection:
            toast(self, "错误", "Collection 不能为空", ok=False)
            return
        if not project:
            toast(self, "错误", "Project 不能为空", ok=False)
            return

        # name unique among projects (can adjust later to include collection)
        for x in self._settings.projects:
            if self._existing and x.id == self._existing.id:
                continue
            if x.project == project:
                toast(self, "错误", f"项目名称重复：{project}", ok=False)
                return

        if not self._settings.libraries:
            toast(self, "错误", "请先新增代码库", ok=False)
            return
        lib_id = self._settings.active_library_id or self._settings.libraries[0].id

        pid = self._existing.id if self._existing else f"proj:{uuid.uuid4()}"
        self._result = ProjectEntry(id=pid, library_id=lib_id, collection=collection, project=project)
        self.accept()
