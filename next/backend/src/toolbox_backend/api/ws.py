import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from toolbox_backend.api.middleware import token_matches
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.models import (
    RunEvent,
    RunEventData,
    RunSubscribedData,
    RunSubscribedEvent,
)

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


async def _run_enqueue(hub, sub, model, data):
    while sub.queue.full() and not sub.overflowed.is_set():
        sub.queue.space.clear()
        if sub.queue.full():
            await sub.queue.space.wait()
    if not sub.overflowed.is_set():
        hub.enqueue(sub, model, data)


async def _subscribe_run(ws, sub, frame):
    rid, after = frame.get("run_id"), frame.get("after_seq")
    if (
        not isinstance(rid, str)
        or len(rid) > 128
        or type(after) is not int
        or after < 0
        or (rid not in sub.runs and len(sub.runs) >= 8)
    ):
        raise ValueError("invalid subscription")
    hub, store = ws.app.state.hub, ws.app.state.run_store
    # Register before the first DB await. Concurrent commits are buffered until replay ends.
    sub.runs[rid] = after
    sub.replaying[rid] = []
    try:
        run = await store.get(rid)
        watermark = run["last_seq"]
        if after > watermark:
            raise ValueError("future cursor")
        while after < watermark:
            page = await store.events(rid, after, 1000)
            for event in page["items"]:
                if event["run_seq"] > watermark:
                    break
                await _run_enqueue(hub, sub, RunEvent, RunEventData(**event))
                after = event["run_seq"]
                sub.runs[rid] = after
        await _run_enqueue(
            hub, sub, RunSubscribedEvent, RunSubscribedData(run_id=rid, last_seq=watermark)
        )
        pending = sub.replaying[rid]
        while pending:
            event = pending.pop(0)
            if event["run_seq"] > sub.runs[rid]:
                await _run_enqueue(hub, sub, RunEvent, RunEventData(**event))
                sub.runs[rid] = event["run_seq"]
        del sub.replaying[rid]
    except BaseException:
        sub.runs.pop(rid, None)
        sub.replaying.pop(rid, None)
        raise


async def _drain_incoming(ws: WebSocket, sub=None) -> None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return
        if sub is None:
            continue
        raw = message.get("text")
        # S0 ignored post-auth garbage/binary frames. Only recognised run messages add
        # protocol semantics; keep existing clients and regression behavior unchanged.
        if raw is None or len(raw) > 4096:
            continue
        try:
            frame = json.loads(raw)
        except ValueError, RecursionError:
            continue
        if (
            not isinstance(frame, dict)
            or frame.get("topic") != "run"
            or frame.get("type") not in {"subscribe", "unsubscribe"}
        ):
            continue
        try:
            if frame.get("type") == "subscribe" and frame.get("topic") == "run":
                await _subscribe_run(ws, sub, frame)
            elif frame.get("type") == "unsubscribe" and frame.get("topic") == "run":
                sub.runs.pop(frame.get("run_id"), None)
                sub.replaying.pop(frame.get("run_id"), None)
        except ValueError, TypeError, SettingsError:
            await _close(ws, 1008)
            return


@router.websocket("/ws/events")
async def events(ws: WebSocket) -> None:
    app = ws.app
    settings = app.state.settings
    origin = ws.headers.get("origin")
    if origin not in settings.allowed_origins:
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
    incoming = asyncio.create_task(_drain_incoming(ws, sub))
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
