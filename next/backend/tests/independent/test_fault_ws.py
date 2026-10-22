"""Fault paths for /ws/events: first-frame auth, Origin, isolation, churn, no leaks."""

import asyncio
import json
import socket
import struct

import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from .harness import Proc, open_fd_count, wait_until


def uri(b: Proc) -> str:
    return f"ws://127.0.0.1:{b.port}/ws/events"


async def connect(b: Proc, origin: str | None = "tauri://localhost", headers: dict[str, str] | None = None):
    return await websockets.connect(
        uri(b), origin=origin, additional_headers=headers, open_timeout=5, close_timeout=5
    )


async def authed(b: Proc, token: str | None = None, origin: str | None = "tauri://localhost"):
    ws = await connect(b, origin=origin)
    await ws.send(json.dumps({"type": "auth", "token": b.token if token is None else token}))
    return ws


async def next_event(ws, timeout: float = 5.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def close_code(ws, timeout: float = 8.0, allow_messages: bool = False) -> int | None:
    """Drain until the server closes; fail if a message arrives and it is not allowed."""

    async def drain() -> None:
        while True:
            msg = await ws.recv()
            if not allow_messages:
                raise AssertionError(f"unexpected frame before close: {msg!r}")

    try:
        await asyncio.wait_for(drain(), timeout)
    except ConnectionClosed:
        return ws.close_code
    except TimeoutError:
        raise AssertionError("connection was not closed within timeout") from None
    raise AssertionError("unreachable")


async def collect_until_alerts(ws, n: int, timeout: float = 10.0) -> list[dict]:
    events: list[dict] = []
    async with asyncio.timeout(timeout):
        while sum(e["type"] == "system.alert" for e in events) < n:
            events.append(json.loads(await ws.recv()))
    return events


def post_alert_sync(b: Proc, active: bool) -> None:
    r = httpx.post(
        b.base + "/api/system/alert",
        headers=b.auth,
        json={"active": active, "reason": None},
        timeout=5,
    )
    assert r.status_code == 200


def healthy(b: Proc) -> bool:
    return httpx.get(b.base + "/health", headers=b.auth, timeout=5).status_code == 200


def abort_transport(ws) -> None:
    """Abrupt close: no WebSocket close frame, the TCP transport is torn down."""
    ws.transport.abort()


def raw_upgrade_then_reset(port: int) -> None:
    """Complete the HTTP upgrade by hand, then RST the socket before any auth frame."""
    req = (
        "GET /ws/events HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
    ).encode()
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        sock.sendall(req)
        sock.recv(4096)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    finally:
        sock.close()


# ---------- isolation between clients


async def test_bad_and_silent_clients_do_not_affect_good_clients(ind_backend):
    b = ind_backend
    good = [await authed(b) for _ in range(10)]
    bad = []
    for _ in range(5):
        ws = await connect(b)
        await ws.send(json.dumps({"type": "auth", "token": "wrong-token"}))
        bad.append(ws)
    silent = [await connect(b) for _ in range(5)]
    try:
        # Post-alert events must reach every good client, in the same order, with monotonic seq.
        for active in (True, False, True):
            post_alert_sync(b, active)
        streams = await asyncio.gather(*(collect_until_alerts(ws, 3) for ws in good))
        alert_seqs = []
        for events in streams:
            assert events[0]["type"] == "system.hello"
            seqs = [e["seq"] for e in events]
            assert all(x < y for x, y in zip(seqs, seqs[1:], strict=False)), seqs
            alert_seqs.append([e["seq"] for e in events if e["type"] == "system.alert"])
        assert all(s == alert_seqs[0] for s in alert_seqs), alert_seqs
        bad_codes = await asyncio.gather(*(close_code(ws) for ws in bad))
        assert bad_codes == [4401] * 5
        silent_codes = await asyncio.gather(*(close_code(ws) for ws in silent))
        assert silent_codes == [4401] * 5
        assert healthy(b)
    finally:
        for ws in good + bad + silent:
            await ws.close()


async def test_abrupt_disconnects_before_and_after_auth_leave_others_intact(ind_backend):
    b = ind_backend
    survivor = await authed(b)
    try:
        assert (await next_event(survivor))["type"] == "system.hello"
        for _ in range(20):
            await asyncio.to_thread(raw_upgrade_then_reset, b.port)
        for _ in range(20):
            ws = await authed(b)
            await next_event(ws)  # hello
            abort_transport(ws)
        post_alert_sync(b, True)
        events = await collect_until_alerts(survivor, 1)
        assert any(e["type"] == "system.alert" for e in events)
        post_alert_sync(b, False)
        assert healthy(b)
    finally:
        await survivor.close()


async def test_unauthenticated_client_receives_no_event_from_broadcasts(ind_backend):
    b = ind_backend
    ws = await connect(b)
    try:
        post_alert_sync(b, True)
        post_alert_sync(b, False)
        assert await close_code(ws, timeout=8.0, allow_messages=False) == 4401
    finally:
        await ws.close()


# ---------- first-frame authentication


FRAME_CASES = [
    ("text", "empty", ""),
    ("text", "not-json", "not json"),
    ("text", "null", "null"),
    ("text", "array", "[]"),
    ("text", "string", '"auth"'),
    ("text", "no-token", '{"type":"auth"}'),
    ("text", "token-int", '{"type":"auth","token":123}'),
    ("text", "token-null", '{"type":"auth","token":null}'),
    ("text", "type-case", '{"type":"AUTH","token":"TOKEN"}'),
    ("text", "no-type", '{"token":"TOKEN"}'),
    ("text", "deep-nesting-unterminated", "[" * 100_000),
    ("text", "deep-nesting-balanced", "[" * 100_000 + "]" * 100_000),
    ("bytes", "binary-garbage", b"\x00\x01\x02"),
    ("bytes", "binary-valid-auth", b'{"type":"auth","token":"TOKEN"}'),
]


@pytest.mark.parametrize("kind,ident,payload", FRAME_CASES, ids=[c[1] for c in FRAME_CASES])
async def test_malformed_first_frame_closes_4401(ind_backend, kind, ident, payload):
    b = ind_backend
    if isinstance(payload, str):
        payload = payload.replace("TOKEN", b.token)
    else:
        payload = payload.replace(b"TOKEN", b.token.encode())
    ws = await connect(b)
    try:
        await ws.send(payload)
        assert await close_code(ws) == 4401
    finally:
        await ws.close()
    assert healthy(b)


async def test_oversized_first_frame_is_closed_and_server_survives(ind_backend):
    # uvicorn's default WebSocket max size is 16 MiB; 17 MiB must be refused by the protocol layer.
    b = ind_backend
    ws = await connect(b)
    try:
        await ws.send("a" * (17 * 1024 * 1024))
        code = await close_code(ws)
        assert code == 1009, code
    finally:
        await ws.close()
    assert healthy(b)


async def test_bearer_header_does_not_authenticate_websocket(ind_backend):
    b = ind_backend
    ws = await connect(b, headers={"Authorization": f"Bearer {b.token}"})
    try:
        # Contract: WebSocket authenticates by first frame only; header auth must not grant events.
        assert await close_code(ws, timeout=8.0) == 4401
    finally:
        await ws.close()


async def test_auth_with_correct_token_then_garbage_frames_keeps_connection(ind_backend):
    b = ind_backend
    ws = await authed(b)
    try:
        assert (await next_event(ws))["type"] == "system.hello"
        for i in range(100):
            await ws.send("x" * 1000 if i % 2 else b"\x00\xff")
        await ws.send("[" * 100_000)
        post_alert_sync(b, True)
        events = await collect_until_alerts(ws, 1)
        assert any(e["type"] == "system.alert" for e in events)
        assert ws.close_code is None
        post_alert_sync(b, False)
    finally:
        await ws.close()
    assert healthy(b)


# ---------- Origin


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "https://tauri.localhost",
        "tauri://localhost.evil.com",
        "http://tauri.localhost:8080",
        "http://localhost:1420",
        "http://evil.example",
    ],
)
async def test_foreign_origin_rejected_at_handshake(ind_backend, origin):
    with pytest.raises(InvalidStatus) as exc:
        await connect(ind_backend, origin=origin)
    assert exc.value.response.status_code == 403


