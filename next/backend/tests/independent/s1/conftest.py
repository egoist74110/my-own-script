import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings

LEGACY_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/legacy"


class TrackedCredentials(MemoryCredentials):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail_set_accounts = set()

    def get(self, key):
        self.calls.append(("get", key))
        return super().get(key)

    def set(self, key, value):
        self.calls.append(("set", key))
        if key in self.fail_set_accounts:
            self.fail_set_accounts.remove(key)
            raise RuntimeError("injected credential write failure")
        super().set(key, value)

    def delete(self, key):
        self.calls.append(("delete", key))
        return super().delete(key)


@dataclass
class S1Context:
    app: object
    client: httpx.AsyncClient
    new_credentials: TrackedCredentials
    old_credentials: TrackedCredentials
    source_dir: Path
    data_dir: Path
    requests: list

    async def close(self):
        await self.client.aclose()

    async def revision(self):
        return (await self.client.get("/api/settings")).json()["revision"]

    async def create_library(self, *, name="Main", base_url="https://ado.example.test", pat=None):
        body = {"revision": await self.revision(), "name": name, "base_url": base_url}
        if pat is not None:
            body["pat"] = pat
        response = await self.client.post("/api/ado/libraries", json=body)
        return response


@pytest.fixture
async def s1ctx(tmp_path):
    source_dir = tmp_path / "legacy"
    shutil.copytree(LEGACY_FIXTURES, source_dir)
    data_dir = tmp_path / "data"
    new_credentials = TrackedCredentials()
    old_credentials = TrackedCredentials()
    old_credentials.values["azuredevops_pat:lib:sample"] = "FAKE_S1_LEGACY_PAT_36a"
    requests = []

    def response_handler(request):
        requests.append(request)
        return httpx.Response(200, json={"value": [{"name": "Remote project"}]})

    app = create_app(
        Settings(
            token="isolated-s1-token",
            port=1234,
            data_dir=data_dir,
            legacy_config_dir=source_dir,
        ),
        credentials=new_credentials,
        legacy_credentials=old_credentials,
        ado_http=AdoHTTP(httpx.MockTransport(response_handler)),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer isolated-s1-token"},
    )
    context = S1Context(
        app, client, new_credentials, old_credentials, source_dir, data_dir, requests
    )
    try:
        yield context
    finally:
        await context.close()
