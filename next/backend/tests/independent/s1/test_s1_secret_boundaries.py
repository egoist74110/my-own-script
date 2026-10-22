import json

import httpx
import pytest

from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings

PAT = "INDEPENDENT_FAKE_PAT_S1_7d31a9"


class RecordingCredentials(MemoryCredentials):
    def __init__(self, *, fail_set=False):
        super().__init__()
        self.fail_set = fail_set

    def set(self, account, value):
        if self.fail_set:
            raise RuntimeError("keychain failure: " + PAT)
        super().set(account, value)


@pytest.fixture
async def api(tmp_path):
    data_dir = tmp_path / "data"
    old_dir = tmp_path / "legacy"
    old_dir.mkdir()
    credentials = RecordingCredentials()
    app = create_app(
        Settings(
            token="isolated-test-token",
            port=1234,
            data_dir=data_dir,
            legacy_config_dir=old_dir,
        ),
        credentials=credentials,
        legacy_credentials=MemoryCredentials(),
        ado_http=AdoHTTP(httpx.MockTransport(lambda _: httpx.Response(200, json={"value": []}))),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer isolated-test-token"},
    ) as client:
        yield app, client, credentials, data_dir


async def test_pat_is_absent_from_validation_success_and_persisted_config(api):
    app, client, credentials, data_dir = api
    invalid = await client.post(
        "/api/ado/libraries",
        json={"revision": 0, "name": "n", "base_url": "file:///tmp", "pat": PAT},
    )
    assert invalid.status_code == 422
    assert PAT not in invalid.text

    created = await client.post(
        "/api/ado/libraries",
        json={
            "revision": 0,
            "name": "Primary",
            "base_url": "https://ado.example.test",
            "pat": PAT,
        },
    )
    assert created.status_code == 200, created.text
    assert PAT not in created.text
    library_id = created.json()["id"]
    listed = await client.get("/api/credentials")
    assert listed.status_code == 200
    assert PAT not in listed.text
    assert credentials.values == {f"ado_pat:{library_id}": PAT}

    raw_config = (data_dir / "config.json").read_text()
    assert PAT not in raw_config
    parsed = json.loads(raw_config)
    assert parsed["credentials"][f"ado_pat:{library_id}"]["ref"] == library_id
    assert app.state.config_store.path == data_dir / "config.json"


async def test_credential_backend_exception_is_not_returned_or_logged(api, caplog):
    _, client, credentials, data_dir = api
    created = await client.post(
        "/api/ado/libraries",
        json={
            "revision": 0,
            "name": "Primary",
            "base_url": "https://ado.example.test",
        },
    )
    assert created.status_code == 200, created.text
    credentials.fail_set = True
    response = await client.put(
        f"/api/ado/libraries/{created.json()['id']}/pat",
        json={"revision": 1, "pat": PAT},
    )
    assert response.status_code == 502
    assert PAT not in response.text
    assert PAT not in caplog.text
    assert PAT not in (data_dir / "config.json").read_text()
