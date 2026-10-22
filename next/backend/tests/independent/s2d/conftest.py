"""Isolated S2-D service fixture: in-memory credentials and mocked ADO only."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings


@dataclass
class S2DContext:
    app: object
    client: httpx.AsyncClient
    requests: list[httpx.Request]

    async def close(self) -> None:
        await self.client.aclose()

    async def revision(self) -> int:
        return (await self.client.get("/api/settings")).json()["revision"]

    def mock_ado(self, handler) -> None:
        self.app.state.work_items_service.http = AdoRead(httpx.MockTransport(handler))

    async def create_project(self) -> str:
        library = await self.client.post(
            "/api/ado/libraries",
            json={"revision": await self.revision(), "name": "S2-D", "base_url": "https://ado.example/root", "pat": "FAKE_S2D_PAT_72"},
        )
        assert library.status_code == 200, library.text
        created = await self.client.post(
            "/api/ado/projects",
            json={
                "revision": await self.revision(),
                "library_id": library.json()["id"],
                "collection": "Collection One",
                "project": "Project 中文",
            },
        )
        assert created.status_code == 200, created.text
        return created.json()["id"]


@pytest.fixture
async def s2dctx(tmp_path) -> AsyncIterator[S2DContext]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"value": []})

    app = create_app(
        Settings(
            token="isolated-s2d-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
        ado_read=AdoRead(httpx.MockTransport(respond)),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer isolated-s2d-token"},
    )
    context = S2DContext(app=app, client=client, requests=requests)
    try:
        yield context
    finally:
        await context.close()
