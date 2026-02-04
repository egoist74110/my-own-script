from __future__ import annotations

import httpx
from PySide6 import QtCore, QtGui, QtWidgets

from ui_app.azuredevops_ops import list_collections
from ui_app.library_store import normalize_base_url, set_pat
from ui_app.settings_store import LibraryEntry


class VerifyWorker(QtCore.QObject):
    ok = QtCore.Signal(list)
    failed = QtCore.Signal(str)

    def __init__(self, base_url: str, pat: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.pat = pat

    @QtCore.Slot()
    def run(self) -> None:
        try:
            cols = list_collections(self.base_url, self.pat)
            self.ok.emit(cols)
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:400]
            self.failed.emit(f"HTTP {e.response.status_code}: {body}")
        except Exception as e:
            self.failed.emit(str(e))


class LibraryDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, *, existing: LibraryEntry | None = None, new_id: str | None = None) -> None:
        super().__init__(parent)
        self._existing = existing
        self._new_id = new_id
        self._result: LibraryEntry | None = None

        self.setWindowTitle("编辑代码库" if existing else "新增代码库")
        self.setModal(True)
        self.resize(640, 360)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("例如：公司 ADO")

        self.url = QtWidgets.QLineEdit()
        self.url.setPlaceholderText("例如：https://azuredevops.cg1alias.com")

        self.pat = QtWidgets.QLineEdit()
        self.pat.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pat.setPlaceholderText("PAT（留空=不修改）")

        form.addRow("名称", self.name)
        form.addRow("URL", self.url)
        form.addRow("PAT", self.pat)
        root.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        self.verify_btn = QtWidgets.QPushButton("验证(尝试列Collections)")
        self.verify_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.verify_btn.clicked.connect(self._verify)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("Muted")
        row.addWidget(self.verify_btn)
        row.addWidget(self.status, 1)
        root.addLayout(row)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._thread: QtCore.QThread | None = None

        if existing:
            self.name.setText(existing.name)
            self.url.setText(existing.base_url)

    def result_entry(self) -> LibraryEntry | None:
        return self._result

    def _cleanup(self) -> None:
        if self._thread is not None:
            try:
                self._thread.quit()
                self._thread.wait(800)
            except Exception:
                pass
            self._thread = None

    def _verify(self) -> None:
        base_url = normalize_base_url(self.url.text())
        pat = self.pat.text().strip()
        if not base_url:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 URL")
            return
        if not pat:
            QtWidgets.QMessageBox.warning(self, "错误", "请输入 PAT 才能验证")
            return

        self.status.setText("验证中...")
        self.verify_btn.setEnabled(False)
        self._cleanup()

        worker = VerifyWorker(base_url, pat)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ok.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.ok.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def ok(cols: list) -> None:
            if cols:
                self.status.setText(f"验证成功：发现 {len(cols)} 个 Collections（服务器可能允许列出）")
            else:
                self.status.setText("验证成功，但未发现 Collections")
            self.verify_btn.setEnabled(True)

        def fail(msg: str) -> None:
            self.status.setText(f"验证失败：{msg}")
            self.verify_btn.setEnabled(True)

        worker.ok.connect(ok)
        worker.failed.connect(fail)

        self._thread = thread
        thread.start()

    def accept(self) -> None:
        name = self.name.text().strip()
        base_url = normalize_base_url(self.url.text())
        pat = self.pat.text().strip()

        if not name:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写名称")
            return
        if not base_url:
            QtWidgets.QMessageBox.warning(self, "错误", "请填写 URL")
            return

        lid = self._existing.id if self._existing else (self._new_id or "lib:new")
        entry = LibraryEntry(
            id=lid,
            provider="azuredevops",
            name=name,
            base_url=base_url,
        )

        # Save token only if provided
        if pat:
            # set_pat needs the final id; we temporarily set for new, then caller will replace
            set_pat(lid, pat)
            self.pat.setText("")

        self._result = entry
        super().accept()
