"""Fault paths for process lifecycle: stdin EOF, signals, children, startup window, logs."""

import asyncio
import json
import signal
import socket
import subprocess
import time

import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from .harness import Proc, h, raw_http


async def _authed_ws(p: Proc):
    ws = await websockets.connect(f"ws://127.0.0.1:{p.port}/ws/events", open_timeout=5)
    await ws.send(json.dumps({"type": "auth", "token": p.token}))
    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert msg["type"] == "system.hello"
    return ws


def _children(pid: int) -> list[str]:
    out = subprocess.run(
        ["pgrep", "-P", str(pid)], capture_output=True, text=True, timeout=10
    ).stdout
    return [x for x in out.split() if x]


def _listening(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


async def test_stdin_eof_with_open_websockets_exits_zero_and_disconnects_clients():
    p = Proc().start()
    clients = []
    try:
        for _ in range(3):
            clients.append(await _authed_ws(p))
        assert _children(p.pid) == []
        p.close_stdin()
        started = time.monotonic()
        code = await asyncio.to_thread(p.wait_exit, 5)
        assert code == 0
        assert time.monotonic() - started < 5
        for ws in clients:
            with pytest.raises(ConnectionClosed):
                async with asyncio.timeout(5):
                    while True:
                        await ws.recv()
        assert not _listening(p.port)
    finally:
        for ws in clients:
            await ws.close()
        p.close()


async def test_sigterm_during_pending_auth_exits_zero_within_5s():
    p = Proc().start()
    try:
        ws = await websockets.connect(f"ws://127.0.0.1:{p.port}/ws/events", open_timeout=5)
        try:
            p.popen.send_signal(signal.SIGTERM)
            code = await asyncio.to_thread(p.wait_exit, 5)
            assert code == 0
        finally:
            await ws.close()
    finally:
        p.close()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
async def test_signal_with_active_http_and_ws_exits_zero_and_leaves_no_children(sig):
    p = Proc().start()
    try:
        ws = await _authed_ws(p)
        r = httpx.get(p.base + "/health", headers=p.auth, timeout=5)
        assert r.status_code == 200
        assert _children(p.pid) == []
        p.popen.send_signal(sig)
        code = await asyncio.to_thread(p.wait_exit, 5)
        assert code == 0
        with pytest.raises(ConnectionClosed):
            async with asyncio.timeout(5):
                while True:
                    await ws.recv()
    finally:
        p.close()


def test_stdin_devnull_at_launch_exits_zero_without_hanging():
    p = Proc(stdin=subprocess.DEVNULL)
    try:
        code = p.wait_exit(20)
        p.join_pumps()
        assert code == 0
        assert len(p.stdout_lines) <= 1
        assert all(line.startswith("TOOLBOX_READY ") for line in p.stdout_lines)
        if p.stdout_lines:  # READY may or may not be printed before EOF is seen
            token = json.loads(p.stdout_lines[0].partition(" ")[2])["token"]
            assert token not in p.stderr_text()
    finally:
        p.close()


@pytest.mark.parametrize("delay", [0.0, 0.01, 0.05, 0.15, 0.4])
def test_sigterm_during_startup_window_does_not_hang(delay):
    """Contract: SIGTERM -> exit 0. Observed exit code is asserted; a hang is a failure."""
    p = Proc()
    try:
        time.sleep(delay)
        p.popen.send_signal(signal.SIGTERM)
        code = p.wait_exit(15)
        p.join_pumps()
        # 主控裁决（S0A-003）：READY 之前送达的 SIGTERM 可能早于解释器执行任何 Python 代码，
        # 进程内无法处理，允许被信号终止；一旦输出 READY，必须协调退出码 0。
        allowed = (0,) if p.stdout_lines else (0, -signal.SIGTERM)
        assert code in allowed, f"exit code {code} after SIGTERM at +{delay}s (stdout={p.stdout_lines!r})"
        assert all(line.startswith("TOOLBOX_READY ") for line in p.stdout_lines)
        assert len(p.stdout_lines) <= 1
    finally:
        p.close()


@pytest.mark.parametrize(
    "args",
    [["--bogus"], ["--host", "0.0.0.0"], ["--port", "80"], ["--dev", "extra"]],
    ids=["bogus", "host-option", "port-option", "dev-positional"],
)
def test_unknown_arguments_exit_nonzero_without_ready(args):
    p = Proc(args)
    try:
        code = p.wait_exit(15)
        p.join_pumps()
        assert code != 0
        assert p.stdout_lines == []
    finally:
        p.close()


def test_token_never_reaches_stderr_under_error_inputs():
    p = Proc().start()
    token = p.token
    try:
        httpx.get(f"{p.base}/health?token={token}", timeout=5)  # 401, token in URL
        httpx.get(p.base + "/health", headers={"Host": f"{token}.evil"}, timeout=5)
        httpx.post(
            p.base + "/api/system/alert",
            headers={**p.auth, "Content-Type": "application/json"},
            content=('{"active": ' + token).encode(),
            timeout=5,
        )
        httpx.post(
            p.base + "/api/system/alert",
            headers={**p.auth, "Content-Type": "application/json"},
            content=b"[" * 50_000 + token.encode() + b"]" * 50_000,
            timeout=10,
        )
        raw_http(
            p.port,
            [
                b"GET /health HTTP/1.1",
                h(f"Host: 127.0.0.1:{p.port}"),
                h(f"Authorization: Bearer {token}x"),
                b"Connection: close",
            ],
        )

        async def ws_errors() -> None:
            ws = await websockets.connect(f"ws://127.0.0.1:{p.port}/ws/events", open_timeout=5)
            try:
                await ws.send(json.dumps({"type": "auth", "token": token, "junk": 1}) + "x")
                with pytest.raises(ConnectionClosed):
                    async with asyncio.timeout(8):
                        while True:
                            await ws.recv()
            finally:
                await ws.close()

            ws = await websockets.connect(f"ws://127.0.0.1:{p.port}/ws/events", open_timeout=5)
            try:
                await ws.send(token.encode())
                with pytest.raises(ConnectionClosed):
                    async with asyncio.timeout(8):
                        while True:
                            await ws.recv()
            finally:
                await ws.close()

        asyncio.run(ws_errors())
        time.sleep(0.3)
        assert p.stdout_lines[1:] == [], "stdout must stay silent after READY"
        p.close_stdin()
        assert p.wait_exit(10) == 0
        p.join_pumps()
        assert token not in p.stderr_text()
        assert token not in "".join(p.stdout_lines[1:])
    finally:
        p.close()
