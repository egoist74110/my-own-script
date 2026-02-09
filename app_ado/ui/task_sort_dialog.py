from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app_ado.models import DynamicTaskConfig
from app_ado.ui.dialogs import show_error_dialog


class TaskSortDialog(QtWidgets.QDialog):
    """Sort tasks by editing numeric order.

    This is intentionally simple+explicit (no drag-drop requirement).
    """

    def __init__(self, parent: QtWidgets.QWidget, tasks: list[DynamicTaskConfig]):
        super().__init__(parent)
        self.setWindowTitle("任务排序")
        self.resize(640, 420)

        self._tasks = list(tasks)
        self._order: dict[str, int] = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        hint = QtWidgets.QLabel("为每个任务设置一个顺序值（越小越靠前）。建议使用 10、20、30... 方便后续插入。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        root.addWidget(hint)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["顺序", "命令", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 160)

        root.addWidget(self.table, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_auto = QtWidgets.QPushButton("按当前列表顺序自动编号", self)
        self.btn_auto.clicked.connect(self._auto_number)
        btn_row.addWidget(self.btn_auto)
        btn_row.addStretch(1)

        self.btn_cancel = QtWidgets.QPushButton("取消", self)
        self.btn_ok = QtWidgets.QPushButton("保存", self)
        self.btn_ok.setDefault(True)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)

        root.addLayout(btn_row)

        self._populate()

    def _populate(self) -> None:
        tasks = list(self._tasks)
        tasks.sort(key=lambda t: (int(getattr(t, "sort_order", 0) or 0), (t.tg_command or "").lower()))

        self.table.setRowCount(len(tasks))
        for r, t in enumerate(tasks):
            order = int(getattr(t, "sort_order", 0) or 0)

            sp = QtWidgets.QSpinBox(self.table)
            sp.setRange(0, 999999)
            sp.setValue(order)
            sp.valueChanged.connect(lambda v, tid=str(t.id): self._order.__setitem__(tid, int(v)))
            self._order[str(t.id)] = order

            self.table.setCellWidget(r, 0, sp)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("/" + (t.tg_command or "")))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem((t.tg_desc or "").strip()))

    def _auto_number(self) -> None:
        # Use visible row order, assign 10,20,30...
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 0)
            if isinstance(w, QtWidgets.QSpinBox):
                w.setValue((r + 1) * 10)

    def result_order(self) -> dict[str, int]:
        return dict(self._order)

    def accept(self) -> None:
        # validate: duplicates allowed but warn if all zeros
        try:
            vals = list(self._order.values())
            if vals and all(int(x) == 0 for x in vals):
                show_error_dialog(self, "错误", "顺序不能全部为 0")
                return
        except Exception:
            pass
        super().accept()
