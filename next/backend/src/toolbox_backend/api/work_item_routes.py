from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from toolbox_backend.api.ai_schemas import AnalysisRequest, PromptResponse, SessionView
from toolbox_backend.api.work_item_schemas import (
    ChildrenResponse,
    ColumnsResponse,
    CommentsResponse,
    UpdatesResponse,
    WorkItemDetail,
    WorkItemErrorResponse,
    WorkItemsResponse,
)
from toolbox_backend.domain.settings import Id
from toolbox_backend.services.work_items import COLUMNS

router = APIRouter(
    prefix="/api/work-items",
    responses={code: {"model": WorkItemErrorResponse} for code in (404, 409, 415, 422, 502, 503)},
)
WorkId = Annotated[int, Path(ge=1, le=2147483647)]
Column = Literal["新建", "待开发", "开发中", "测试", "已关闭"]


def service(request):
    return request.app.state.work_items_service


@router.get("/columns", response_model=ColumnsResponse)
async def columns():
    return ColumnsResponse(columns=COLUMNS)


@router.get("", response_model=WorkItemsResponse)
async def listing(request: Request, project_id: Id, column: Column = "开发中"):
    return await service(request).listing(project_id, column)


@router.get(
    "/media/{media_id}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def media(request: Request, media_id: str):
    body, mime, entry = await service(request).fetch_media(media_id)
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
    }
    if entry.kind == "attachment":
        headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(
            entry.name, safe=""
        )
    return Response(body, media_type=mime, headers=headers)


@router.get("/{id}", response_model=WorkItemDetail, response_model_exclude_none=False)
async def detail(request: Request, id: WorkId, project_id: Id):
    return await service(request).detail(project_id, id)


@router.get("/{id}/comments", response_model=CommentsResponse)
async def comments(request: Request, id: WorkId, project_id: Id):
    return await service(request).comments(project_id, id)


@router.get("/{id}/updates", response_model=UpdatesResponse)
async def updates(request: Request, id: WorkId, project_id: Id):
    return await service(request).updates(project_id, id)


@router.get("/{id}/children", response_model=ChildrenResponse)
async def children(request: Request, id: WorkId, project_id: Id):
    return await service(request).children(project_id, id)


@router.post("/{id}/ai-analysis", response_model=SessionView)
async def ai_analysis(request: Request, id: WorkId, body: AnalysisRequest):
    return await request.app.state.ai_service.analyze(service(request), id, body)


@router.get("/{id}/ai-prompt", response_model=PromptResponse)
async def ai_prompt(
    request: Request, id: WorkId, project_id: Id, cli: Literal["claude", "codex", "agy"]
):
    return await request.app.state.ai_service.prompt(service(request), id, project_id, cli)