@pytest.mark.parametrize("origin", ["tauri://localhost", "http://tauri.localhost"])
async def test_tauri_origins_accepted(ind_backend, origin):
    ws = await authed(ind_backend, origin=origin)
    try:
        assert (await next_event(ws))["type"] == "system.hello"
    finally:
        await ws.close()


async def test_missing_origin_rejected_at_handshake(ind_backend):
    with pytest.raises(InvalidStatus) as exc:
        await connect(ind_backend, origin=None)
    assert exc.value.response.status_code == 403


async def test_dev_origins_only_in_dev_mode_on_websocket(ind_dev, ind_backend):
    ws = await authed(ind_dev, origin="http://127.0.0.1:1420")
    try:
        assert (await next_event(ws))["type"] == "system.hello"
    finally:
        await ws.close()
    with pytest.raises(InvalidStatus) as exc:
        await connect(ind_backend, origin="http://127.0.0.1:1420")
    assert exc.value.response.status_code == 403


# ---------- ordering and churn


async def test_concurrent_alert_burst_has_no_loss_and_strict_seq(ind_backend):
    b = ind_backend
    ws = await authed(b)
    try:
        assert (await next_event(ws))["type"] == "system.hello"
        async with httpx.AsyncClient(timeout=10) as client:
            results = await asyncio.gather(
                *(
                    client.post(
                        b.base + "/api/system/alert",
                        headers=b.auth,
                        json={"active": i % 2 == 0, "reason": f"burst-{i}"},
                    )
                    for i in range(40)
                )
            )
        assert all(r.status_code == 200 for r in results)
        events = await collect_until_alerts(ws, 40, timeout=15)
        seqs = [e["seq"] for e in events]
        assert all(x < y for x, y in zip(seqs, seqs[1:], strict=False))
        assert sum(e["type"] == "system.alert" for e in events) == 40
    finally:
        await ws.close()
    post_alert_sync(b, False)


