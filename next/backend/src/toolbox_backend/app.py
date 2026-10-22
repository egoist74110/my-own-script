import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from toolbox_backend import __version__
from toolbox_backend.api import routes, ws
from toolbox_backend.api.middleware import BearerAuth, HostGuard
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.system import SystemService
from toolbox_backend.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        beat = asyncio.create_task(app.state.system.heartbeat_loop(settings.heartbeat_interval_s))
        try:
            yield
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)

    app = FastAPI(
        title="TOOLBOX backend",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo the offending input (can be huge or deeply nested).
        detail = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse({"detail": detail}, status_code=422)

    hub = EventHub(queue_size=settings.ws_queue_size)
    app.state.settings = settings
    app.state.hub = hub
    app.state.system = SystemService(hub)
    app.include_router(routes.router)
    app.include_router(ws.router)

    # add_middleware prepends: the last one added is outermost.
    # Resulting order: Host -> CORS -> Auth -> routes.
    app.add_middleware(BearerAuth, token=settings.token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(HostGuard, expected_host=settings.expected_host)
    return app
