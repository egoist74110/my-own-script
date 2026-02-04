from __future__ import annotations

import uuid

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QWidget
from qfluentwidgets import LineEdit, PushButton, InfoBar, InfoBarPosition, ComboBox

from app_ado.models import LibraryEntry, ProjectEntry, UiSettings
from app_ado.secrets import set_pat


def toast(parent: QWidget, title: str, content: str, ok: bool = True) -> None:
    if ok:
        InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=parent)
    else:
        InfoBar.error(title, content, position=InfoBarPosition.TOP_RIGHT, parent=parent)


def show_error_dialog(parent: QWidget, title: str, details: str) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.resize(720, 420)

    root = QtWidgets.QVBoxLayout(dlg)
    root.setContentsMargins(16, 16, 16, 16)
    root.setSpacing(12)

    box = QtWidgets.QPlainTextEdit()
    box.setReadOnly(True)
    box.setPlainText(details)
    root.addWidget(box, 1)

    btn = PushButton("确认")
    btn.clicked.connect(dlg.accept)
    row = QtWidgets.QHBoxLayout()
    row.addStretch(1)
    row.addWidget(btn)
    root.addLayout(row)

    dlg.exec()


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
        root.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.name = LineEdit(); self.name.setFixedWidth(260)
        self.url = LineEdit(); self.url.setFixedWidth(260)
        self.pat = LineEdit(); self.pat.setFixedWidth(260)
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
        root.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Two modes: manual input OR dropdowns (when discovery is implemented)
        self.collection_input = LineEdit(); self.collection_input.setFixedWidth(260)
        self.project_input = LineEdit(); self.project_input.setFixedWidth(260)

        self.collection_combo = ComboBox(); self.collection_combo.setFixedWidth(260)
        self.project_combo = ComboBox(); self.project_combo.setFixedWidth(260)
        self.collection_combo.setVisible(False)
        self.project_combo.setVisible(False)

        root.addRow("Collection", self.collection_input)
        root.addRow("Project", self.project_input)

        self.btn_fetch_collections = PushButton("获取Collections")
        self.btn_try_default = PushButton("尝试DefaultCollection")
        self.btn_fetch_projects = PushButton("获取Projects")

        self.btn_fetch_collections.clicked.connect(self._fetch_collections)
        self.btn_try_default.clicked.connect(lambda: self._use_collection("DefaultCollection"))
        self.btn_fetch_projects.clicked.connect(self._fetch_projects)

        btns = QHBoxLayout()
        btns.addWidget(self.btn_fetch_collections)
        btns.addWidget(self.btn_try_default)
        btns.addWidget(self.btn_fetch_projects)
        root.addRow(btns)

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
            self.collection_input.setText(existing.collection)
            self.project_input.setText(existing.project)

    def _set_loading(self, on: bool, text: str = "") -> None:
        for b in (self.btn_fetch_collections, self.btn_try_default, self.btn_fetch_projects, self.btn_ok):
            b.setEnabled(not on)
        if on and text:
            toast(self, "加载中", text, ok=True)

    def _use_collection(self, c: str) -> None:
        self.collection_input.setText(c)

    def _fetch_collections(self) -> None:
        # Stub for now: show informative error dialog
        self._set_loading(True, "正在获取 Collections ...")
        QtCore.QTimer.singleShot(200, lambda: self._finish_stub("获取 Collections 尚未接入网络层（后续用 QNetworkAccessManager 封装）。"))

    def _fetch_projects(self) -> None:
        c = self.collection_input.text().strip()
        if not c:
            show_error_dialog(self, "错误", "请先填写 Collection（例如 DefaultCollection）")
            return
        self._set_loading(True, f"正在获取 Projects（{c}）...")
        QtCore.QTimer.singleShot(200, lambda: self._finish_stub("获取 Projects 尚未接入网络层（后续用 QNetworkAccessManager 封装）。"))

    def _finish_stub(self, msg: str) -> None:
        self._set_loading(False)
        show_error_dialog(self, "提示", msg)

    def result_entry(self) -> ProjectEntry | None:
        return self._result

    def _on_ok(self) -> None:
        collection = self.collection_input.text().strip()
        project = self.project_input.text().strip()

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
