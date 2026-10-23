"""S5-A routes, behind the existing S0 middleware boundary."""

import asyncio
import contextlib
import json
import struct
from typing import Literal

from fastapi import APIRouter, Query, Request, Response, WebSocket, WebSocketDisconnect

from toolbox_backend.api.ai_schemas import (
    AgyModels,
    AIEventsResponse,
    AISettingsPatch,
    AIView,
    ApprovalDecision,
    ApprovalResult,
    CheckResponse,
    JobResponse,
    ProfileCreate,
    ProfilePatch,
    ResumeCandidates,
    ResumeSession,
    SendMessage,
    SendResult,
    SessionCreate,
    SessionList,
    SessionState,
    SessionView,
)
from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.ws import _close, _first_frame_ok
from toolbox_backend.domain.errors import SettingsError

router = APIRouter()


@router.get("/api/ai", response_model=AIView)
async def settings(request: Request):
    return await request.app.state.ai_service.settings()


@router.post("/api/ai/profiles", response_model=MutationResponse)
async def profile_create(body: ProfileCreate, request: Request):
    return await request.app.state.ai_service.save_profile(body)


@router.patch("/api/ai/profiles/{pid}", response_model=MutationResponse)
async def profile_patch(pid: str, body: ProfilePatch, request: Request):
    return await request.app.state.ai_service.save_profile(body, pid)


@router.delete("/api/ai/profiles/{pid}", response_model=MutationResponse)
async def profile_delete(pid: str, request: Request, revision: int = Query(ge=0)):
    return await request.app.state.ai_service.delete_profile(pid, revision)


@router.patch("/api/ai/settings", response_model=MutationResponse)
async def settings_patch(body: AISettingsPatch, request: Request):
    return await request.app.state.ai_service.patch_settings(body)


@router.post("/api/ai/profiles/{pid}/check", response_model=CheckResponse)
async def check(pid: str, request: Request):
    return await request.app.state.ai_service.check(pid)


@router.post("/api/ai/profiles/{pid}/upgrade", response_model=JobResponse)
async def upgrade(pid: str, request: Request):
    return await request.app.state.ai_service.upgrade(pid)


@router.post("/api/ai/jobs/{jid}/cancel", response_model=JobResponse)
async def cancel_job(jid: str, request: Request):
    return await request.app.state.ai_service.cancel_job(jid)


@router.get("/api/ai/agy-models", response_model=AgyModels)
async def agy_models(request: Request):
    return await request.app.state.ai_service.agy_models()


@router.get("/api/ai/resume-candidates", response_model=ResumeCandidates)
async def resume_candidates(
    request: Request,
    repo_id: str = Query(min_length=1, max_length=128),
    cli: Literal["claude"] = "claude",
    query: str = Query(default="", max_length=64),
):
    return await request.app.state.ai_service.resume_candidates(repo_id, cli, query)


@router.post("/api/ai/sessions/{sid}/messages", response_model=SendResult)
async def send(sid: str, body: SendMessage, request: Request):
    return await request.app.state.ai_service.send(sid, body)


@router.post("/api/ai/sessions/{sid}/resume", response_model=SessionView)
async def resume(sid: str, body: ResumeSession, request: Request):
    return await request.app.state.ai_service.resume(sid, body)


@router.post("/api/ai/sessions/{sid}/approvals/{aid}", response_model=ApprovalResult)
async def approve(sid: str, aid: str, body: ApprovalDecision, request: Request):
    return await request.app.state.ai_service.decide(sid, aid, body)


@router.post("/api/ai/sessions", response_model=SessionView)
async def create(body: SessionCreate, request: Request):
    return await request.app.state.ai_service.create(body)


@router.get("/api/ai/sessions", response_model=SessionList)
async def sessions(
    request: Request,
    state: SessionState | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    return await request.app.state.ai_service.list(state, limit)


@router.get("/api/ai/sessions/{sid}", response_model=SessionView)
async def session(sid: str, request: Request):
    return await request.app.state.ai_service.get(sid)


@router.get("/api/ai/sessions/{sid}/events", response_model=AIEventsResponse)
async def events(
    sid: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    return await request.app.state.ai_store.events(sid, after_seq, limit)


@router.post("/api/ai/sessions/{sid}/interrupt", response_model=SessionView)
async def interrupt(sid: str, request: Request):
    return await request.app.state.ai_service.command(sid, "interrupt")


@router.post("/api/ai/sessions/{sid}/close", response_model=SessionView)
async def close(sid: str, request: Request):
    return await request.app.state.ai_service.command(sid, "close")


@router.delete("/api/ai/sessions/{sid}", status_code=204)
async def delete(sid: str, request: Request):
    await request.app.state.ai_service.delete(sid)
    return Response(status_code=204)


@router.websocket("/api/ai/terminals/{sid}/ws")
async def terminal_socket(sid: str, ws: WebSocket):
    settings = ws.app.state.settings
    if ws.headers.get("origin") not in settings.allowed_origins:
        await ws.close(code=1008)
        return
    await ws.accept()
    terminal = None
    tasks = set()
    try:
        if not await _first_frame_ok(ws, settings.token, settings.ws_auth_timeout_s):
            await _close(ws, 4401)
            return
        service = ws.app.state.ai_service
        row = await service.store.get(sid)
        if row["kind"] != "terminal":
            raise ValueError("not terminal")
        terminal = service.terminals.get(sid)
        if terminal is None:
            # Terminal output intentionally cannot be recovered after backend restart.
            from toolbox_backend.adapters.pty_terminal import PTYTerminal

            terminal = object.__new__(PTYTerminal)
            terminal.closed = True
            terminal.buffer = bytearray()
            terminal.offset = 0
            terminal.connections = 0
            terminal.changed = asyncio.Event()
            service.terminals[sid] = terminal
        if terminal.connections >= 2:
            terminal = None  # Do not decrement somebody else's reservation.
            await _close(ws, 1008)
            return
        terminal.connections += 1
        async with asyncio.timeout(settings.ws_auth_timeout_s):
            raw = await ws.receive_text()
        if len(raw) > 4096:
            raise ValueError("invalid attach")
        attach = json.loads(raw)
        if not isinstance(attach, dict) or attach.get("type") != "attach":
            raise ValueError("invalid attach")
        after = attach.get("after_offset")
        terminal.replay(after)

        async def output():
            offset = after
            while True:
                # Snapshot and clear happen without await; output arriving during send is
                # observed at the next iteration. Slow sockets never block the PTY reader.
                terminal.changed.clear()
                start, data = terminal.replay(offset)
                if data:
                    await ws.send_bytes(struct.pack(">Q", start) + data)
                    offset = start + len(data)
                elif terminal.closed:
                    return
                else:
                    await terminal.changed.wait()

        async def incoming():
            while True:
                raw = await ws.receive_text()
                if len(raw) > 24000:
                    raise ValueError("frame too large")
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    raise ValueError("invalid frame")
                if frame.get("type") == "input":
                    await terminal.input(frame.get("data"))
                elif frame.get("type") == "resize":
                    terminal.resize(frame.get("rows"), frame.get("cols"))
                else:
                    raise ValueError("invalid frame")

        tasks = {asyncio.create_task(output()), asyncio.create_task(incoming())}
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except ValueError, TypeError, RuntimeError, SettingsError, TimeoutError:
        await _close(ws, 1008)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if terminal:
            terminal.connections -= 1
        with contextlib.suppress(RuntimeError):
            await _close(ws, 1000)
