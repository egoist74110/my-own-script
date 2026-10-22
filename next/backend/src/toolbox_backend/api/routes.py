from fastapi import APIRouter, Request

from toolbox_backend import __version__
from toolbox_backend.api.schemas import AlertRequest, HealthResponse
from toolbox_backend.domain.models import AlertState
from toolbox_backend.services.system import SystemService

router = APIRouter()


def _system(request: Request) -> SystemService:
    return request.app.state.system


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    system = _system(request)
    return HealthResponse(
        status="ok",
        version=__version__,
        pid=system.pid,
        uptime_s=system.uptime_s,
        alert=system.alert.active,
    )


@router.post("/api/system/alert", response_model=AlertState)
async def set_alert(body: AlertRequest, request: Request) -> AlertState:
    return _system(request).set_alert(body.active, body.reason)
