from fastapi import APIRouter, Query, Request

from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.telegram_schemas import (
    ActivityResponse,
    BindCodeResponse,
    EnableRequest,
    GroupCreate,
    GroupPatch,
    MemberCreate,
    MemberPatch,
    RevisionRequest,
    TelegramErrorResponse,
    TelegramSettingsRequest,
    TelegramView,
    TokenRequest,
    WhitelistRequest,
)

router = APIRouter(
    prefix="/api/telegram",
    responses={code: {"model": TelegramErrorResponse} for code in (404, 409, 422, 502, 503)},
)


def service(request):
    return request.app.state.telegram_service


@router.get("", response_model=TelegramView)
async def view(request: Request):
    return await service(request).view()


@router.put("/token", response_model=MutationResponse)
async def token(body: TokenRequest, request: Request):
    return await service(request).token(body.revision, body.token.get_secret_value())


@router.post("/token/import-legacy", response_model=MutationResponse)
async def import_token(body: RevisionRequest, request: Request):
    return await service(request).token(body.revision, legacy=True)


@router.delete("/token", response_model=MutationResponse)
async def delete_token(request: Request, revision: int = Query(ge=0)):
    return await service(request).token(revision, delete=True)


@router.post("/control/enable", response_model=MutationResponse)
async def enable(body: EnableRequest, request: Request):
    return await service(request).enable(body)


@router.post("/control/disable", response_model=MutationResponse)
async def disable(body: RevisionRequest, request: Request):
    return await service(request).disable(body.revision)


@router.post("/control/retry", response_model=MutationResponse)
async def retry(body: RevisionRequest, request: Request):
    return await service(request).retry(body.revision)


@router.post("/owner/bind-code", response_model=BindCodeResponse)
async def bind_code(body: RevisionRequest, request: Request):
    return await service(request).bind_code(body.revision)


@router.delete("/owner", response_model=MutationResponse)
async def unbind(request: Request, revision: int = Query(ge=0)):
    return await service(request).unbind(revision)


@router.patch("/settings", response_model=MutationResponse)
async def settings(body: TelegramSettingsRequest, request: Request):
    return await service(request).settings_patch(body)


@router.post("/acl/groups", response_model=MutationResponse)
async def group_create(body: GroupCreate, request: Request):
    return await service(request).acl(
        "groups", body.revision, body.model_dump(exclude={"revision"})
    )


@router.patch("/acl/groups/{id}", response_model=MutationResponse)
async def group_patch(id: str, body: GroupPatch, request: Request):
    return await service(request).acl(
        "groups", body.revision, body.model_dump(exclude={"revision"}, exclude_unset=True), id
    )


@router.delete("/acl/groups/{id}", response_model=MutationResponse)
async def group_delete(id: str, request: Request, revision: int = Query(ge=0)):
    return await service(request).acl("groups", revision, ident=id, delete=True)


@router.post("/acl/members", response_model=MutationResponse)
async def member_create(body: MemberCreate, request: Request):
    return await service(request).acl(
        "members", body.revision, body.model_dump(exclude={"revision"})
    )


@router.patch("/acl/members/{id}", response_model=MutationResponse)
async def member_patch(id: str, body: MemberPatch, request: Request):
    return await service(request).acl(
        "members", body.revision, body.model_dump(exclude={"revision"}, exclude_unset=True), id
    )


@router.delete("/acl/members/{id}", response_model=MutationResponse)
async def member_delete(id: str, request: Request, revision: int = Query(ge=0)):
    return await service(request).acl("members", revision, ident=id, delete=True)


@router.put("/acl/legacy-whitelist", response_model=MutationResponse)
async def whitelist(body: WhitelistRequest, request: Request):
    return await service(request).whitelist(body)


@router.post("/test-message", response_model=MutationResponse)
async def test_message(body: RevisionRequest, request: Request):
    return await service(request).test_message(body.revision)


@router.get("/activity", response_model=ActivityResponse)
async def activity(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    tg = service(request)
    await tg.store.initialize()
    return dict(items=await tg.store.activity(limit))
