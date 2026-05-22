"""真终端控件：自绘 pyte 屏幕网格 + 回滚滚动，直接捕获键盘按字节注入 PTY。

设计：
- 通过 provider(start, count) -> (total, cursor, rows) 按需取片渲染：只构建可视窗口那几十行，
  历史回滚再多也不卡。total 含历史行数，据此设置右侧滚动条。
- paintEvent 逐格绘制可视片（前景/背景色、加粗、下划线、反显、块状光标）。
- keyPressEvent 把 Qt 按键翻译成终端字节交给会话写进 PTY；Shift+PgUp/PgDn/Home/End 用于滚动
  查看历史（不发给 PTY），敲普通键则自动跳回底部。
- 滚轮滚动；新输出时若停在底部则自动贴底，滚上去看历史则保持不动。
- 鼠标框选 + 复制（mac: Cmd+C；其它: Ctrl+Shift+C），复制按选区行号从 provider 重新取，
  跨出可视区也能复制；粘贴走 paste_text（外部用 bracketed-paste 包裹）。

注意 macOS 上 Qt 默认把 Control 和 Command 互换：物理 Ctrl → MetaModifier，
物理 Cmd → ControlModifier。终端的 Ctrl+C（SIGINT）必须对应物理 Ctrl，所以这里区分平台。
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
IS_MAC = sys.platform == "darwin"

# 物理 Ctrl 键对应的 modifier（mac 上被 Qt 换成 Meta）
_CTRL_MOD = Qt.KeyboardModifier.MetaModifier if IS_MAC else Qt.KeyboardModifier.ControlModifier

# provider(start, count) -> (total, cursor=(x,y,hidden), rows)
Provider = Callable[[int, int], tuple]


# ---- 颜色映射：pyte 的颜色字符串 → QColor ----
_NAMED = {
    "black": "#2e3436", "red": "#cc0000", "green": "#4e9a06", "brown": "#c4a000",
    "yellow": "#c4a000", "blue": "#3465a4", "magenta": "#75507b", "cyan": "#06989a",
    "white": "#d3d7cf",
    "brightblack": "#555753", "brightred": "#ef2929", "brightgreen": "#8ae234",
    "brightbrown": "#fce94f", "brightyellow": "#fce94f", "brightblue": "#729fcf",
    "brightmagenta": "#ad7fa8", "brightcyan": "#34e2e2", "brightwhite": "#eeeeec",
}
_BRIGHTEN = {
    "black": "brightblack", "red": "brightred", "green": "brightgreen",
    "brown": "brightbrown", "yellow": "brightyellow", "blue": "brightblue",
    "magenta": "brightmagenta", "cyan": "brightcyan", "white": "brightwhite",
}
_HEXSET = set("0123456789abcdefABCDEF")


def _to_qcolor(name: str, default: QtGui.QColor, *, bold: bool = False) -> QtGui.QColor:
    if not name or name == "default":
        return default
    if bold and name in _BRIGHTEN:
        name = _BRIGHTEN[name]
    hexv = _NAMED.get(name)
    if hexv:
        return QtGui.QColor(hexv)
    if len(name) == 6 and all(c in _HEXSET for c in name):
        return QtGui.QColor("#" + name)
    qc = QtGui.QColor(name)
    return qc if qc.isValid() else default


# ---- Qt 按键 → 终端字节 ----
_SPECIAL: dict = {
    Qt.Key.Key_Up: b"\x1b[A", Qt.Key.Key_Down: b"\x1b[B",
    Qt.Key.Key_Right: b"\x1b[C", Qt.Key.Key_Left: b"\x1b[D",
    Qt.Key.Key_Home: b"\x1b[H", Qt.Key.Key_End: b"\x1b[F",
    Qt.Key.Key_PageUp: b"\x1b[5~", Qt.Key.Key_PageDown: b"\x1b[6~",
    Qt.Key.Key_Insert: b"\x1b[2~", Qt.Key.Key_Delete: b"\x1b[3~",
    Qt.Key.Key_Return: b"\r", Qt.Key.Key_Enter: b"\r",
    Qt.Key.Key_Tab: b"\t", Qt.Key.Key_Backtab: b"\x1b[Z",
    Qt.Key.Key_Escape: b"\x1b", Qt.Key.Key_Backspace: b"\x7f",
    Qt.Key.Key_F1: b"\x1bOP", Qt.Key.Key_F2: b"\x1bOQ",
    Qt.Key.Key_F3: b"\x1bOR", Qt.Key.Key_F4: b"\x1bOS",
    Qt.Key.Key_F5: b"\x1b[15~", Qt.Key.Key_F6: b"\x1b[17~",
    Qt.Key.Key_F7: b"\x1b[18~", Qt.Key.Key_F8: b"\x1b[19~",
    Qt.Key.Key_F9: b"\x1b[20~", Qt.Key.Key_F10: b"\x1b[21~",
    Qt.Key.Key_F11: b"\x1b[23~", Qt.Key.Key_F12: b"\x1b[24~",
}
_CTRL_SYM: dict = {
    Qt.Key.Key_Space: 0x00, Qt.Key.Key_BracketLeft: 0x1b,
    Qt.Key.Key_Backslash: 0x1c, Qt.Key.Key_BracketRight: 0x1d,
}


class TerminalWidget(QtWidgets.QWidget):
    """自绘终端网格 + 回滚滚动 + 键盘直通。内容由 provider 按需提供。"""

    key_bytes = QtCore.Signal(bytes)       # 翻译好的终端字节，写进 PTY
    paste_text = QtCore.Signal(str)        # 粘贴的明文（外部用 bracketed-paste 包裹）
    resized = QtCore.Signal(int, int)      # rows, cols（防抖后）

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setMinimumHeight(300)

        font = QtGui.QFont("Menlo")
        font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        if not font.exactMatch():
            font = QtGui.QFont("Courier New")
            font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        font.setPointSize(12)
        self.setFont(font)
        fm = QtGui.QFontMetricsF(font)
        self._cell_w = max(1.0, fm.horizontalAdvance("M"))
        self._cell_h = max(1.0, fm.height())
        self._ascent = fm.ascent()

        # 配色
        self._bg_color = QtGui.QColor("#1e1e1e")
        self._fg_color = QtGui.QColor("#d4d4d4")
        self._cursor_color = QtGui.QColor("#cfcfcf")
        self._sel_bg = QtGui.QColor("#264f78")
        self._sel_fg = QtGui.QColor("#ffffff")

        # 右侧滚动条（子控件，手动布局）
        self._vbar = QtWidgets.QScrollBar(Qt.Orientation.Vertical, self)
        self._vbar.setSingleStep(1)
        self._vbar.valueChanged.connect(self._on_scroll)
        self._sb_w = self._vbar.sizeHint().width() or 14

        self._provider: Optional[Provider] = None
        self._cols = 0
        self._total = 0
        self._visible_top = 0
        self._visible_lines: list = []         # 当前可视窗口的单元格行
        self._cursor = (0, 0, True)            # x, y_full, hidden
        self._input_enabled = False

        # 选区（绝对坐标：x, 行号）
        self._sel_start: Optional[tuple[int, int]] = None
        self._sel_end: Optional[tuple[int, int]] = None

        self._resize_timer = QtCore.QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._emit_resize)
        self._last_emitted: Optional[tuple[int, int]] = None

    # ---------- 外部接口 ----------

    def set_provider(self, provider: Optional[Provider]) -> None:
        self._provider = provider
        self._sel_start = self._sel_end = None
        if provider is None:
            self._visible_lines = []
            self._total = 0
            self._cursor = (0, 0, True)
            self._vbar.setRange(0, 0)
            self.update()
        else:
            self.refresh(stick_bottom=True)

    def refresh(self, *, stick_bottom: bool = False) -> None:
        """重新从 provider 取片重绘。stick_bottom=True 时强制贴底（如切换会话）。"""
        if self._provider is None:
            return
        vis = self._visible_rows()
        sb = self._vbar
        was_bottom = stick_bottom or sb.value() >= sb.maximum() - 1
        try:
            total, cursor, _ = self._provider(0, 0)
        except Exception:
            return
        self._total = total
        self._cursor = cursor
        sb.blockSignals(True)
        sb.setPageStep(vis)
        sb.setRange(0, max(0, total - vis))
        if was_bottom:
            sb.setValue(sb.maximum())
        sb.blockSignals(False)
        self._pull_slice(sb.value())

    def clear_screen(self) -> None:
        self.set_provider(None)

    def set_input_enabled(self, on: bool) -> None:
        self._input_enabled = bool(on)
        self.update()

    def grid_size(self) -> tuple[int, int]:
        cols = max(20, int(self._text_width() // self._cell_w))
        rows = max(6, int(self.height() // self._cell_h))
        return rows, cols

    # ---------- 取片 / 滚动 ----------

    def _text_width(self) -> int:
        return max(1, self.width() - self._sb_w)

    def _visible_rows(self) -> int:
        return max(1, int(self.height() // self._cell_h))

    def _pull_slice(self, top: int) -> None:
        if self._provider is None:
            return
        vis = self._visible_rows()
        try:
            total, cursor, rows = self._provider(top, vis)
        except Exception:
            return
        self._total = total
        self._cursor = cursor
        self._visible_lines = rows
        self._visible_top = top
        self._cols = len(rows[0]) if rows else self._cols
        self.update()

    def _on_scroll(self, value: int) -> None:
        self._pull_slice(value)

    def _scroll_to_bottom(self) -> None:
        self._vbar.setValue(self._vbar.maximum())

    # ---------- 尺寸 ----------

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        super().resizeEvent(e)
        self._vbar.setGeometry(self.width() - self._sb_w, 0, self._sb_w, self.height())
        self.refresh()
        self._resize_timer.start(150)

    def _emit_resize(self) -> None:
        size = self.grid_size()
        if size != self._last_emitted:
            self._last_emitted = size
            self.resized.emit(size[0], size[1])

    # ---------- 绘制 ----------

    def paintEvent(self, e: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), self._bg_color)
        base_font = self.font()
        bold_font = QtGui.QFont(base_font)
        bold_font.setBold(True)
        cw, ch, asc = self._cell_w, self._cell_h, self._ascent
        sel = self._norm_selection()

        for sy, line in enumerate(self._visible_lines):
            ry = sy * ch
            abs_line = self._visible_top + sy
            for x, cell in enumerate(line):
                data, fg, bg, bold, reverse, underscore = cell
                fgc = _to_qcolor(fg, self._fg_color, bold=bold)
                bgc = _to_qcolor(bg, self._bg_color)
                if reverse:
                    fgc, bgc = bgc, fgc
                if sel is not None and self._in_selection(sel, abs_line, x):
                    fgc, bgc = self._sel_fg, self._sel_bg
                rx = x * cw
                if bgc.rgb() != self._bg_color.rgb():
                    p.fillRect(QtCore.QRectF(rx, ry, cw + 0.6, ch), bgc)
                if data and data != " ":
                    p.setFont(bold_font if bold else base_font)
                    p.setPen(fgc)
                    p.drawText(QtCore.QPointF(rx, ry + asc), data)
                if underscore:
                    p.setPen(fgc)
                    p.drawLine(QtCore.QPointF(rx, ry + ch - 1), QtCore.QPointF(rx + cw, ry + ch - 1))

        self._paint_cursor(p, base_font)
        p.end()

    def _paint_cursor(self, p: QtGui.QPainter, base_font: QtGui.QFont) -> None:
        cx, cy, hidden = self._cursor
        if hidden or not self._input_enabled:
            return
        sy = cy - self._visible_top
        if not (0 <= sy < len(self._visible_lines)):
            return
        line = self._visible_lines[sy]
        if not (0 <= cx < len(line)):
            return
        rx, ry = cx * self._cell_w, sy * self._cell_h
        rect = QtCore.QRectF(rx, ry, self._cell_w, self._cell_h)
        if self.hasFocus():
            p.fillRect(rect, self._cursor_color)
            data = line[cx][0]
            if data and data != " ":
                p.setFont(base_font)
                p.setPen(self._bg_color)
                p.drawText(QtCore.QPointF(rx, ry + self._ascent), data)
        else:
            p.setPen(self._cursor_color)
            p.drawRect(rect.adjusted(0, 0, -1, -1))

    # ---------- 选区 / 复制 ----------

    def _norm_selection(self):
        """返回归一化 ((x0,l0),(x1,l1)) 使 (l0,x0) <= (l1,x1)，无选区返回 None。"""
        if self._sel_start is None or self._sel_end is None or self._sel_start == self._sel_end:
            return None
        a, b = self._sel_start, self._sel_end
        ka, kb = (a[1], a[0]), (b[1], b[0])
        return (a, b) if ka <= kb else (b, a)

    @staticmethod
    def _in_selection(sel, line: int, x: int) -> bool:
        (x0, l0), (x1, l1) = sel
        return (l0, x0) <= (line, x) <= (l1, x1)

    def _cell_at(self, pos: QtCore.QPointF) -> tuple[int, int]:
        cols = self._cols or 1
        x = max(0, min(cols - 1, int(pos.x() // self._cell_w)))
        sy = max(0, min(max(0, len(self._visible_lines) - 1), int(pos.y() // self._cell_h)))
        return x, self._visible_top + sy

    def _copy_selection(self) -> None:
        sel = self._norm_selection()
        if sel is None or self._provider is None:
            return
        (x0, l0), (x1, l1) = sel
        cols = self._cols or 1
        try:
            _, _, rows = self._provider(l0, l1 - l0 + 1)
        except Exception:
            return
        out: list[str] = []
        for i, row in enumerate(rows):
            line_idx = l0 + i
            xs = x0 if line_idx == l0 else 0
            xe = x1 if line_idx == l1 else cols - 1
            seg = "".join((row[x][0] if x < len(row) else " ") for x in range(xs, xe + 1))
            out.append(seg.rstrip())
        text = "\n".join(out)
        if text.strip():
            QtWidgets.QApplication.clipboard().setText(text)

    def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._sel_start = self._cell_at(e.position())
            self._sel_end = self._sel_start
            self.update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QtGui.QMouseEvent) -> None:
        if self._sel_start is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self._sel_end = self._cell_at(e.position())
            self.update()
        super().mouseMoveEvent(e)

    def wheelEvent(self, e: QtGui.QWheelEvent) -> None:
        dy = e.angleDelta().y()
        if dy:
            step = 3 if dy < 0 else -3
            self._vbar.setValue(self._vbar.value() + step)
        e.accept()

    # ---------- 键盘 ----------

    def _is_copy(self, mods: Qt.KeyboardModifier, key: int) -> bool:
        if key != Qt.Key.Key_C or self._norm_selection() is None:
            return False
        if IS_MAC:
            return bool(mods & Qt.KeyboardModifier.ControlModifier)  # Cmd+C
        return bool(mods & Qt.KeyboardModifier.ControlModifier) and bool(mods & Qt.KeyboardModifier.ShiftModifier)

    def _is_paste(self, mods: Qt.KeyboardModifier, key: int) -> bool:
        if key != Qt.Key.Key_V:
            return False
        if IS_MAC:
            return bool(mods & Qt.KeyboardModifier.ControlModifier)  # Cmd+V
        return bool(mods & Qt.KeyboardModifier.ControlModifier) and bool(mods & Qt.KeyboardModifier.ShiftModifier)

    def _handle_scroll_key(self, mods: Qt.KeyboardModifier, key: int) -> bool:
        """Shift+PgUp/PgDn/Home/End 用于滚动查看历史（不发给 PTY）。返回是否已处理。"""
        if not (mods & Qt.KeyboardModifier.ShiftModifier):
            return False
        sb = self._vbar
        if key == Qt.Key.Key_PageUp:
            sb.setValue(sb.value() - sb.pageStep())
        elif key == Qt.Key.Key_PageDown:
            sb.setValue(sb.value() + sb.pageStep())
        elif key == Qt.Key.Key_Home:
            sb.setValue(0)
        elif key == Qt.Key.Key_End:
            sb.setValue(sb.maximum())
        else:
            return False
        return True

    def _translate(self, e: QtGui.QKeyEvent) -> Optional[bytes]:
        key, mods, text = e.key(), e.modifiers(), e.text()
        sp = _SPECIAL.get(key)
        if sp is not None:
            return sp
        if mods & _CTRL_MOD:
            if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                return bytes([key - Qt.Key.Key_A + 1])
            cs = _CTRL_SYM.get(key)
            if cs is not None:
                return bytes([cs])
        if text:
            b = text.encode("utf-8")
            if (mods & Qt.KeyboardModifier.AltModifier) and not IS_MAC:
                return b"\x1b" + b
            return b
        return None

    def keyPressEvent(self, e: QtGui.QKeyEvent) -> None:
        if not self._input_enabled:
            super().keyPressEvent(e)
            return
        mods, key = e.modifiers(), e.key()
        if self._is_copy(mods, key):
            self._copy_selection()
            e.accept()
            return
        if self._is_paste(mods, key):
            txt = QtWidgets.QApplication.clipboard().text()
            if txt:
                self.paste_text.emit(txt)
            e.accept()
            return
        if self._handle_scroll_key(mods, key):
            e.accept()
            return
        data = self._translate(e)
        if data:
            self._sel_start = self._sel_end = None
            self._scroll_to_bottom()   # 敲键就跳回底部，确保看到输入
            self.key_bytes.emit(data)
        e.accept()

    def inputMethodEvent(self, e: QtGui.QInputMethodEvent) -> None:
        # 基础 IME 支持：只在提交时把整段中文/候选字按 UTF-8 发出去（无预编辑显示）。
        if self._input_enabled and e.commitString():
            self._scroll_to_bottom()
            self.key_bytes.emit(e.commitString().encode("utf-8"))
        e.accept()