async def test_connection_churn_does_not_leak_fds_or_break_service(ind_backend):
    b = ind_backend
    assert wait_until(lambda: healthy(b), 5)
    await asyncio.sleep(1.0)
    baseline = await asyncio.to_thread(open_fd_count, b.pid)
    for _ in range(120):
        ws = await authed(b)
        await next_event(ws)
        await ws.close()
    for _ in range(40):
        ws = await authed(b)
        await next_event(ws)
        abort_transport(ws)
    for _ in range(40):
        await asyncio.to_thread(raw_upgrade_then_reset, b.port)
    for _ in range(20):
        ws = await connect(b)
        await ws.send("[" * 100_000)
        await ws.close()

    def settled() -> bool:
        return open_fd_count(b.pid) <= baseline + 3

    settled_ok = False
    for _ in range(60):
        if await asyncio.to_thread(settled):
            settled_ok = True
            break
        await asyncio.sleep(0.25)
    after = await asyncio.to_thread(open_fd_count, b.pid)
    assert settled_ok, f"fd count did not return to baseline: baseline={baseline} after={after}"
    ws = await authed(b)
    try:
        hello = await next_event(ws)
        assert hello["type"] == "system.hello"
    finally:
        await ws.close()
    assert healthy(b)


async def test_zz_module_stderr_has_no_traceback(ind_backend):
    """Runs last in this module: unhandled exceptions from any fault case show up here."""
    await asyncio.sleep(0.5)
    text = ind_backend.stderr_text()
    errors = [line for line in text.splitlines() if "Error" in line or "Traceback" in line]
    assert "Traceback" not in text, "unhandled exceptions in stderr: " + " | ".join(errors[-8:])
