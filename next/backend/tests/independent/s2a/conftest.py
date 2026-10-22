"""Isolated S2-A API clients; all paths and credentials stay test-owned."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings


@dataclass
class S2Context:
    app: object
    client: httpx.AsyncClient
    requests: list[httpx.Request]

    async def close(self) -> None:
        await self.client.aclose()

    async def revision(self) -> int:
        return (await self.client.get("/api/settings")).json()["revision"]

    def mock_ado(self, handler) -> None:
        self.app.state.work_items_service.http = AdoRead(httpx.MockTransport(handler))

    async def create_project(
        self,
        *,
        base_url="https://ado.example/root",
        collection="Collection One",
        project="Project & X",
        pat="FAKE_S2A_ADO_PAT_943",
    ) -> str:
        library = await self.client.post(
            "/api/ado/libraries",
            json={
                "revision": await self.revision(),
                "name": "S2 library",
                "base_url": base_url,
                "pat": pat,
            },
        )
        assert library.status_code == 200, library.text
        created = await self.client.post(
            "/api/ado/projects",
            json={
                "revision": await self.revision(),
                "library_id": library.json()["id"],
                "collection": collection,
                "project": project,
            },
        )
        assert created.status_code == 200, created.text
        return created.json()["id"]


@pytest.fixture
async def s2ctx(tmp_path) -> AsyncIterator[S2Context]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"value": []})

    app = create_app(
        Settings(
            token="isolated-s2-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
        ado_read=AdoRead(httpx.MockTransport(respond)),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer isolated-s2-token"},
    )
    context = S2Context(app=app, client=client, requests=requests)
    try:
        yield context
    finally:
        await context.close()
