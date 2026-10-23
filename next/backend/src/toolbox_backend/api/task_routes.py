from typing import Literal

from fastapi import APIRouter, Query, Request, Response

from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.task_schemas import (
    PlanResponse,
    PreflightRequest,
    RunEventsResponse,
    RunListResponse,
    RunResponse,
    RunStatus,
    StartRequest,
    StartResponse,
    TaskCreate,
    TaskListResponse,
    TaskOrder,
    TaskPatch,
    TaskResponse,
)

router = APIRouter()


@router.get("/api/tasks", response_model=TaskListResponse)
async def tasks(request: Request) -> dict:
    return await request.app.state.tasks_service.get()


@router.post("/api/tasks", response_model=MutationResponse)
async def create_task(body: TaskCreate, request: Request):
    return await request.app.state.tasks_service.save(body)


@router.put("/api/tasks/order", response_model=MutationResponse)
async def task_order(body: TaskOrder, request: Request):
    return await request.app.state.tasks_service.order(body)


@router.get("/api/tasks/{task_id}", response_model=TaskResponse)
async def task(task_id: str, request: Request) -> dict:
    return await request.app.state.tasks_service.get(task_id)


@router.patch("/api/tasks/{task_id}", response_model=MutationResponse)
async def patch_task(task_id: str, body: TaskPatch, request: Request):
    return await request.app.state.tasks_service.save(body, task_id)


@router.delete("/api/tasks/{task_id}", response_model=MutationResponse)
async def delete_task(
    task_id: str, request: Request, revision: int = Query(ge=0), detach_acl: bool = False
):
    return await request.app.state.tasks_service.delete(task_id, revision, detach_acl)


@router.post("/api/tasks/{task_id}/preflight", response_model=PlanResponse)
async def preflight(task_id: str, body: PreflightRequest, request: Request) -> dict:
    return await request.app.state.run_service.preflight(task_id, body)


@router.post("/api/tasks/{task_id}/runs", status_code=202, response_model=StartResponse)
async def start(task_id: str, body: StartRequest, request: Request) -> dict:
    return await request.app.state.run_service.start(task_id, body)


@router.get("/api/runs", response_model=RunListResponse)
async def runs(
    request: Request,
    task_id: str | None = None,
    status: RunStatus | None = None,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
    order: Literal["asc", "desc"] = "asc",
) -> dict:
    return await request.app.state.run_store.list(
        task_id=task_id, status=status, cursor=cursor, limit=limit, order=order
    )


@router.get("/api/runs/{run_id}", response_model=RunResponse)
async def run(run_id: str, request: Request) -> dict:
    return await request.app.state.run_store.get(run_id)


@router.post("/api/runs/{run_id}/cancel", status_code=202, response_model=RunResponse)
async def cancel(run_id: str, request: Request, response: Response) -> dict:
    from toolbox_backend.adapters.run_store import TERMINAL

    before = await request.app.state.run_store.get(run_id)
    result = await request.app.state.run_service.cancel(run_id)
    if before["status"] in TERMINAL:
        response.status_code = 200
    return result


@router.get("/api/runs/{run_id}/events", response_model=RunEventsResponse)
async def events(
    run_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    return await request.app.state.run_store.events(run_id, after_seq, limit)


@router.post("/api/runs/{run_id}/reconcile", status_code=202, response_model=RunResponse)
async def reconcile(run_id: str, request: Request) -> dict:
    if await request.body():
        from toolbox_backend.domain.errors import SettingsError

        raise SettingsError("validation_error", "重新核实不接受请求体或远端标识", 422)
    return await request.app.state.run_service.reconcile(run_id)
