"""发布配置与其运行命令使用同一配置 revision 乐观锁。"""

from fastapi import APIRouter, Query, Request

from toolbox_backend.api.release_discovery_routes import router as discovery_router
from toolbox_backend.api.release_schemas import (
    CommandCreate,
    CommandListResponse,
    CommandPatch,
    CommandResponse,
    ReleaseCreate,
    ReleaseListResponse,
    ReleasePatch,
    ReleaseResponse,
)
from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.task_schemas import TaskOrder
from toolbox_backend.services.releases import ReleasesService

router = APIRouter(prefix="/api/release-configs")
router.include_router(discovery_router)


def service(request):
    return ReleasesService(request.app.state.tasks_service)


@router.get("", response_model=ReleaseListResponse)
async def configs(request: Request):
    return await service(request).get()


@router.post("", response_model=MutationResponse)
async def create(body: ReleaseCreate, request: Request):
    return await service(request).save(body)


@router.put("/order", response_model=MutationResponse)
async def order(body: TaskOrder, request: Request):
    return await service(request).order(body)


@router.get("/{config_id}", response_model=ReleaseResponse)
async def config(config_id: str, request: Request):
    return await service(request).get(config_id)


@router.patch("/{config_id}", response_model=MutationResponse)
async def patch(config_id: str, body: ReleasePatch, request: Request):
    return await service(request).save(body, config_id)


@router.delete("/{config_id}", response_model=MutationResponse)
async def delete(
    config_id: str, request: Request, revision: int = Query(ge=0), detach_acl: bool = False
):
    return await service(request).delete(config_id, revision, detach_acl)


@router.get("/{config_id}/commands", response_model=CommandListResponse)
async def commands(config_id: str, request: Request):
    return await service(request).commands(config_id)


@router.post("/{config_id}/commands", response_model=MutationResponse)
async def create_command(config_id: str, body: CommandCreate, request: Request):
    return await service(request).save_command(config_id, body)


@router.put("/{config_id}/commands/order", response_model=MutationResponse)
async def command_order(config_id: str, body: TaskOrder, request: Request):
    return await service(request).order(body, config_id)


@router.get("/{config_id}/commands/{command_id}", response_model=CommandResponse)
async def command(config_id: str, command_id: str, request: Request):
    return await service(request).commands(config_id, command_id)


@router.patch("/{config_id}/commands/{command_id}", response_model=MutationResponse)
async def patch_command(config_id: str, command_id: str, body: CommandPatch, request: Request):
    return await service(request).save_command(config_id, body, command_id)


@router.delete("/{config_id}/commands/{command_id}", response_model=MutationResponse)
async def delete_command(
    config_id: str,
    command_id: str,
    request: Request,
    revision: int = Query(ge=0),
    detach_acl: bool = False,
):
    return await service(request).delete(config_id, revision, detach_acl, command_id)
