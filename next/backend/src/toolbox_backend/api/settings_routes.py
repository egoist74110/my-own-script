from typing import Annotated

from fastapi import APIRouter, Query, Request

from toolbox_backend.adapters.ado_http import ConnectionResult, RemoteProject
from toolbox_backend.api.settings_schemas import (
    ActiveRequest,
    AdoRequestErrorResponse,
    AdoResponse,
    CredentialStatus,
    ImportPreview,
    ImportRequest,
    LibraryCreate,
    LibraryPatch,
    MutationResponse,
    NoCredentialErrorResponse,
    PatRequest,
    ProjectCreate,
    ProjectPatch,
    SettingsResponse,
    TestRequest,
    ValidationErrorResponse,
)
from toolbox_backend.domain.settings import Segment
from toolbox_backend.services.settings import SettingsService

router = APIRouter()
Revision = Annotated[int, Query(ge=0)]


def service(request: Request) -> SettingsService:
    return request.app.state.settings_service


@router.get("/api/settings", response_model=SettingsResponse)
async def settings(request: Request):
    return await service(request).settings()


@router.post("/api/settings/import/preview", response_model=ImportPreview)
async def preview(request: Request):
    return await service(request).preview()


@router.post("/api/settings/import/execute", response_model=MutationResponse)
async def execute(body: ImportRequest, request: Request):
    return await service(request).execute(body.fingerprint)


@router.post("/api/settings/import/decline", response_model=MutationResponse)
async def decline(request: Request):
    return await service(request).decline()


@router.get("/api/ado", response_model=AdoResponse)
async def ado(request: Request):
    return await service(request).ado()


@router.post("/api/ado/libraries", response_model=MutationResponse)
async def create_library(body: LibraryCreate, request: Request):
    return await service(request).create_library(body)


@router.patch("/api/ado/libraries/{id}", response_model=MutationResponse)
async def patch_library(id: str, body: LibraryPatch, request: Request):
    return await service(request).patch_library(id, body)


@router.delete("/api/ado/libraries/{id}", response_model=MutationResponse)
async def delete_library(id: str, revision: Revision, request: Request):
    return await service(request).delete_library(id, revision)


@router.put("/api/ado/libraries/{id}/pat", response_model=MutationResponse)
async def put_pat(id: str, body: PatRequest, request: Request):
    return await service(request).put_pat(id, body.revision, body.pat.get_secret_value())


@router.delete("/api/ado/libraries/{id}/pat", response_model=MutationResponse)
async def delete_pat(id: str, revision: Revision, request: Request):
    return await service(request).delete_pat(id, revision)


@router.post("/api/ado/libraries/{id}/test", response_model=ConnectionResult)
async def test_connection(id: str, body: TestRequest, request: Request):
    return await service(request).connection(id, body)


@router.get(
    "/api/ado/libraries/{id}/remote-projects",
    response_model=list[RemoteProject],
    responses={
        409: {"model": NoCredentialErrorResponse},
        502: {"model": AdoRequestErrorResponse},
        422: {"model": ValidationErrorResponse},
    },
)
async def remote_projects(id: str, collection: Segment, request: Request):
    return await service(request).connection(id, TestRequest(collection=collection), listing=True)


@router.post("/api/ado/projects", response_model=MutationResponse)
async def create_project(body: ProjectCreate, request: Request):
    return await service(request).project(body)


@router.patch("/api/ado/projects/{id}", response_model=MutationResponse)
async def patch_project(id: str, body: ProjectPatch, request: Request):
    return await service(request).project(body, id)


@router.delete("/api/ado/projects/{id}", response_model=MutationResponse)
async def delete_project(id: str, revision: Revision, request: Request):
    return await service(request).delete_project(id, revision)


@router.put("/api/ado/active", response_model=MutationResponse)
async def active(body: ActiveRequest, request: Request):
    return await service(request).active(body)


@router.get("/api/credentials", response_model=list[CredentialStatus])
async def credentials(request: Request):
    return await service(request).statuses()


@router.delete("/api/credentials/{account}", response_model=MutationResponse)
async def delete_credential(account: str, revision: Revision, request: Request):
    return await service(request).delete_orphan(account, revision)
