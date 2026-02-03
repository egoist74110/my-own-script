from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class NavButton(QtWidgets.QPushButton):
    def __init__(self, text: str, *, icon: QtGui.QIcon | None = None) -> None:
        super().__init__(text)
        if icon is not None:
            self.setIcon(icon)
        self.setCheckable(True)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setMinimumHeight(36)


class TaskCard(QtWidgets.QFrame):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Raised)
        self.setObjectName("TaskCard")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self.title = QtWidgets.QLabel(title)
        self.title.setStyleSheet("font-weight: 600; font-size: 14px;")

        self.subtitle = QtWidgets.QLabel(subtitle)
        self.subtitle.setStyleSheet("color: #666;")

        self.status = QtWidgets.QLabel("idle")
        self.status.setStyleSheet("color: #1f2937;")

        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        layout.addWidget(self.title)
        if subtitle:
            layout.addWidget(self.subtitle)
        layout.addWidget(self.status)
        layout.addWidget(self.run_btn, alignment=QtCore.Qt.AlignLeft)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
