"""Independent S6-A config migration and analysis-source contract cases."""

import json

import httpx
import pytest

from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import Config
from toolbox_backend.settings import Settings


def _v3_config() -> dict:
    raw = Config().model_dump(mode="json", by_alias=True)
    raw.update(schema_version=3, revision=8, updated_at="2026-10-01T00:00:00+00:00")
    raw["imported"]["lark"] = {
        "app_id": "cli_a1b2c3",
        "domain": "https://open.feishu.cn",
        "tools": "im.message,contact.user",
        "language": "en",
        "oauth_port": 4321,
        "scope": "im:message",
    }
    raw["imported"]["figma"] = {"expiry_days": 90, "token_set_at": "2026-09-01T00:00:00Z"}
    return raw


async def test_v3_migration_normalizes_mcp_settings_and_preserves_import_snapshot(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = _v3_config()
    (data_dir / "config.json").write_text(json.dumps(original), encoding="utf-8")

    store = ConfigStore(data_dir)
    migrated = await store.initialize()
    assert migrated.schema_version == 6
    result = migrated.model_dump(mode="json", by_alias=True)
    assert result["imported"]["lark"] == original["imported"]["lark"]
    assert result["imported"]["figma"] == original["imported"]["figma"]
    assert result["mcp"]["lark"] == {
        **result["mcp"]["lark"],
        "app_id": "cli_a1b2c3",
        "domain": "https://open.feishu.cn",
        "tools": "im.message,contact.user",
        "language": "en",
        "port": 4321,
        "scope_hint": "im:message",
        "owner_confirmed_at": None,
        "autostart": False,
    }
    assert result["mcp"]["figma"]["expiry_days"] == 90
    assert result["mcp"]["figma"]["token_set_at"] == "2026-09-01T00:00:00Z"
    assert migrated.revision == 9

    first_bytes = store.path.read_bytes()
    second = await store.initialize()
    assert store.path.read_bytes() == first_bytes
    assert second.revision == 9


@pytest.mark.parametrize(
    "change",
    [
        {"port": 1023},
        {"port": 65536},
        {"domain": "http://open.larksuite.com"},
        {"domain": "https://evil.example"},
        {"tools": "im.message,has space"},
    ],
)
async def test_config_v4_rejects_unsafe_lark_values(tmp_path, change):
    raw = _v3_config()
    raw["schema_version"] = 4
    raw["mcp"] = {
        "ado": {
            "allow_create_work_item": False,
            "attachment_cache_mb": 500,
            "attachment_max_mb": 25,
            "query_max_items": 200,
        },
        "lark": {
            "app_id": "",
            "domain": "https://open.larksuite.com",
            "tools": "im.message",
            "language": "zh",
            "port": 3000,
            "scope_hint": "",
            "owner_confirmed_at": None,
            "autostart": False,
            "login": {"logged_in_at": None, "scope": None},
        },
        "figma": {
            "token_set_at": None,
            "expiry_days": 90,
            "max_concurrency": 1,
            "min_interval_ms": 350,
            "max_retry": 4,
        },
        "runtime": {
            "node": {"source": "none", "path": None, "version": None},
            "packages": {
                "@larksuiteoapi/lark-mcp": "0.5.1",
                "figma-developer-mcp": "0.13.2",
            },
        },
    }
    raw["mcp"]["lark"].update(change)

    with pytest.raises(ValueError):
        Config.model_validate(raw)


@pytest.fixture
async def ai_settings_client(tmp_path):
    app = create_app(
        Settings(
            token="s6a-isolated-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer s6a-isolated-token"},
    ) as client:
        yield client


async def test_analysis_source_defaults_to_legacy_and_can_switch_back(ai_settings_client):
    client = ai_settings_client
    initial = await client.get("/api/ai")
    assert initial.status_code == 200, initial.text
    assert initial.json()["analysis"]["mcp_source"] == "legacy"

    needs_confirmation = await client.patch(
        "/api/ai/settings",
        json={"revision": initial.json()["revision"], "analysis": {"mcp_source": "toolbox"}},
    )
    assert needs_confirmation.status_code == 422
    assert (await client.get("/api/ai")).json()["analysis"]["mcp_source"] == "legacy"

    switched = await client.patch(
        "/api/ai/settings",
        json={
            "revision": initial.json()["revision"],
            "analysis": {"mcp_source": "toolbox"},
            "ack_cli_registered": True,
        },
    )
    assert switched.status_code == 200, switched.text
    toolbox = await client.get("/api/ai")
    assert toolbox.json()["analysis"]["mcp_source"] == "toolbox"

    reverted = await client.patch(
        "/api/ai/settings",
        json={"revision": toolbox.json()["revision"], "analysis": {"mcp_source": "legacy"}},
    )
    assert reverted.status_code == 200, reverted.text
    assert (await client.get("/api/ai")).json()["analysis"]["mcp_source"] == "legacy"


async def test_analysis_source_rejects_unknown_choice_without_mutating(ai_settings_client):
    client = ai_settings_client
    initial = await client.get("/api/ai")
    response = await client.patch(
        "/api/ai/settings",
        json={"revision": initial.json()["revision"], "analysis": {"mcp_source": "remote"}},
    )
    assert response.status_code == 422
    after = await client.get("/api/ai")
    assert after.json()["analysis"]["mcp_source"] == "legacy"
    assert after.json()["revision"] == initial.json()["revision"]


@pytest.fixture
async def mcp_client(tmp_path):
    data_dir = tmp_path / "data"
    credentials = MemoryCredentials()
    app = create_app(
        Settings(
            token="s6a-isolated-token",
            port=1234,
            data_dir=data_dir,
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=credentials,
        legacy_credentials=MemoryCredentials(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer s6a-isolated-token"},
    ) as client:
        yield client, credentials, data_dir


async def test_figma_credential_write_never_echoes_or_persists_secret(mcp_client, caplog):
    client, credentials, data_dir = mcp_client
    secret = "INDEPENDENT_S6A_FIGMA_SECRET_80a4c5"
    before = await client.get("/api/mcp")
    assert before.status_code == 200, before.text

    saved = await client.put(
        "/api/mcp/credentials/figma_token",
        json={"revision": before.json()["revision"], "value": secret, "expiry_days": 90},
    )
    assert saved.status_code == 200, saved.text
    assert secret not in saved.text

    status = await client.get("/api/mcp")
    assert status.status_code == 200, status.text
    assert secret not in status.text
    assert credentials.values["figma_token"] == secret
    assert secret not in (data_dir / "config.json").read_text(encoding="utf-8")
    assert secret not in caplog.text
