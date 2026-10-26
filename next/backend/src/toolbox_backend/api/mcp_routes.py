from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from toolbox_backend.api.mcp_schemas import (
    ClientConfig,
    CredentialImport,
    CredentialKind,
    CredentialPut,
    MCPSettingsPatch,
    MCPSnapshot,
    PolicyImport,
    SelfTestRequest,
    SelfTestResult,
)
from toolbox_backend.api.settings_schemas import MutationResponse

router = APIRouter()


def service(request):
    return request.app.state.mcp_service


@router.get("/api/mcp", response_model=MCPSnapshot)
async def snapshot(request: Request):
    return await service(request).snapshot()


@router.patch("/api/mcp/settings", response_model=MutationResponse)
async def patch(body: MCPSettingsPatch, request: Request):
    return await service(request).patch(body)


@router.put("/api/mcp/credentials/{kind}", response_model=MutationResponse)
async def put_credential(kind: CredentialKind, body: CredentialPut, request: Request):
    return await service(request).credential(
        kind,
        body.revision,
        value=body.value.get_secret_value(),
        app_id=body.app_id,
        expiry_days=body.expiry_days,
    )


@router.delete("/api/mcp/credentials/{kind}", response_model=MutationResponse)
async def delete_credential(
    kind: CredentialKind,
    request: Request,
    revision: Annotated[int, Query(ge=0)],
    app_id: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,128}$")] = None,
):
    return await service(request).credential(kind, revision, app_id=app_id)


@router.post("/api/mcp/credentials/import-legacy", response_model=MutationResponse)
async def import_credentials(body: CredentialImport, request: Request):
    return await service(request).import_credentials(body)


@router.post("/api/mcp/ado/policy/import-legacy", response_model=MutationResponse)
async def import_policy(body: PolicyImport, request: Request):
    return await service(request).import_policy(body)


@router.get("/api/mcp/client-config", response_model=ClientConfig)
async def client_config(
    request: Request,
    server: Literal["ado", "lark", "figma"],
    cli: Literal["claude", "codex", "agy"],
):
    return await service(request).client_config(server, cli)


@router.post("/api/mcp/ado/self-test", response_model=SelfTestResult)
async def self_test(body: SelfTestRequest, request: Request):
    return await service(request).self_test(body)
