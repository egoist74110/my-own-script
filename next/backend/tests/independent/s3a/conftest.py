"""S3-A isolated ASGI clients; temporary config and in-memory credentials only."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import DynamicTask
from toolbox_backend.settings import Settings

TOKEN = "isolated-s3a-token"


@dataclass
class S3AContext:
    app: object
    client: httpx.AsyncClient
    data_dir: object

    async def close(self) -> None:
        await self.client.aclose()

    async def revision(self) -> int:
        response = await self.client.get("/api/settings")
        assert response.status_code == 200, response.text
        return response.json()["revision"]

    async def create_task(self, **fields):
        body = {"revision": await self.revision(), **fields}
        return await self.client.post("/api/tasks", json=body)

    async def seed_task(self, task_id: str, **fields) -> int:
        task = DynamicTask(id=task_id, **fields)
        revision = await self.revision()

        def add(config):
            config.tasks.items.append(task)

        await self.app.state.config_store.update(revision, add)
        return await self.revision()


@pytest.fixture
async def s3actx(tmp_path) -> AsyncIterator[S3AContext]:
    data_dir = tmp_path / "data"
    app = create_app(
        Settings(
            token=TOKEN,
            port=1234,
            data_dir=data_dir,
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    context = S3AContext(app=app, client=client, data_dir=data_dir)
    try:
        yield context
    finally:
        await context.close()
