from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class NavButton(QtWidgets.QPushButton):
    def __init__(self, text: str, *, icon: QtGui.QIcon | None = None) -> None:
        super().__init__(text)
        if icon is not None:
            self.setIcon(icon)
        self.setCheckable(True)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setMinimumHeight(40)
        self.setObjectName("NavButton")


class TaskRowCard(QtWidgets.QFrame):
    """A single row card in the task list (title + subtitle + start button)."""

    start_clicked = QtCore.Signal()

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("TaskRowCard")

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(4)

        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("TaskTitle")

        self.subtitle = QtWidgets.QLabel(subtitle)
        self.subtitle.setWordWrap(True)
        self.subtitle.setObjectName("TaskSubtitle")

        self.status = QtWidgets.QLabel("idle")
        self.status.setObjectName("TaskStatus")

        left.addWidget(self.title)
        if subtitle:
            left.addWidget(self.subtitle)
        left.addWidget(self.status)

        right = QtWidgets.QHBoxLayout()
        right.setSpacing(10)

        self.start_btn = QtWidgets.QPushButton("开始")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.start_btn.clicked.connect(self.start_clicked.emit)

        right.addWidget(self.start_btn)

        root.addLayout(left, 1)
        root.addLayout(right, 0)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
