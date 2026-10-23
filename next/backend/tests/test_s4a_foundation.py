import json

import httpx

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import Config
from toolbox_backend.settings import Settings


async def test_v1_migration_is_disabled_durable_and_idempotent(tmp_path):
    raw = Config().model_dump(by_alias=True)
    raw.update(schema_version=1, revision=4)
    raw.pop("telegram", None)
    raw["imported"]["telegram"] = {
        "control_enabled": True,
        "chat_id": "123",
        "future": {"x": 1},
        "acl_members": [{"group_id": "old", "username": "@Example", "label": ""}],
    }
    path = tmp_path / "config.json"
    original = json.dumps(raw)
    path.write_text(original)
    store = ConfigStore(tmp_path)
    migrated = await store.initialize()
    assert migrated.schema_version == 3
    assert not migrated.telegram.control.enabled
    assert migrated.telegram.owner.chat_id == "123"
    assert "telegram" not in migrated.imported.model_dump()
    assert migrated.telegram.model_extra["future"] == {"x": 1}
    backups = list((tmp_path / "migrations").glob("config-v1-*.json"))
    assert len(backups) == 1 and backups[0].read_text() == original
    before = path.read_bytes()
    await store.initialize()
    assert path.read_bytes() == before


async def test_telegram_token_and_dev_routes_are_guarded(tmp_path):
    app = create_app(
        Settings(token="local-test-auth", port=123, data_dir=tmp_path),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:123"
        ) as client:
            assert (await client.get("/api/telegram")).status_code == 401
            client.headers["Authorization"] = "Bearer local-test-auth"
            view = await client.get("/api/telegram")
            assert view.status_code == 200
            assert view.json()["poller"]["state"] == "disabled"
            assert (await client.get("/api/dev/telegram/sent")).status_code == 404
            response = await client.put(
                "/api/telegram/token",
                json={
                    "revision": 0,
                    "token": "123456:" + "A" * 32,
                },
            )
            assert response.status_code == 200
            assert "A" * 32 not in response.text
