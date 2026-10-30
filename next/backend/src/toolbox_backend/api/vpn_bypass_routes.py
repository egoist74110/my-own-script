"""Bypass API with bearer/host/body guards and explicit OS authorization."""

from fastapi import APIRouter, Request

from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.domain.vpn_bypass import (
    BypassActionRequest,
    BypassExport,
    BypassExportRequest,
    BypassSettingsWrite,
    BypassSnapshot,
    BypassSweepRequest,
    BypassSweepResult,
)

router = APIRouter(prefix="/api/vpn/bypass", tags=["vpn-bypass"])


@router.get("", response_model=BypassSnapshot)
async def status(request: Request):
    return await request.app.state.vpn_bypass_service.snapshot()


@router.patch("/settings", response_model=MutationResponse)
async def settings(body: BypassSettingsWrite, request: Request):
    config = await request.app.state.vpn_bypass_service.update(body)
    return MutationResponse(revision=config.revision)


@router.post("/sweep", response_model=BypassSweepResult)
async def sweep(body: BypassSweepRequest, request: Request):
    return await request.app.state.vpn_bypass_service.sweep(body.apply)


@router.post("/export", response_model=BypassExport)
async def export(body: BypassExportRequest, request: Request):
    return await request.app.state.vpn_bypass_service.export(body.python_path)


@router.post("/activate", response_model=BypassSnapshot)
async def activate(body: BypassActionRequest, request: Request):
    return await request.app.state.vpn_bypass_service.activate(body.revision)


@router.post("/deactivate", response_model=BypassSnapshot)
async def deactivate(body: BypassActionRequest, request: Request):
    return await request.app.state.vpn_bypass_service.deactivate(body.revision)
