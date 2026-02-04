from __future__ import annotations

from PySide6 import QtCore
from PySide6.QtWidgets import QWidget, QFormLayout
from qfluentwidgets import CardWidget, ComboBox, PushButton

from ok.gui.widget.Tab import Tab


class TasksTab(Tab):
    """Task page placeholder.

    Next step: implement FlowTask config + execution:
    - repo/branches dropdown discovery
    - merge/push
    - build trigger + monitor
    - release trigger + monitor (multi-stage)
    - logs
    """

    icon = None
    name = "任务"

    def __init__(self):
        super().__init__()

        w = CardWidget(self)
        form = QFormLayout(w)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.task_combo = ComboBox(); self.task_combo.setFixedWidth(260)
        self.task_combo.addItem("同步/合并 + 构建 + 发布", userData="sync_merge_build_release")

        self.btn_edit = PushButton("配置")
        self.btn_run = PushButton("运行")

        form.addRow("任务", self.task_combo)
        form.addRow(self.btn_edit, self.btn_run)

        self.add_card("任务", w)
