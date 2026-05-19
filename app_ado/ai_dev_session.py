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
    "tab": b"\t",
    "y": b"y",
    "n": b"n",
    "ctrl_c": b"\x03",
    "ctrl_d": b"\x04",
    "backspace": b"\x7f",
    "space": b" ",
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
            self._screen = pyte.Screen(cols, rows)
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
        b = text.encode("utf-8", errors="replace")
        if append_enter:
            b = b + b"\r"
        return self.write_bytes(b)

    def send_key(self, key: str) -> bool:
        b = KEY_CODES.get(key.lower().strip())
        if b is None:
            return False
        return self.write_bytes(b)

    # ---------- screen ----------

    def snapshot_text(self) -> str:
        if self._screen is not None:
            lines = list(self._screen.display)
            return "\n".join(line.rstrip() for line in lines).rstrip("\n")
        if self._raw_buf is not None:
            return strip_ansi(self._raw_buf.decode("utf-8", errors="replace"))
        return ""

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
