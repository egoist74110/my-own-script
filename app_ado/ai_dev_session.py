"""AI 开发：基于 PTY 的多会话 AI CLI 包装。

每个 AiDevSession 在 PTY 里跑一个 AI CLI（Codex / Gemini CLI / Claude Code），用 pyte
维护一个虚拟终端屏幕，监听者可订阅每次屏幕更新。AiDevSessionManager 统一管理生命周期。

仅在 POSIX（macOS / Linux）下可用。Windows 不支持 fork+pty。
"""

from __future__ import annotations

import errno
import fcntl
import os
import re
import shlex
import shutil
import signal
import struct
import sys
import termios
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

try:  # pyte 是新增依赖；无 pyte 时退化为 strip ANSI 缓冲
    import pyte  # type: ignore
    _HAS_PYTE = True
except Exception:
    pyte = None  # type: ignore
    _HAS_PYTE = False


_SCROLLBACK_LINES = 5000  # GUI 终端回滚保留的历史行数上限

_YN_RE = re.compile(
    r"\(\s*(?:y\s*/\s*n|y\s*/\s*N|N\s*/\s*y|yes\s*/\s*no|是\s*/\s*否)\s*\)\s*[?？]?\s*$",
    re.IGNORECASE,
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-Z]")


KEY_CODES: dict[str, bytes] = {
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "enter": b"\r",
    "esc": b"\x1b",
    "esc_esc": b"\x1b\x1b",   # Claude Code 双 Esc = 清空输入
    "tab": b"\t",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "y": b"y",
    "n": b"n",
    "ctrl_c": b"\x03",
    "ctrl_d": b"\x04",
    "backspace": b"\x7f",
    "space": b" ",
    # 数字键：选 TUI 菜单项
    "1": b"1", "2": b"2", "3": b"3", "4": b"4", "5": b"5",
}


def _augment_path(env: dict[str, str]) -> dict[str, str]:
    """GUI app 启动子进程 PATH 不全是 macOS 老坑，这里补回常见 bin 目录。"""
    extras = [
        "/usr/local/bin",
        "/opt/homebrew/bin",
        str(Path.home() / ".gemini" / "bin"),
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / "bin"),
    ]
    parts = env.get("PATH", "").split(":") if env.get("PATH") else []
    for p in extras:
        if p and p not in parts and Path(p).exists():
            parts.append(p)
    env["PATH"] = ":".join(parts) if parts else env.get("PATH", "")
    return env


def resolve_command_executable(command: str) -> Optional[str]:
    if not command or not command.strip():
        return None
    try:
        argv = shlex.split(command)
    except Exception:
        return None
    if not argv:
        return None
    env = _augment_path(os.environ.copy())
    return shutil.which(argv[0], path=env["PATH"])


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@dataclass
class SessionInfo:
    sid: str
    model_id: str
    model_label: str
    repo_id: str
    repo_name: str
    cwd: str
    command: str
    pid: int = 0
    status: str = "starting"  # starting | running | waiting | exited
    exit_code: Optional[int] = None
    awaiting_yn: bool = False
    started_at: float = field(default_factory=time.time)


