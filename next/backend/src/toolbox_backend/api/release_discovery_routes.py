"""发布配置向导的只读发现接口。"""

from fastapi import APIRouter, Query, Request

from toolbox_backend.api.release_discovery_schemas import (
    DiscoverBranchesResponse,
    DiscoverQueuesResponse,
    DiscoverRepoInput,
    DiscoverRepoResponse,
    DiscoverTargetsResponse,
)
from toolbox_backend.services.release_discovery import ReleaseDiscoveryService

router = APIRouter(prefix="/discover")


def service(request):
    return ReleaseDiscoveryService(request.app.state.work_items_service)


@router.post("/repo", response_model=DiscoverRepoResponse)
async def repo(body: DiscoverRepoInput, request: Request):
    return await service(request).repo(body.local_repo_path)


@router.get("/branches", response_model=DiscoverBranchesResponse)
async def branches(
    request: Request, project_id: str = Query(min_length=1), repo_id: str = Query(min_length=1)
):
    return await service(request).branches(project_id, repo_id)


@router.get("/targets", response_model=DiscoverTargetsResponse)
async def targets(
    request: Request, project_id: str = Query(min_length=1), repo_id: str = Query(min_length=1)
):
    return await service(request).targets(project_id, repo_id)


@router.get("/queues", response_model=DiscoverQueuesResponse)
async def queues(request: Request, project_id: str = Query(min_length=1)):
    return await service(request).queues(project_id)
