"""S8 VPN routes. Bearer/host/body guards are installed at the app boundary."""

from fastapi import APIRouter, Request

from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.vpn_schemas import (
    CredentialConfigured,
    CredentialWrite,
    LegacyCredentialsImport,
    ManualMfa,
    ManualMfaResult,
    TotpImport,
    VpnRunList,
    VpnRunRequest,
    VpnRunView,
    VpnSettingsPatch,
    VpnSnapshot,
)

router = APIRouter(prefix="/api/vpn")


@router.get("", response_model=VpnSnapshot)
async def status(request: Request):
    return await request.app.state.vpn_service.snapshot()


@router.patch("/settings", response_model=MutationResponse)
async def settings(body: VpnSettingsPatch, request: Request):
    service = request.app.state.vpn_service
    config = await service.update_settings(body)
    return MutationResponse(revision=config.revision)


@router.put("/credentials/{kind}", response_model=CredentialConfigured)
async def put_credential(kind: str, body: CredentialWrite, request: Request):
    request.app.state.vpn_service.write_credential(kind, body.value)
    return {"configured": True}


@router.delete("/credentials/{kind}", response_model=CredentialConfigured)
async def delete_credential(kind: str, request: Request):
    request.app.state.vpn_service.delete_credential(kind)
    return {"configured": False}


@router.post("/credentials/import-legacy")
async def import_legacy(body: LegacyCredentialsImport, request: Request):
    return await request.app.state.vpn_service.import_legacy(body.kinds, body.fields)


@router.post("/totp/import", response_model=CredentialConfigured)
async def import_totp(body: TotpImport, request: Request):
    return await request.app.state.vpn_service.import_totp(body.text, body.index)


@router.post("/connect", response_model=VpnRunView, status_code=202)
async def connect(body: VpnRunRequest, request: Request):
    return await request.app.state.vpn_service.start(
        request_id=body.request_id, allow_login=body.allow_login, max_rung=body.max_rung
    )


@router.post("/relogin", response_model=VpnRunView, status_code=202)
async def relogin(body: VpnRunRequest, request: Request):
    return await request.app.state.vpn_service.start(
        request_id=body.request_id, relogin=True, allow_login=True, max_rung=body.max_rung
    )


@router.post("/runs/{run_id}/cancel", response_model=VpnRunView)
async def cancel(run_id: str, request: Request):
    return await request.app.state.vpn_service.cancel(run_id)


@router.post("/runs/{run_id}/mfa", response_model=ManualMfaResult)
async def mfa(run_id: str, body: ManualMfa, request: Request):
    return await request.app.state.vpn_service.submit_mfa(run_id, body.code)


@router.get("/runs", response_model=VpnRunList)
async def runs(request: Request):
    return {"items": request.app.state.vpn_service.list_runs()}


@router.get("/runs/{run_id}", response_model=VpnRunView)
async def run(run_id: str, request: Request):
    return request.app.state.vpn_service.get_run(run_id)