class AiDevSession:
    def __init__(
        self,
        *,
        sid: str,
        model_id: str,
        model_label: str,
        repo_id: str,
        repo_name: str,
        cwd: str,
        command: str,
        rows: int = 30,
        cols: int = 100,
    ) -> None:
        self.info = SessionInfo(
            sid=sid,
            model_id=model_id,
            model_label=model_label,
            repo_id=repo_id,
            repo_name=repo_name,
            cwd=cwd,
            command=command,
        )
        self._rows = rows
        self._cols = cols
        self._master_fd: Optional[int] = None
        self._proc_pid: Optional[int] = None
        self._closed = False
        self._listeners: list[Callable[[str, bool], None]] = []
        if _HAS_PYTE:
            # HistoryScreen 维护回滚缓冲（滚出屏幕的行进 history.top），GUI 据此实现滚动
            self._screen = pyte.HistoryScreen(cols, rows, history=_SCROLLBACK_LINES, ratio=0.5)
            self._stream = pyte.ByteStream(self._screen)
            self._raw_buf: Optional[bytearray] = None
        else:
            self._screen = None
            self._stream = None
            self._raw_buf = bytearray()

    # ---------- lifecycle ----------

    def start(self) -> None:
        if sys.platform == "win32":
            raise RuntimeError("AI 开发模块当前不支持 Windows（需要 PTY）")
        import pty

        master_fd, slave_fd = pty.openpty()
        try:
            packed = struct.pack("HHHH", self._rows, self._cols, 0, 0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, packed)
        except Exception:
            pass

        env = _augment_path(os.environ.copy())
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("FORCE_COLOR", "1")
        env.pop("CI", None)

        argv = shlex.split(self.info.command) if self.info.command else []
        if not argv:
            os.close(master_fd)
            os.close(slave_fd)
            raise RuntimeError("启动命令为空")
        full = shutil.which(argv[0], path=env["PATH"])
        if full:
            argv[0] = full

        cwd = self.info.cwd or os.getcwd()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(master_fd)
                os.setsid()
                try:
                    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                except Exception:
                    pass
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                if slave_fd > 2:
                    os.close(slave_fd)
                try:
                    os.chdir(cwd)
                except Exception:
                    pass
                os.execvpe(argv[0], argv, env)
            except Exception as e:
                try:
                    os.write(2, f"[ai_dev] exec failed: {e}\n".encode("utf-8"))
                except Exception:
                    pass
                os._exit(127)

        os.close(slave_fd)
        self._master_fd = master_fd
        self._proc_pid = pid
        self.info.pid = pid
        self.info.status = "running"

        threading.Thread(target=self._reader_loop, daemon=True).start()
        threading.Thread(target=self._waiter_loop, daemon=True).start()

    def _reader_loop(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        try:
            while not self._closed:
                try:
                    data = os.read(fd, 4096)
                except OSError as e:
                    if e.errno in (errno.EIO, errno.EBADF):
                        break
                    time.sleep(0.02)
                    continue
                if not data:
                    break
                self._on_bytes(data)
        finally:
            self._closed = True

    def _waiter_loop(self) -> None:
        pid = self._proc_pid
        if pid is None:
            return
        try:
            _, status = os.waitpid(pid, 0)
        except OSError:
            status = 0
        if os.WIFEXITED(status):
            code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            code = -os.WTERMSIG(status)
        else:
            code = -1
        self.info.exit_code = code
        self.info.status = "exited"
        self._closed = True
        self._notify(self.snapshot_text(), False)

    def _on_bytes(self, data: bytes) -> None:
        if self._stream is not None:
            try:
                self._stream.feed(data)
            except Exception:
                pass
        elif self._raw_buf is not None:
            self._raw_buf.extend(data)
            if len(self._raw_buf) > 256 * 1024:  # cap fallback buffer
                del self._raw_buf[: len(self._raw_buf) - 256 * 1024]

        snapshot = self.snapshot_text()
        last_line = snapshot.splitlines()[-1] if snapshot else ""
        yn = bool(_YN_RE.search(last_line))
        self.info.awaiting_yn = yn
        if not self._closed:
            self.info.status = "waiting" if yn else "running"
        self._notify(snapshot, yn)

    def _notify(self, snapshot: str, yn: bool) -> None:
        for cb in list(self._listeners):
            try:
                cb(snapshot, yn)
            except Exception:
                pass

    def add_listener(self, cb: Callable[[str, bool], None]) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[str, bool], None]) -> None:
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    # ---------- input ----------

    def write_bytes(self, data: bytes) -> bool:
        if self._master_fd is None or self._closed:
            return False
        try:
            os.write(self._master_fd, data)
            return True
        except OSError:
            return False

    def write_text(self, text: str, *, append_enter: bool = True) -> bool:
        # Claude Code / Codex / Gemini 是 ink raw-mode TUI，对一坨字节会做 heuristic
        # paste detection，末尾 \r 会被吃掉、必须用户再手动按 Enter 才提交。
        # 用 bracketed paste 显式包文本，让 TUI 明确认作粘贴；之后单独发 \r 才是真正
        # 的 Enter 键事件。
        body = text.encode("utf-8", errors="replace")
        ok = self.write_bytes(b"\x1b[200~" + body + b"\x1b[201~")
        if not ok or not append_enter:
            return ok
        time.sleep(0.05)
        return self.write_bytes(b"\r")

    def send_key(self, key: str) -> bool:
        b = KEY_CODES.get(key.lower().strip())
        if b is None:
            return False
        return self.write_bytes(b)

    def resize(self, rows: int, cols: int) -> bool:
        """跟随前端窗口调整终端尺寸：同步 pyte 屏幕 + 对 PTY 发 TIOCSWINSZ（触发 SIGWINCH）。"""
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        if rows == self._rows and cols == self._cols:
            return True
        self._rows, self._cols = rows, cols
        if self._screen is not None:
            try:
                self._screen.resize(rows, cols)
            except Exception:
                pass
        fd = self._master_fd
        if fd is not None and not self._closed:
            try:
                packed = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
            except Exception:
                pass
        return True

    # ---------- screen ----------

    def snapshot_text(self) -> str:
        if self._screen is not None:
            lines = list(self._screen.display)
            return "\n".join(line.rstrip() for line in lines).rstrip("\n")
        if self._raw_buf is not None:
            return strip_ansi(self._raw_buf.decode("utf-8", errors="replace"))
        return ""

    @staticmethod
    def _line_to_cells(line, cols: int) -> list:
        out = []
        for x in range(cols):
            c = line[x]
            out.append((c.data or " ", c.fg, c.bg, bool(c.bold), bool(c.reverse), bool(c.underscore)))
        return out

    @staticmethod
    def _line_blank(line, cols: int) -> bool:
        for x in range(cols):
            d = line[x].data
            if d and d != " ":
                return False
        return True

    def screen_view(self, start: int, count: int) -> tuple:
        """供 GUI 滚动渲染的「按需取片」接口（含历史回滚）。

        返回 (total, cursor, rows)：
          total  = 完整记录总行数（历史 + 当前页，已裁掉末尾空行，但保证含光标行）
          cursor = (x, y_full, hidden)，y_full 是在完整记录里的行号
          rows   = [start, start+count) 这一段的单元格行（只构建这一段，O(count)）

        count<=0 时只返回 (total, cursor, [])，用于廉价地取总行数/光标。
        无 pyte 时退化为纯文本网格。
        """
        scr = self._screen
        if scr is not None:
            try:
                cols = scr.columns
                page_rows = scr.lines
                hist = getattr(scr, "history", None)
                top_deque = list(hist.top) if (hist is not None and hist.top) else []
                n_hist = len(top_deque)
                buf = scr.buffer

                def _line_at(idx):
                    return buf[idx - n_hist] if idx >= n_hist else top_deque[idx]

                cur = scr.cursor
                cx = int(cur.x)
                cy = int(cur.y) + n_hist
                hidden = bool(getattr(cur, "hidden", False))

                # 从底部往上裁掉全空行（光标行及以上保留）
                last = n_hist + page_rows - 1
                while last > cy and last >= 0 and self._line_blank(_line_at(last), cols):
                    last -= 1
                total = max(last + 1, cy + 1, 0)
                cursor = (cx, cy, hidden)
                if count <= 0:
                    return total, cursor, []
                rows = [
                    self._line_to_cells(_line_at(idx), cols)
                    for idx in range(max(0, start), min(start + count, total))
                ]
                return total, cursor, rows
            except Exception:
                pass

        # fallback（无 pyte）
        all_lines = self.snapshot_text().split("\n")
        total = len(all_lines)
        cursor = (0, max(0, total - 1), True)
        if count <= 0:
            return total, cursor, []
        rows = [
            [(ch, "default", "default", False, False, False) for ch in ln]
            for ln in all_lines[max(0, start): start + count]
        ]
        return total, cursor, rows

    # ---------- shutdown ----------

    def close(self, *, grace_seconds: float = 2.0) -> None:
        if self._proc_pid is not None and not self._closed:
            try:
                os.kill(self._proc_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:
                pass
        deadline = time.time() + grace_seconds
        while not self._closed and time.time() < deadline:
            time.sleep(0.05)
        if not self._closed and self._proc_pid is not None:
            try:
                os.kill(self._proc_pid, signal.SIGKILL)
            except Exception:
                pass
        self._closed = True
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except Exception:
                pass
            self._master_fd = None


class AiDevSessionManager:
    """全局多会话注册表。线程安全。"""

    def __init__(self) -> None:
        self._sessions: dict[str, AiDevSession] = {}
        self._creation_order: list[str] = []
        self._lock = threading.Lock()

    def list(self) -> list[SessionInfo]:
        with self._lock:
            return [s.info for s in self._sessions.values()]

    def get(self, sid: str) -> Optional[AiDevSession]:
        with self._lock:
            return self._sessions.get(sid)

    def latest_sid(self) -> Optional[str]:
        with self._lock:
            return self._creation_order[-1] if self._creation_order else None

    def new(
        self,
        *,
        model_id: str,
        model_label: str,
        repo_id: str,
        repo_name: str,
        cwd: str,
        command: str,
    ) -> AiDevSession:
        with self._lock:
            sid = f"s{int(time.time() * 1000):013d}"
            while sid in self._sessions:
                sid = sid + "x"
        sess = AiDevSession(
            sid=sid,
            model_id=model_id,
            model_label=model_label,
            repo_id=repo_id,
            repo_name=repo_name,
            cwd=cwd,
            command=command,
        )
        with self._lock:
            self._sessions[sid] = sess
            self._creation_order.append(sid)
        sess.start()
        return sess

    def remove(self, sid: str) -> bool:
        with self._lock:
            sess = self._sessions.pop(sid, None)
            if sid in self._creation_order:
                self._creation_order.remove(sid)
        if sess is None:
            return False
        sess.close()
        return True

    def shutdown(self) -> None:
        with self._lock:
            sids = list(self._sessions.keys())
        for sid in sids:
            self.remove(sid)
