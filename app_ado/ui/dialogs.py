from __future__ import annotations

import uuid
import json

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QWidget
from qfluentwidgets import LineEdit, PushButton, InfoBar, InfoBarPosition, ComboBox

from app_ado.models import LibraryEntry, ProjectEntry, UiSettings
from app_ado.secrets import get_pat, set_pat
from app_ado.httpx_ado import get_projects


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
    def __init__(self, parent: QWidget, *, settings: UiSettings, existing: ProjectEntry | None = None, library_id: str | None = None):
        super().__init__(parent)
        self._settings = settings
        self._existing = existing
        self._library_id = library_id
        self._result: ProjectEntry | None = None

        self.setWindowTitle("编辑项目" if existing else "新增项目")
        self.setModal(True)
        self.resize(560, 240)

        root = QFormLayout(self)
        root.setLabelAlignment(QtCore.Qt.AlignLeft)
        root.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # library picker
        self.lib_combo = ComboBox(); self.lib_combo.setFixedWidth(260)
        idx = 0
        for i, lib in enumerate(self._settings.libraries):
            self.lib_combo.addItem(lib.name, userData=lib.id)
            if (self._library_id and lib.id == self._library_id) or (existing and lib.id == existing.library_id):
                idx = i
        if self._settings.libraries:
            self.lib_combo.setCurrentIndex(idx)

        # Two modes: manual input OR dropdowns (when discovery is implemented)
        self.collection_input = LineEdit(); self.collection_input.setFixedWidth(260)
        self.project_input = LineEdit(); self.project_input.setFixedWidth(260)

        self.collection_combo = ComboBox(); self.collection_combo.setFixedWidth(260)
        self.project_combo = ComboBox(); self.project_combo.setFixedWidth(260)
        self.collection_combo.setVisible(False)
        self.project_combo.setVisible(False)

        root.addRow("代码库", self.lib_combo)
        root.addRow("Collection", self.collection_input)
        root.addRow("Project", self.project_input)
        root.addRow("Collection(下拉)", self.collection_combo)
        root.addRow("Project(下拉)", self.project_combo)

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
        # Real request (QNAM): GET /{collection}/_apis/projects?api-version=7.0
        lib_id = self.lib_combo.currentData() or self._library_id or self._settings.active_library_id or (
            self._settings.libraries[0].id if self._settings.libraries else None
        )
        if not lib_id:
            show_error_dialog(self, "错误", "请先新增代码库")
            return
        lib = next((x for x in self._settings.libraries if x.id == lib_id), None)
        if not lib:
            show_error_dialog(self, "错误", "找不到代码库配置")
            return
        pat = get_pat(lib.id)
        if not pat:
            show_error_dialog(
                self,
                "错误",
                f"该代码库未保存 PAT：{lib.name}\n\n请在『代码库 → 编辑』里填写 PAT 并保存。",
            )
            return

        c = self.collection_input.text().strip()
        if not c:
            show_error_dialog(self, "错误", "请先填写 Collection（例如 DefaultCollection）")
            return

        base_url = lib.base_url
        collection = c
        self._set_loading(True, f"正在获取 Projects（{c}）...")

        def run() -> None:
            try:
                res = get_projects(base_url, collection, pat=pat, api_version="7.0", timeout_sec=10.0)
                self._http_res = res
            except Exception as e:
                self._http_res = e

        # run in background thread (python threading), then marshal back to UI
        import threading

        self._http_res = None
        th = threading.Thread(target=run, daemon=True)
        th.start()

        def finish() -> None:
            if th.is_alive():
                QtCore.QTimer.singleShot(80, finish)
                return
            self._set_loading(False)
            if isinstance(self._http_res, Exception):
                show_error_dialog(self, "获取 Projects 失败", str(self._http_res))
                return
            res = self._http_res
            assert res is not None

            url = f"{base_url.rstrip('/')}/{collection}/_apis/projects?api-version=7.0"
            if res.status != 200:
                pat_len = len(pat) if pat else 0
                details = (
                    f"代码库: {lib.name}\n"
                    f"library_id: {lib.id}\n"
                    f"PAT_len: {pat_len}\n\n"
                    f"URL: {url}\n状态码: {res.status}\n\nHeaders:\n" + "\n".join(
                        [f"{k}: {v}" for k, v in res.headers.items()]
                    ) + f"\n\nBody(截断):\n{(res.body or '')[:4000]}"
                )
                show_error_dialog(self, "获取 Projects 失败", details)
                return

            try:
                data = json.loads(res.body or "{}")
            except Exception as e:
                show_error_dialog(self, "解析失败", f"JSON解析失败: {e}\n\nBody:\n{(res.body or '')[:4000]}")
                return

            items = [x.get("name") for x in (data.get("value") or []) if x.get("name")]
            self.project_combo.clear()
            for name in items:
                self.project_combo.addItem(str(name), userData=str(name))
            if items:
                self.project_input.setVisible(False)
                self.project_combo.setVisible(True)
                self.project_combo.setCurrentIndex(0)
                self.project_input.setText(str(items[0]))
                toast(self, "成功", f"已获取 Projects: {len(items)}")
            else:
                show_error_dialog(self, "提示", "请求成功，但没有返回任何 Projects")

        QtCore.QTimer.singleShot(80, finish)

    def _finish_stub(self, msg: str) -> None:
        self._set_loading(False)
        show_error_dialog(self, "提示", msg)

    def result_entry(self) -> ProjectEntry | None:
        return self._result

    def _on_ok(self) -> None:
        collection = self.collection_input.text().strip()
        project = (self.project_combo.currentData() if self.project_combo.isVisible() else self.project_input.text().strip())
        project = str(project).strip() if project else ""

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
        lib_id = self.lib_combo.currentData() or self._library_id or self._settings.active_library_id or self._settings.libraries[0].id

        pid = self._existing.id if self._existing else f"proj:{uuid.uuid4()}"
        self._result = ProjectEntry(id=pid, library_id=str(lib_id), collection=collection, project=project)
        self.accept()
