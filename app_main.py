from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, FluentIcon

from app_ado.ui.ado_tab import AdoReleaseTab


def main() -> None:
    app = QApplication(sys.argv)

    w = MSFluentWindow()
    w.setWindowTitle("my-own-script (QFluentWidgets)")

    ado = AdoReleaseTab()
    w.addSubInterface(ado, FluentIcon.APPLICATION, "ADO发布")

    w.resize(1100, 760)
    w.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
