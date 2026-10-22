"""S0-A acceptance 1 and 5: handshake and lifecycle."""

import signal
import socket
import time

import httpx
import pytest

from .conftest import start_backend


def test_ready_line_format_and_uniqueness():
    a = start_backend()
    b = start_backend()
    try:
        assert a.ready_raw.startswith("TOOLBOX_READY {") and a.ready_raw.endswith("}\n")
        assert a.ready["v"] == 1 and a.ready["pid"] == a.proc.pid
        assert set(a.ready) == {"v", "port", "token", "pid"}
        assert a.port != b.port and a.token != b.token
        assert len(a.token) >= 43
        assert a.port != 0
    finally:
        a.stop_gracefully()
        b.stop_gracefully()


def test_accepts_connections_immediately_after_ready():
    for _ in range(3):
        b = start_backend()
        try:
            with socket.create_connection(("127.0.0.1", b.port), timeout=2):
                pass
            r = httpx.get(b.base + "/health", headers=b.auth, timeout=5)
            assert r.status_code == 200
        finally:
            b.stop_gracefully()


def test_stdout_silent_after_ready_and_stderr_has_no_token():
    b = start_backend()
    try:
        httpx.get(b.base + "/health", headers=b.auth, timeout=5)
        httpx.get(b.base + "/health", headers={"Authorization": "Bearer wrong"}, timeout=5)
        httpx.post(
            b.base + "/api/system/alert",
            headers=b.auth,
            json={"active": True, "reason": b.token},  # a leaked token in data must be redacted
            timeout=5,
        )
    finally:
        b.proc.stdin.close()
        assert b.wait_exit(10) == 0
    time.sleep(0.2)
    assert b.extra_stdout() == []
    err = b.stderr_text()
    assert err  # logs go to stderr
    assert b.token not in err
    b.kill()


def test_stdin_eof_exits_zero_within_5s():
    b = start_backend()
    try:
        started = time.monotonic()
        b.proc.stdin.close()
        assert b.wait_exit(5) == 0
        assert time.monotonic() - started < 5
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", b.port), timeout=1)
    finally:
        b.kill()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_exits_zero(sig):
    b = start_backend()
    try:
        b.proc.send_signal(sig)
        assert b.wait_exit(5) == 0
    finally:
        b.kill()


def test_signal_exits_zero_with_open_websocket():
    import asyncio

    import websockets

    async def scenario() -> None:
        b = start_backend()
        try:
            uri = f"ws://127.0.0.1:{b.port}/ws/events"
            async with websockets.connect(uri) as ws:
                await ws.send('{"type":"auth","token":"%s"}' % b.token)
                await asyncio.wait_for(ws.recv(), 5)
                b.proc.send_signal(signal.SIGTERM)
                loop = asyncio.get_running_loop()
                code = await loop.run_in_executor(None, b.wait_exit, 8)
                assert code == 0
        finally:
            b.kill()

    asyncio.run(scenario())


def test_startup_does_not_leave_children():
    b = start_backend()
    pid = b.proc.pid
    b.stop_gracefully()
    with pytest.raises(ProcessLookupError):
        import os

        os.kill(pid, 0)


def test_no_listen_address_option():
    from .conftest import Backend

    b = Backend("--host", "0.0.0.0")
    try:
        assert b.wait_exit(10) != 0
        time.sleep(0.2)
        assert b.extra_stdout() == []
    finally:
        b.kill()
