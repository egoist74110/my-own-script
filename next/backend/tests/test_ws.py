"""S0-A acceptance 4: /ws/events."""

import asyncio
import json
import time

import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

pytestmark = pytest.mark.asyncio


def uri(b):
    return f"ws://127.0.0.1:{b.port}/ws/events"


async def authed(b, **kw):
    ws = await websockets.connect(uri(b), **({"origin": "tauri://localhost"} | kw))
    await ws.send(json.dumps({"type": "auth", "token": b.token}))
    return ws


async def recv(ws, timeout=5):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def post_alert(b, active, reason=None):
    async with httpx.AsyncClient() as c:
        r = await c.post(
            b.base + "/api/system/alert",
            headers=b.auth,
            json={"active": active, "reason": reason},
            timeout=5,
        )
        assert r.status_code == 200


async def test_hello_alert_and_monotonic_seq(backend):
    ws = await authed(backend)
    try:
        hello = await recv(ws)
        assert set(hello) == {"seq", "topic", "type", "ts", "data"}
        assert hello["type"] == "system.hello" and hello["topic"] == "system"
        assert hello["data"]["pid"] == backend.proc.pid
        assert set(hello["data"]) == {"pid", "version", "alert"}
        assert set(hello["data"]["alert"]) == {"active", "reason", "changed_at"}
        await post_alert(backend, True, "demo")
        seqs = [hello["seq"]]
        got_alert = None
        deadline = time.monotonic() + 5
        while got_alert is None and time.monotonic() < deadline:
            ev = await recv(ws)
            seqs.append(ev["seq"])
            if ev["type"] == "system.alert":
                got_alert = ev
        assert got_alert and got_alert["data"]["active"] is True
        assert got_alert["data"]["reason"] == "demo"
        assert all(b > a for a, b in zip(seqs, seqs[1:], strict=False))
        await post_alert(backend, False)
    finally:
        await ws.close()


async def test_heartbeat_with_injected_interval(backend):
    ws = await authed(backend)
    try:
        await recv(ws)  # hello
        beats = []
        while len(beats) < 2:
            ev = await recv(ws, timeout=3)
            if ev["type"] == "system.heartbeat":
                beats.append(ev)
        assert beats[1]["seq"] > beats[0]["seq"]
        assert beats[1]["data"]["uptime_s"] > beats[0]["data"]["uptime_s"]
        assert beats[0]["topic"] == "system"
    finally:
        await ws.close()


async def test_bad_origin_rejected_at_handshake(backend):
    with pytest.raises(InvalidStatus) as exc:
        await websockets.connect(uri(backend), origin="https://evil.example")
    assert exc.value.response.status_code == 403


async def test_allowed_origin_accepted(backend):
    ws = await authed(backend, origin="tauri://localhost")
    try:
        assert (await recv(ws))["type"] == "system.hello"
    finally:
        await ws.close()


async def test_dev_origin_only_in_dev(backend, dev_backend):
    with pytest.raises(InvalidStatus):
        await websockets.connect(uri(backend), origin="http://localhost:1420")
    ws = await authed(dev_backend, origin="http://localhost:1420")
    try:
        assert (await recv(ws))["type"] == "system.hello"
    finally:
        await ws.close()


async def test_bad_host_rejected(backend):
    import socket

    def handshake() -> bytes:
        with socket.create_connection(("127.0.0.1", backend.port), timeout=5) as s:
            s.sendall(
                b"GET /ws/events HTTP/1.1\r\nHost: evil.com\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                b"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            return s.recv(4096)

    reply = await asyncio.get_running_loop().run_in_executor(None, handshake)
    assert b" 101 " not in reply.split(b"\r\n")[0]
    assert reply.split(b"\r\n")[0].split()[1] in (b"400", b"403")


@pytest.mark.parametrize(
    "frame",
    [
        '{"type":"auth","token":"wrong"}',
        "not json",
        '{"type":"hello"}',
        '{"type":"auth"}',
        "[1]",
        '{"type":"auth","token":5}',
    ],
)
async def test_bad_first_frame_closes_4401(backend, frame):
    ws = await websockets.connect(uri(backend), origin="tauri://localhost")
    await ws.send(frame)
    with pytest.raises(ConnectionClosed):
        await asyncio.wait_for(ws.recv(), 5)
    assert ws.close_code == 4401


async def test_no_auth_frame_closes_4401_within_5s(backend):
    started = time.monotonic()
    ws = await websockets.connect(uri(backend), origin="tauri://localhost")
    with pytest.raises(ConnectionClosed):
        await asyncio.wait_for(ws.recv(), 8)
    elapsed = time.monotonic() - started
    assert ws.close_code == 4401
    assert 4.0 <= elapsed < 6.5


async def test_auth_failure_does_not_break_other_clients(backend):
    good = await authed(backend)
    try:
        await recv(good)
        bad = await websockets.connect(uri(backend), origin="tauri://localhost")
        await bad.send('{"type":"auth","token":"x"}')
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(bad.recv(), 5)
        await post_alert(backend, False)
        while (await recv(good))["type"] != "system.alert":
            pass
    finally:
        await good.close()
