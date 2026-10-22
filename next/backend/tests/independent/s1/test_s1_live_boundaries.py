"""Real socket checks; run outside restricted sandboxes that cannot bind ports."""

import asyncio

import httpx
import pytest
import websockets
from websockets.exceptions import InvalidStatus

from ..harness import Proc, h, raw_http

TAURI = "tauri://localhost"


@pytest.fixture(scope="module")
def live_backend():
    backend = Proc().start()
    try:
        yield backend
    finally:
        backend.close()


def test_every_new_settings_route_requires_bearer(live_backend):
    base = live_backend.base
    routes = [
        ("GET", "/api/settings", None),
        ("POST", "/api/settings/import/preview", {}),
        ("POST", "/api/settings/import/execute", {"fingerprint": "x"}),
        ("POST", "/api/settings/import/decline", {}),
        ("GET", "/api/ado", None),
        ("POST", "/api/ado/libraries", {}),
        ("PATCH", "/api/ado/libraries/lib%3Ax", {}),
        ("DELETE", "/api/ado/libraries/lib%3Ax?revision=0", None),
        ("PUT", "/api/ado/libraries/lib%3Ax/pat", {}),
        ("DELETE", "/api/ado/libraries/lib%3Ax/pat?revision=0", None),
        ("POST", "/api/ado/libraries/lib%3Ax/test", {}),
        ("GET", "/api/ado/libraries/lib%3Ax/remote-projects?collection=x", None),
        ("POST", "/api/ado/projects", {}),
        ("PATCH", "/api/ado/projects/proj%3Ax", {}),
        ("DELETE", "/api/ado/projects/proj%3Ax?revision=0", None),
        ("PUT", "/api/ado/active", {}),
        ("GET", "/api/credentials", None),
        ("DELETE", "/api/credentials/ado_pat%3Ax", None),
    ]
    with httpx.Client(timeout=5) as client:
        for method, path, body in routes:
            response = client.request(method, base + path, json=body)
            assert response.status_code == 401, (method, path, response.status_code, response.text)


def test_chunked_request_without_content_length_over_limit_is_413(live_backend):
    payload = b"x" * (64 * 1024 + 1)
    chunked = f"{len(payload):X}\r\n".encode() + payload + b"\r\n0\r\n\r\n"
    status, raw = raw_http(
        live_backend.port,
        [
            h("POST /api/settings/import/execute HTTP/1.1"),
            h(f"Host: 127.0.0.1:{live_backend.port}"),
            h("Authorization: Bearer " + live_backend.token),
            h("Transfer-Encoding: chunked"),
            h("Connection: close"),
        ],
        chunked,
    )
    assert status == 413, raw[:400]
    assert b"Internal Server Error" not in raw


def test_websocket_handshake_without_origin_is_rejected(live_backend):
    async def attempt():
        with pytest.raises(InvalidStatus):
            await websockets.connect(
                f"ws://127.0.0.1:{live_backend.port}/ws/events",
                origin=None,
                open_timeout=5,
            )

    asyncio.run(attempt())


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_cors_preflight_allows_s1_mutation_methods(live_backend, method):
    response = httpx.options(
        live_backend.base + "/api/ado/libraries",
        headers={
            "Origin": TAURI,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization, content-type",
        },
        timeout=5,
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == TAURI
    allowed = {item.strip() for item in response.headers["access-control-allow-methods"].split(",")}
    assert allowed == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def test_cors_preflight_rejects_trace(live_backend):
    response = httpx.options(
        live_backend.base + "/api/ado/libraries",
        headers={"Origin": TAURI, "Access-Control-Request-Method": "TRACE"},
        timeout=5,
    )
    assert response.status_code == 400
    assert "TRACE" not in response.headers.get("access-control-allow-methods", "")


def test_cors_preflight_rejects_untrusted_origin(live_backend):
    response = httpx.options(
        live_backend.base + "/api/ado/libraries",
        headers={"Origin": "https://attacker.invalid", "Access-Control-Request-Method": "PUT"},
        timeout=5,
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
