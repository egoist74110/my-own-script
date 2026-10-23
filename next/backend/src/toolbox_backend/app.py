import asyncio
import contextlib
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from toolbox_backend import __version__
from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.ado_tasks import AdoTaskExecutor
from toolbox_backend.adapters.config_store import ConfigStore, MigrationStep
from toolbox_backend.adapters.credentials import CredentialStore, LegacyCredentialSource
from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.adapters.task_git import GitAdapter
from toolbox_backend.adapters.telegram_store import TelegramStore
from toolbox_backend.api import (
    routes,
    settings_routes,
    task_routes,
    telegram_routes,
    work_item_routes,
    ws,
)
from toolbox_backend.api.middleware import BearerAuth, BodyLimit, HostGuard
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.models import SettingsChangedData, SettingsChangedEvent
from toolbox_backend.logging_setup import register_secret
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.runs import RunService
from toolbox_backend.services.settings import SettingsService
from toolbox_backend.services.system import SystemService
from toolbox_backend.services.tasks import TasksService
from toolbox_backend.services.telegram import TelegramService
from toolbox_backend.services.work_items import WorkItemsService
from toolbox_backend.settings import Settings


class UnavailableCredentials:
    def get(self, account):
        raise RuntimeError("credential adapter was not injected")

    def set(self, account, value):
        raise RuntimeError("credential adapter was not injected")

    def delete(self, account):
        raise RuntimeError("credential adapter was not injected")


def create_app(
    settings: Settings,
    *,
    credentials: CredentialStore | None = None,
    legacy_credentials: LegacyCredentialSource | None = None,
    ado_http: AdoHTTP | None = None,
    migrations: dict[int, MigrationStep] | None = None,
    ado_read: AdoRead | None = None,
    task_executor=None,
    task_git: GitAdapter | None = None,
    telegram_transport=None,
) -> FastAPI:
    register_secret(settings.token)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Read startup state without creating a directory. Interrupted imports keep the
        # credential intent list so retry/decline can reconcile a crash after set().
        try:
            config = await app.state.config_store.initialize()
            if config.import_.state == "in_progress":

                def interrupted(c):
                    c.import_.state = "failed"
                    c.import_.error = "上次导入被中断；可重试或放弃"

                await app.state.config_store.update(config.revision, interrupted)
        except SettingsError:
            pass  # Exposed via GET /api/settings; never reset corrupt/unsupported files.
        await app.state.run_service.initialize()
        await app.state.telegram_service.initialize()
        beat = asyncio.create_task(app.state.system.heartbeat_loop(settings.heartbeat_interval_s))
        try:
            yield
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)
            try:
                await app.state.run_service.close()
            finally:
                await app.state.telegram_service.close()

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
        return JSONResponse(
            {"detail": {"code": "validation_error", "message": "请求校验失败"}},
            status_code=422,
        )

    @app.exception_handler(SettingsError)
    async def _settings_error(_: Request, exc: SettingsError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail()}, status_code=exc.status)

    hub = EventHub(queue_size=settings.ws_queue_size)
    app.state.settings = settings
    app.state.hub = hub
    app.state.system = SystemService(hub)
    store = ConfigStore(
        settings.data_dir,
        lambda revision: hub.publish(
            SettingsChangedEvent,
            SettingsChangedData(revision=revision),
        ),
        migrations=migrations,
    )
    app.state.config_store = store
    app.state.settings_service = SettingsService(
        store,
        credentials or UnavailableCredentials(),
        legacy_credentials or UnavailableCredentials(),
        settings.legacy_config_dir,
        ado_http or AdoHTTP(),
    )
    app.state.work_items_service = WorkItemsService(
        app.state.settings_service, ado_read or AdoRead()
    )
    app.state.run_store = RunStore(settings.data_dir, hub.publish_run)
    app.state.tasks_service = TasksService(
        app.state.settings_service, app.state.run_store, task_git or GitAdapter(settings.data_dir)
    )
    store.before_commit = app.state.tasks_service.guard
    app.state.settings_service.guard_resource = app.state.tasks_service.guard_resource
    app.state.run_service = RunService(
        app.state.tasks_service,
        app.state.run_store,
        task_executor
        if task_executor is not None
        else AdoTaskExecutor(app.state.work_items_service, app.state.tasks_service.git),
    )
    app.state.telegram_store = TelegramStore(settings.data_dir)
    fake = None
    if os.environ.get("TOOLBOX_DEV_FAKE_TELEGRAM") is not None:
        from toolbox_backend.adapters.credentials import MemoryCredentials
        from toolbox_backend.adapters.fake_telegram import FakeTelegram

        if (
            os.environ.get("TOOLBOX_DEV_FAKE_TELEGRAM") != "1"
            or not settings.dev
            or os.environ.get("TOOLBOX_CREDENTIALS") != "memory"
            or not isinstance(credentials, MemoryCredentials)
        ):
            raise ValueError("TOOLBOX_DEV_FAKE_TELEGRAM requires --dev and memory credentials")
        fake = FakeTelegram()
        telegram_transport = fake.transport
        from toolbox_backend.api.settings_schemas import MutationResponse
        from toolbox_backend.api.telegram_schemas import (
            FakeSentResponse,
            InjectRequest,
        )

        @app.post("/api/dev/telegram/inject", response_model=MutationResponse)
        async def inject(body: InjectRequest):
            fake.inject(body.update)
            config = await store.read()
            return MutationResponse(revision=config.revision)

        @app.get("/api/dev/telegram/sent", response_model=FakeSentResponse)
        async def sent():
            return {"items": fake.sent}

    app.state.telegram_service = TelegramService(
        app.state.settings_service,
        app.state.telegram_store,
        app.state.run_service,
        hub,
        transport=telegram_transport,
        work_items=app.state.work_items_service,
    )
    prior_event = app.state.run_store.on_event

    def run_event(event):
        prior_event(event)
        app.state.telegram_service.on_run_event(event)

    app.state.run_store.on_event = run_event
    app.include_router(telegram_routes.router)
    app.include_router(task_routes.router)
    app.include_router(work_item_routes.router)
    app.include_router(routes.router)
    app.include_router(ws.router)
    app.include_router(settings_routes.router)

    # add_middleware prepends: the last one added is outermost.
    # Resulting order: Host -> CORS -> Auth -> BodyLimit -> routes.
    app.add_middleware(BodyLimit, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(BearerAuth, token=settings.token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(HostGuard, expected_host=settings.expected_host)
    return app
