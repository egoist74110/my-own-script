"""Shared helpers: launch the real backend as a subprocess with hard timeouts."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
READY_TIMEOUT_S = 20


class Backend:
    def __init__(self, *args: str, env_extra: dict[str, str] | None = None) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", **(env_extra or {})}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "toolbox_backend", *args],
            cwd=BACKEND_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._stdout_lines: queue.Queue[bytes] = queue.Queue()
        self.stderr_chunks: list[bytes] = []
        self.stdout_after_ready: list[bytes] = []
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        self.ready: dict = {}
        self.ready_raw = ""

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._stdout_lines.put(line)

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_chunks.append(line)

    def wait_ready(self) -> Backend:
        try:
            line = self._stdout_lines.get(timeout=READY_TIMEOUT_S).decode()
        except queue.Empty:
            self.kill()
            raise AssertionError("no READY line within timeout") from None
        self.ready_raw = line
        prefix, _, payload = line.rstrip("\n").partition(" ")
        assert prefix == "TOOLBOX_READY"
        self.ready = json.loads(payload)
        return self

    @property
    def port(self) -> int:
        return self.ready["port"]

    @property
    def token(self) -> str:
        return self.ready["token"]

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def extra_stdout(self) -> list[bytes]:
        out = []
        while True:
            try:
                out.append(self._stdout_lines.get_nowait())
            except queue.Empty:
                return out

    def stderr_text(self) -> str:
        return b"".join(self.stderr_chunks).decode(errors="replace")

    def wait_exit(self, timeout: float) -> int:
        return self.proc.wait(timeout=timeout)

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def stop_gracefully(self) -> None:
        """Close stdin and wait (used by fixtures); always reap in the end."""
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired, OSError:
            pass
        finally:
            self.kill()


def start_backend(*args: str, env_extra: dict[str, str] | None = None) -> Backend:
    backend = Backend(*args, env_extra=env_extra)
    try:
        return backend.wait_ready()
    except BaseException:
        backend.kill()
        raise


@pytest.fixture(scope="module")
def backend() -> Iterator[Backend]:
    b = start_backend(env_extra={"TOOLBOX_HEARTBEAT_INTERVAL_S": "0.2"})
    try:
        yield b
    finally:
        b.stop_gracefully()


@pytest.fixture(scope="module")
def dev_backend() -> Iterator[Backend]:
    b = start_backend("--dev")
    try:
        yield b
    finally:
        b.stop_gracefully()


def wait_until(predicate, timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
