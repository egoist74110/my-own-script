from __future__ import annotations

import uuid

from PySide6 import QtCore, QtWidgets
from qfluentwidgets import CheckBox, ComboBox, LineEdit, PushButton

from app_ado.ui.dialogs import show_error_dialog, toast


class AclGroupDialog(QtWidgets.QDialog):
    def __init__(self, parent, *, task_options: list[tuple[str, str]] | None = None, existing: dict | None = None):
        super().__init__(parent)
        self._existing = existing
        self._result: dict | None = None

        self.setWindowTitle("编辑权限组" if existing else "新增权限组")
        self.setModal(True)
        self.resize(560, 360)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        root.addLayout(form)

        self.name = LineEdit(); self.name.setFixedWidth(260)
        self.can_run = CheckBox("允许运行任务")
        self.can_stop = CheckBox("允许停止自己触发的任务")
        self.can_status = CheckBox("允许查询状态")
        self.can_rollback = CheckBox("允许回退版本")

        self.tasks_box = QtWidgets.QListWidget()
        self.tasks_box.setFixedHeight(140)

        form.addRow("组名", self.name)
        perm = QtWidgets.QWidget()
        pv = QtWidgets.QVBoxLayout(perm)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(6)
        pv.addWidget(self.can_run)
        pv.addWidget(self.can_stop)
        pv.addWidget(self.can_status)
        pv.addWidget(self.can_rollback)
        pv.addStretch(1)
        form.addRow("权限", perm)
        form.addRow("允许的任务", self.tasks_box)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Save)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # prefill
        if existing:
            self.name.setText(existing.get("name") or "")
            self.can_run.setChecked(bool(existing.get("can_run")))
            self.can_stop.setChecked(bool(existing.get("can_stop")))
            self.can_status.setChecked(bool(existing.get("can_status", True)))
            self.can_rollback.setChecked(bool(existing.get("can_rollback")))
            allowed = set(existing.get("task_ids") or [])
        else:
            self.can_status.setChecked(True)
            self.can_rollback.setChecked(False)
            allowed = set()

        for tid, label in (task_options or []):
            it = QtWidgets.QListWidgetItem(label)
            it.setData(QtCore.Qt.UserRole, tid)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if tid in allowed else QtCore.Qt.Unchecked)
            self.tasks_box.addItem(it)

    def _row(self, a: QtWidgets.QWidget, b: QtWidgets.QWidget) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(a)
        h.addWidget(b)
        h.addStretch(1)
        return w

    def result_group(self) -> dict | None:
        return self._result

    def accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            show_error_dialog(self, "表单未完整", "组名不能为空")
            return

        task_ids: list[str] = []
        for i in range(self.tasks_box.count()):
            it = self.tasks_box.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                tid = str(it.data(QtCore.Qt.UserRole) or "")
                if tid:
                    task_ids.append(tid)

        if self.can_run.isChecked() and not task_ids:
            show_error_dialog(self, "表单未完整", "允许运行任务时，至少勾选一个任务")
            return

        gid = self._existing.get("id") if self._existing else f"acl_group:{uuid.uuid4()}"
        self._result = {
            "id": gid,
            "name": name,
            "can_run": bool(self.can_run.isChecked()),
            "can_stop": bool(self.can_stop.isChecked()),
            "can_status": bool(self.can_status.isChecked()),
            "can_rollback": bool(self.can_rollback.isChecked()),
            "task_ids": task_ids,
        }
        super().accept()


class AclMemberDialog(QtWidgets.QDialog):
    def __init__(self, parent, *, group_name: str, existing: dict | None = None):
        super().__init__(parent)
        self._existing = existing
        self._result: dict | None = None

        self.setWindowTitle("编辑成员" if existing else f"新增成员（{group_name}）")
        self.setModal(True)
        self.resize(560, 260)

        form = QtWidgets.QFormLayout(self)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.label = LineEdit(); self.label.setFixedWidth(260)
        self.chat_id = LineEdit(); self.chat_id.setFixedWidth(260)
        self.username = LineEdit(); self.username.setFixedWidth(260)
        self.username.setPlaceholderText("可选：@username")

        form.addRow("备注", self.label)
        form.addRow("chat_id", self.chat_id)
        form.addRow("@username", self.username)

        btn_row = QtWidgets.QHBoxLayout()
        btn_cancel = PushButton("取消")
        btn_ok = PushButton("保存")
        btn_ok.setDefault(True)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        form.addRow(btn_row)

        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self.accept)

        if existing:
            self.label.setText(existing.get("label") or "")
            self.chat_id.setText(existing.get("chat_id") or "")
            self.username.setText(existing.get("username") or "")

    def result_member(self) -> dict | None:
        return self._result

    def accept(self) -> None:
        label = self.label.text().strip()
        chat_id = self.chat_id.text().strip()
        username = self.username.text().strip()
        if username and not username.startswith("@"):  # normalize
            username = "@" + username

        if not chat_id and not username:
            show_error_dialog(self, "表单未完整", "chat_id 或 @username 至少填写一个")
            return

        mid = self._existing.get("id") if self._existing else f"acl_member:{uuid.uuid4()}"
        self._result = {
            "id": mid,
            "label": label,
            "chat_id": chat_id,
            "username": username,
        }
        super().accept()
