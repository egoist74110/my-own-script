from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets


@dataclass(frozen=True)
class RollbackChoice:
    offset: int  # 1..N, where 1 means "previous" (index 1)


class RollbackDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        *,
        task_label: str,
        max_offset: int,
        preview_lines: dict[int, list[str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("回退")
        self.resize(720, 420)

        self._choice: RollbackChoice | None = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QtWidgets.QLabel(f"选择回退版本（{task_label}）")
        title.setStyleSheet("font-weight:600;")
        root.addWidget(title)

        hint = QtWidgets.QLabel(
            "说明：将对该任务配置的所有发布目标逐个执行回退。\n"
            "回退版本是相对最新 Release 的偏移：1=上一个，2=上上个..."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        root.addWidget(hint)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("回退到："))
        self.combo = QtWidgets.QComboBox(self)
        for k in range(1, max_offset + 1):
            self.combo.addItem(f"前 {k} 个（offset={k}）", userData=k)
        row.addWidget(self.combo)
        row.addStretch(1)
        root.addLayout(row)

        self.preview = QtWidgets.QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("预览")
        root.addWidget(self.preview, 1)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        def refresh_preview() -> None:
            k = int(self.combo.currentData() or 1)
            lines = preview_lines.get(k) or []
            self.preview.setPlainText("\n".join(lines) if lines else "(无预览)")

        self.combo.currentIndexChanged.connect(refresh_preview)
        refresh_preview()

    def result_choice(self) -> RollbackChoice | None:
        return self._choice

    def accept(self) -> None:
        k = int(self.combo.currentData() or 1)
        self._choice = RollbackChoice(offset=k)
        super().accept()
