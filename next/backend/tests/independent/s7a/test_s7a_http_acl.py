"""Independent HTTP permission boundary checks for S7-A routes."""

import httpx
import pytest

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings


@pytest.fixture
async def services_clients(tmp_path):
    app = create_app(
        Settings(
            token="s7a-http-test-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
        ) as anonymous, httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer s7a-http-test-token"},
        ) as authorized:
            yield anonymous, authorized


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/services", None),
        ("PATCH", "/api/services/settings", {"revision": 0, "services": {}}),
        ("POST", "/api/services/import-legacy", {"revision": 0, "path": "/tmp/old-pref.json"}),
        ("POST", "/api/services/code-server/start", {"ack_public": False}),
        ("POST", "/api/services/cloudflared/stop", {"ack_public": False}),
        ("POST", "/api/services/cloudflared/tunnels", {"target_url": "http://127.0.0.1:8080", "ack_public": False}),
        ("POST", "/api/services/cloudflared/protocol", {"revision": 0, "protocol": "http2"}),
        ("GET", "/api/services/code-server/logs", None),
    ],
)
async def test_services_http_routes_require_bearer_auth(
    services_clients, method, path, body
):
    anonymous, _ = services_clients
    response = await anonymous.request(method, path, json=body)
    assert response.status_code == 401, response.text


async def test_authorized_services_snapshot_is_read_only_and_secret_free(services_clients):
    _, authorized = services_clients
    response = await authorized.get("/api/services")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert {"code_server", "cloudflared", "network", "binaries", "settings", "revision"} <= set(payload)
    encoded = response.text.lower()
    assert "password" not in encoded
    assert "token" not in encoded
