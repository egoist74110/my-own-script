from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Request

from toolbox_backend.api.mcp_schemas import (
    ClientConfig,
    CredentialImport,
    CredentialKind,
    CredentialPut,
    LarkActionRequest,
    LarkOwnershipRequest,
    McpJobView,
    MCPSettingsPatch,
    MCPSnapshot,
    PolicyImport,
    RuntimeInstallRequest,
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
    return await service(request).self_test(body, server="ado")


@router.post("/api/mcp/figma/self-test", response_model=SelfTestResult)
async def figma_self_test(body: SelfTestRequest, request: Request):
    return await service(request).self_test(body, server="figma")


@router.post("/api/mcp/lark/ownership", response_model=MCPSnapshot)
async def confirm_lark_ownership(body: LarkOwnershipRequest, request: Request):
    return await service(request).confirm_lark_ownership(body)


@router.delete("/api/mcp/lark/ownership", response_model=MCPSnapshot)
async def revoke_lark_ownership(
    request: Request,
    revision: Annotated[int | None, Query(ge=0)] = None,
):
    return await service(request).revoke_lark_ownership(revision=revision)


@router.post("/api/mcp/lark/start", response_model=MCPSnapshot)
async def start_lark(
    request: Request,
    body: Annotated[LarkActionRequest | None, Body()] = None,
):
    return await service(request).start_lark(body)


@router.post("/api/mcp/lark/stop", response_model=MCPSnapshot)
async def stop_lark(
    request: Request,
    body: Annotated[LarkActionRequest | None, Body()] = None,
):
    return await service(request).stop_lark(body)


@router.post("/api/mcp/lark/login", response_model=MCPSnapshot)
async def login_lark(
    request: Request,
    body: Annotated[LarkActionRequest | None, Body()] = None,
):
    return await service(request).login_lark(body)


@router.post("/api/mcp/lark/login/cancel", response_model=MCPSnapshot)
async def cancel_lark_login(
    request: Request,
    body: Annotated[LarkActionRequest | None, Body()] = None,
):
    return await service(request).cancel_lark_login(body)


@router.post("/api/mcp/lark/logout", response_model=MCPSnapshot)
async def logout_lark(
    request: Request,
    body: Annotated[LarkActionRequest | None, Body()] = None,
):
    return await service(request).logout_lark(body)


@router.post("/api/mcp/runtime/install", response_model=McpJobView)
async def install_runtime(
    request: Request,
    body: Annotated[RuntimeInstallRequest | None, Body()] = None,
):
    return await service(request).install_runtime(body)


@router.post("/api/mcp/jobs/{job_id}/cancel", response_model=McpJobView)
async def cancel_job(
    job_id: str,
    request: Request,
    body: Annotated[LarkActionRequest | None, Body()] = None,
):
    return await service(request).cancel_job(
        job_id, request_id=body.request_id if body else None
    )
