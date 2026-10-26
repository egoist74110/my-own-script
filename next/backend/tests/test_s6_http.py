import httpx

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings


async def test_mcp_settings_revision_and_write_only_credential(tmp_path):
    creds = MemoryCredentials()
    app = create_app(
        Settings(token="http-test", port=12345, data_dir=tmp_path),
        credentials=creds,
        legacy_credentials=MemoryCredentials(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:12345",
        headers={"Authorization": "Bearer http-test"},
    ) as c:
        r = await c.get("/api/mcp")
        assert r.status_code == 200
        assert r.json()["runtime"]["packages"]["figma-developer-mcp"] == "0.13.2"
        r = await c.put(
            "/api/mcp/credentials/figma_token",
            json={"revision": 0, "value": "figma_fake_0123456789", "expiry_days": 30},
        )
        assert r.status_code == 200
        assert creds.get("figma_token") == "figma_fake_0123456789"
        r = await c.get("/api/mcp")
        assert "figma_fake_" not in r.text
        assert (
            await c.patch("/api/mcp/settings", json={"revision": 0, "ado": {}})
        ).status_code == 409
        assert (await c.get("/api/mcp/credentials/figma_token")).status_code == 405


async def test_new_kinds_are_valid_on_existing_credential_status_route(tmp_path):
    creds = MemoryCredentials()
    app = create_app(
        Settings(token="status-token", port=12345, data_dir=tmp_path),
        credentials=creds,
        legacy_credentials=MemoryCredentials(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:12345",
        headers={"Authorization": "Bearer status-token"},
    ) as c:
        assert (
            await c.put(
                "/api/mcp/credentials/figma_token",
                json={"revision": 0, "value": "s6-fake-figma-credential"},
            )
        ).status_code == 200
        r = await c.get("/api/credentials")
        assert r.status_code == 200
        assert r.json()[0]["kind"] == "figma_token"


async def test_import_legacy_and_client_snippets_are_read_only(tmp_path):
    import json

    creds, legacy = MemoryCredentials(), MemoryCredentials()
    legacy.set("lark_app_secret:cli_123", "legacy-fake-app-secret")
    legacy.set("figma_token", "legacy-fake-figma-token")
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    source = legacy_dir / "lark_login_state.json"
    raw = json.dumps(
        {
            "app_id": "cli_123",
            "logged_in_at": "2026-10-01",
            "scope": "docx:document",
            "access_token": "do-not-import-token",
        }
    )
    source.write_text(raw)
    app = create_app(
        Settings(
            token="import-test",
            port=12345,
            data_dir=tmp_path / "data",
            legacy_config_dir=legacy_dir,
        ),
        credentials=creds,
        legacy_credentials=legacy,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:12345",
        headers={"Authorization": "Bearer import-test"},
    ) as c:
        r = await c.post(
            "/api/mcp/credentials/import-legacy",
            json={"revision": 0, "kinds": ["lark_app_secret", "figma_token"], "app_id": "cli_123"},
        )
        assert r.status_code == 200
        assert legacy.values == creds.values
        assert source.read_text() == raw
        config = await app.state.config_store.read()
        assert config.mcp.lark.login.logged_in_at == "2026-10-01"
        assert "do-not-import-token" not in config.model_dump_json()
        for server, name in [("ado", "toolbox_ado"), ("figma", "toolbox_figma"), ("lark", "lark")]:
            for cli in ["claude", "codex", "agy"]:
                r = await c.get("/api/mcp/client-config", params={"server": server, "cli": cli})
                assert r.status_code == 200
                assert r.json()["name"] == name
                assert "legacy-fake" not in r.text
        assert (
            await c.delete("/api/mcp/credentials/figma_token", params={"revision": 2})
        ).status_code == 200
        assert creds.get("figma_token") is None


async def test_credentials_rollback_if_config_write_fails(tmp_path, monkeypatch):
    import pytest

    from toolbox_backend.domain.errors import SettingsError

    creds = MemoryCredentials()
    creds.set("figma_token", "existing-fake-token")
    app = create_app(
        Settings(token="rollback-test", port=12345, data_dir=tmp_path), credentials=creds
    )

    def fail(_):
        raise SettingsError("store_unavailable", "write failed", 503)

    monkeypatch.setattr(app.state.config_store, "_write", fail)
    with pytest.raises(SettingsError):
        await app.state.mcp_service.credential("figma_token", 0, value="replacement-fake-token")
    assert creds.get("figma_token") == "existing-fake-token"


async def test_mcp_routes_keep_global_security_boundaries(tmp_path):
    app = create_app(
        Settings(token="security-token", port=12345, data_dir=tmp_path),
        credentials=MemoryCredentials(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:12345"
    ) as c:
        assert (await c.get("/api/mcp")).status_code == 401
        assert (
            await c.get(
                "/api/mcp",
                headers={"Host": "attacker.invalid", "Authorization": "Bearer security-token"},
            )
        ).status_code == 400
        headers = {"Authorization": "Bearer security-token"}
        response = await c.patch(
            "/api/mcp/settings", headers=headers, json={"revision": 0, "lark": {"port": 80}}
        )
        assert (
            response.status_code == 422 and response.json()["detail"]["code"] == "validation_error"
        )
        response = await c.get("/api/mcp", headers={**headers, "Origin": "https://evil.invalid"})
        assert "access-control-allow-origin" not in response.headers
        response = await c.patch(
            "/api/mcp/settings",
            headers=headers,
            content=b"x" * (app.state.settings.max_body_bytes + 1),
        )
        assert response.status_code == 413
