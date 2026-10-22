"""Independent harness: launches the real backend with hard timeouts and always reaps it.

Each process gets a private HOME/XDG dir (removed on close). Only the process this harness
spawned is signalled; nothing is killed by name.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
READY_TIMEOUT_S = 20.0


class Proc:
    def __init__(
        self,
        args: list[str] | tuple[str, ...] = (),
        env_extra: dict[str, str] | None = None,
        stdin: int = subprocess.PIPE,
    ) -> None:
        self.home = tempfile.mkdtemp(prefix="indep-home-")
        env = {k: v for k, v in os.environ.items() if not k.startswith("TOOLBOX_")}
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "HOME": self.home,
                "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            }
        )
        env.update(env_extra or {})
        try:
            self.popen = subprocess.Popen(
                [sys.executable, "-m", "toolbox_backend", *args],
                cwd=BACKEND_DIR,
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except BaseException:
            shutil.rmtree(self.home, ignore_errors=True)
            raise
        self._out: queue.Queue[str] = queue.Queue()
        self.stdout_lines: list[str] = []
        self._err: list[bytes] = []
        self._pumps = [
            threading.Thread(target=self._pump_out, daemon=True),
            threading.Thread(target=self._pump_err, daemon=True),
        ]
        for t in self._pumps:
            t.start()
        self.ready: dict = {}
        self.ready_line = ""

    def _pump_out(self) -> None:
        assert self.popen.stdout is not None
        try:
            for raw in self.popen.stdout:
                line = raw.decode("utf-8", errors="replace")
                self.stdout_lines.append(line)
                self._out.put(line)
        except OSError, ValueError:
            pass

    def _pump_err(self) -> None:
        assert self.popen.stderr is not None
        try:
            for raw in self.popen.stderr:
                self._err.append(raw)
        except OSError, ValueError:
            pass

    def start(self) -> Proc:
        """Wait for the READY line; on any failure the process is reaped before raising."""
        try:
            deadline = time.monotonic() + READY_TIMEOUT_S
            line = None
            while time.monotonic() < deadline:
                try:
                    line = self._out.get(timeout=0.1)
                    break
                except queue.Empty:
                    if self.popen.poll() is not None:
                        break
            if line is None:
                raise AssertionError(f"no READY line (exit={self.popen.poll()})")
            prefix, _, payload = line.rstrip("\n").partition(" ")
            assert prefix == "TOOLBOX_READY", line
            self.ready_line = line
            self.ready = json.loads(payload)
        except BaseException:
            self.close()
            raise
        return self

    @property
    def pid(self) -> int:
        return self.popen.pid

    @property
    def port(self) -> int:
        return int(self.ready["port"])

    @property
    def token(self) -> str:
        return str(self.ready["token"])

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def stderr_text(self) -> str:
        return b"".join(self._err).decode("utf-8", errors="replace")

    def close_stdin(self) -> None:
        if self.popen.stdin is not None and not self.popen.stdin.closed:
            try:
                self.popen.stdin.close()
            except OSError:
                pass

    def wait_exit(self, timeout: float) -> int:
        return self.popen.wait(timeout=timeout)

    def join_pumps(self, timeout: float = 3.0) -> None:
        for t in self._pumps:
            t.join(timeout)

    def close(self) -> None:
        """Graceful stdin EOF first, then a hard kill of this child only; always reaps."""
        try:
            self.close_stdin()
            try:
                self.popen.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.popen.kill()
                self.popen.wait(timeout=5)
        finally:
            for stream in (self.popen.stdout, self.popen.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            shutil.rmtree(self.home, ignore_errors=True)


def h(value: str) -> bytes:
    return value.encode("latin-1")


def raw_http(
    port: int, lines: list[bytes], body: bytes = b"", timeout: float = 5.0
) -> tuple[int | None, bytes]:
    """Send exact request bytes (no client normalisation). Returns (status or None, raw)."""
    head = b"\r\n".join(lines) + b"\r\n\r\n"
    chunks: list[bytes] = []
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        try:
            sock.sendall(head + body)
        except BrokenPipeError, ConnectionResetError:
            pass
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except TimeoutError, ConnectionResetError, BrokenPipeError:
            pass
    raw = b"".join(chunks)
    status = None
    if raw.startswith(b"HTTP/"):
        parts = raw.split(b" ", 2)
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
    return status, raw


def wait_until(predicate: Callable[[], bool], timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def open_fd_count(pid: int) -> int:
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    out = subprocess.run(
        [lsof, "-n", "-P", "-p", str(pid)], capture_output=True, text=True, timeout=30
    ).stdout
    return max(len(out.splitlines()) - 1, 0)
