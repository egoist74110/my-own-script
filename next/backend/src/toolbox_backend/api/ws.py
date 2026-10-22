import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from toolbox_backend.api.middleware import token_matches

router = APIRouter()

CLOSE_AUTH = 4401
CLOSE_SLOW = 4408


async def _close(ws: WebSocket, code: int) -> None:
    # uvicorn gates every send (close frame included) on transport back-pressure, so for a
    # client that is not reading at all the close code cannot be delivered; the bounded wait
    # then ends and uvicorn tears the connection down. Other connections are never affected.
    with contextlib.suppress(Exception):
        await asyncio.wait_for(ws.close(code=code), timeout=2.0)


async def _first_frame_ok(ws: WebSocket, token: str, timeout_s: float) -> bool:
    try:
        async with asyncio.timeout(timeout_s):
            message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        raw = message.get("text")
        if raw is None:  # binary first frame
            return False
        frame = json.loads(raw)
    except TimeoutError, json.JSONDecodeError, RuntimeError, RecursionError:
        return False
    supplied = frame.get("token") if isinstance(frame, dict) else None
    return (
        isinstance(frame, dict)
        and frame.get("type") == "auth"
        and isinstance(supplied, str)
        and token_matches(supplied, token)
    )


async def _pump(ws: WebSocket, queue: asyncio.Queue[str]) -> None:
    while True:
        await ws.send_text(await queue.get())


async def _drain_incoming(ws: WebSocket) -> None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return


@router.websocket("/ws/events")
async def events(ws: WebSocket) -> None:
    app = ws.app
    settings = app.state.settings
    origin = ws.headers.get("origin")
    # Browsers always send Origin; non-browser clients may omit it.
    if origin is not None and origin not in settings.allowed_origins:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        if not await _first_frame_ok(ws, settings.token, settings.ws_auth_timeout_s):
            await _close(ws, CLOSE_AUTH)
            return
    except WebSocketDisconnect:
        return

    hub = app.state.hub
    system = app.state.system
    sub = hub.subscribe(hello=system.hello_json)
    pump = asyncio.create_task(_pump(ws, sub.queue))
    incoming = asyncio.create_task(_drain_incoming(ws))
    overflow = asyncio.create_task(sub.overflowed.wait())
    tasks = {pump, incoming, overflow}
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        hub.unsubscribe(sub)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    if sub.overflowed.is_set():
        await _close(ws, CLOSE_SLOW)
