"""A client that stops reading must not affect others; its handler closes with 4408."""

import asyncio
import base64
import json
import os
import socket
import struct

import httpx
import websockets

from .conftest import start_backend

PAD = "x" * 60_000


def _masked_text_frame(text: str) -> bytes:
    payload = text.encode()
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    n = len(payload)
    header = b"\x81" + (bytes([0x80 | n]) if n < 126 else b"\xfe" + struct.pack(">H", n))
    return header + mask + masked


def _frames(buf: bytes):
    i = 0
    while i + 2 <= len(buf):
        op = buf[i] & 0x0F
        n = buf[i + 1] & 0x7F
        i += 2
        if n == 126:
            if i + 2 > len(buf):
                return
            n = struct.unpack(">H", buf[i : i + 2])[0]
            i += 2
        elif n == 127:
            if i + 8 > len(buf):
                return
            n = struct.unpack(">Q", buf[i : i + 8])[0]
            i += 8
        if i + n > len(buf):
            return
        yield op, buf[i : i + n]
        i += n


async def test_stalled_client_does_not_affect_fast_client_end_to_end():
    b = start_backend()
    try:
        raw = socket.socket()
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        raw.settimeout(5)
        raw.connect(("127.0.0.1", b.port))
        key = base64.b64encode(os.urandom(16)).decode()
        raw.sendall(
            (
                f"GET /ws/events HTTP/1.1\r\nHost: 127.0.0.1:{b.port}\r\nUpgrade: websocket\r\n"
                f"Origin: tauri://localhost\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        head = raw.recv(4096)
        assert b" 101 " in head.split(b"\r\n")[0]
        raw.sendall(_masked_text_frame(json.dumps({"type": "auth", "token": b.token})))
        # from now on the raw client never reads

        fast = await websockets.connect(f"ws://127.0.0.1:{b.port}/ws/events", origin="tauri://localhost")
        await fast.send(json.dumps({"type": "auth", "token": b.token}))
        received_alerts = 0

        async def reader():
            nonlocal received_alerts
            async for msg in fast:
                if json.loads(msg)["type"] == "system.alert":
                    received_alerts += 1

        task = asyncio.create_task(reader())
        sent = 0
        async with httpx.AsyncClient(timeout=10) as c:
            for _ in range(900):
                r = await c.post(
                    b.base + "/api/system/alert",
                    headers=b.auth,
                    json={"active": True, "reason": PAD},
                )
                assert r.status_code == 200
                sent += 1
        await asyncio.sleep(0.5)
        # the fast client got everything
        assert received_alerts == sent
        # now drain the slow socket: it must end with a 4408 close frame
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)  # let it drain quickly
        raw.settimeout(10)
        buf = b""
        got_eof = False
        try:
            while True:
                chunk = raw.recv(1 << 20)
                if not chunk:
                    got_eof = True
                    break
                buf += chunk
        except TimeoutError:
            pass
        closes = [p for op, p in _frames(buf) if op == 8]
        if closes:  # deliverable only if the transport drained before the close wait ended
            assert struct.unpack(">H", closes[-1][:2])[0] == 4408
        # How fast the stalled socket drains depends on the kernel, so EOF is not asserted;
        # the 4408 close itself is asserted deterministically by the handler-level test below.
        assert httpx.get(b.base + "/health", headers=b.auth, timeout=5).status_code == 200
        _ = got_eof
        task.cancel()
        await fast.close()
        raw.close()
    finally:
        b.stop_gracefully()


class FakeWebSocket:
    """Minimal stand-in whose send_text never completes (a fully stalled peer)."""

    def __init__(self, app, token):
        self.app = app
        self.headers = {"origin": "tauri://localhost"}
        self._token = token
        self.closed_with: int | None = None
        self._auth_sent = False
        self._never = asyncio.Event()

    async def accept(self):
        pass

    async def receive_text(self):
        if not self._auth_sent:
            self._auth_sent = True
            return json.dumps({"type": "auth", "token": self._token})
        await self._never.wait()

    async def receive(self):
        if not self._auth_sent:
            self._auth_sent = True
            return {
                "type": "websocket.receive",
                "text": json.dumps({"type": "auth", "token": self._token}),
            }
        await self._never.wait()

    async def send_text(self, _data):
        await self._never.wait()

    async def close(self, code=1000):
        self.closed_with = code


async def test_stalled_connection_closed_with_4408_via_handler():
    from toolbox_backend.api.ws import events
    from toolbox_backend.app import create_app
    from toolbox_backend.settings import Settings

    app = create_app(Settings(token="t", port=1, ws_queue_size=256))
    fake = FakeWebSocket(app, "t")
    task = asyncio.create_task(events(fake))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if app.state.hub.subscriber_count == 1:
            break
    assert app.state.hub.subscriber_count == 1
    other = app.state.hub.subscribe()
    # the pump takes the hello off the queue and blocks in send_text; then fill 256 + 1
    from toolbox_backend.domain.models import AlertState, SystemAlertEvent, utcnow

    state = AlertState(active=True, reason=None, changed_at=utcnow())
    for _ in range(300):
        app.state.hub.publish(SystemAlertEvent, state)
        other.queue.get_nowait()
    await asyncio.wait_for(task, 5)
    assert fake.closed_with == 4408
    assert app.state.hub.subscriber_count == 1  # only `other` remains
    assert not other.overflowed.is_set()
