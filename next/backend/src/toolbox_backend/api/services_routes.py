"""All S7 endpoints share the application's S0 middleware boundary."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from toolbox_backend.api.services_schemas import (
    ActionRequest,
    LegacyImport,
    LogsResult,
    ProtocolRequest,
    ServicesSnapshot,
    SettingsPatch,
    SettingsResult,
    TunnelCreate,
)

router = APIRouter()


@router.get("/api/services", response_model=ServicesSnapshot)
async def snapshot(request: Request):
    return await request.app.state.services_service.snapshot()


@router.patch("/api/services/settings", response_model=SettingsResult)
async def settings(body: SettingsPatch, request: Request):
    return await request.app.state.services_service.patch_settings(body)


@router.post("/api/services/import-legacy", response_model=SettingsResult)
async def import_legacy(body: LegacyImport, request: Request):
    return await request.app.state.services_service.import_legacy(body)


@router.post("/api/services/cloudflared/tunnels", response_model=ServicesSnapshot)
async def create_tunnel(body: TunnelCreate, request: Request):
    return await request.app.state.services_service.create_tunnel(body)


@router.delete("/api/services/cloudflared/tunnels/{identifier}", response_model=ServicesSnapshot)
async def delete_tunnel(identifier: str, request: Request):
    return await request.app.state.services_service.delete_tunnel(identifier)


@router.post("/api/services/cloudflared/protocol", response_model=SettingsResult)
async def protocol(body: ProtocolRequest, request: Request):
    return await request.app.state.services_service.set_protocol(body)


@router.post("/api/services/{name}/start", response_model=ServicesSnapshot)
async def start(name: Literal["code-server", "cloudflared"], body: ActionRequest, request: Request):
    return await request.app.state.services_service.start(name, body)


@router.post("/api/services/{name}/stop", response_model=ServicesSnapshot)
async def stop(name: Literal["code-server", "cloudflared"], body: ActionRequest, request: Request):
    return await request.app.state.services_service.stop(name, body)


@router.get("/api/services/{name}/logs", response_model=LogsResult)
async def logs(name: str, request: Request, tail: Annotated[int, Query(ge=1, le=65536)] = 65536):
    return await request.app.state.services_service.logs(name, tail)
