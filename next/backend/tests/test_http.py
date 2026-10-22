"""S0-A acceptance 2 and 3: Host, auth, health, CORS."""

import httpx
import pytest


def get(b, path="/health", headers=None, host=None, method="GET", **kw):
    h = dict(headers or {})
    if host is not None:
        h["Host"] = host
    return httpx.request(method, b.base + path, headers=h, timeout=5, **kw)


def test_health_ok_with_all_fields(backend):
    r = get(backend, headers=backend.auth)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "version", "pid", "uptime_s", "alert"}
    assert body["status"] == "ok" and body["pid"] == backend.proc.pid
    assert body["alert"] is False and body["uptime_s"] >= 0


@pytest.mark.parametrize("host", ["evil.com", "localhost:{port}", "127.0.0.1:1", "127.0.0.1"])
def test_bad_host_is_400_even_with_valid_token(backend, host):
    r = get(backend, headers=backend.auth, host=host.format(port=backend.port))
    assert r.status_code == 400


def test_bad_host_beats_missing_token(backend):
    assert get(backend, host="evil.com").status_code == 400


def test_missing_and_wrong_token_401(backend):
    assert get(backend).status_code == 401
    assert get(backend, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert get(backend, headers={"Authorization": "Basic " + backend.token}).status_code == 401
    assert get(backend, headers={"Authorization": "Bearer"}).status_code == 401
    assert get(backend, headers={"Authorization": "Bearer é".encode()}).status_code == 401
    r = get(backend, method="POST", path="/api/system/alert", json={"active": True})
    assert r.status_code == 401


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_disabled(backend, path):
    assert get(backend, path=path).status_code == 401
    assert get(backend, path=path, headers=backend.auth).status_code == 404


def test_alert_roundtrip_updates_health(backend):
    r = get(
        backend,
        path="/api/system/alert",
        method="POST",
        headers=backend.auth,
        json={"active": True, "reason": "demo"},
    )
    assert r.status_code == 200
    state = r.json()
    assert state["active"] is True and state["reason"] == "demo" and state["changed_at"]
    assert get(backend, headers=backend.auth).json()["alert"] is True
    r = get(
        backend,
        path="/api/system/alert",
        method="POST",
        headers=backend.auth,
        json={"active": False, "reason": None},
    )
    assert r.json()["active"] is False and r.json()["reason"] is None
    bad = get(
        backend, path="/api/system/alert", method="POST", headers=backend.auth, json={"reason": "x"}
    )
    assert bad.status_code == 422


def preflight(b, origin, headers="authorization"):
    return httpx.options(
        b.base + "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": headers,
        },
        timeout=5,
    )


@pytest.mark.parametrize("origin", ["tauri://localhost", "http://tauri.localhost"])
def test_preflight_allowed_without_token(backend, origin):
    r = preflight(backend, origin)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in r.headers


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost:1420", "http://127.0.0.1:1420"]
)
def test_preflight_rejected_in_non_dev(backend, origin):
    r = preflight(backend, origin)
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_preflight_dev_origins_allowed_only_with_dev(dev_backend):
    for origin in ("http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost"):
        r = preflight(dev_backend, origin)
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origin
    assert preflight(dev_backend, "https://evil.example").status_code == 400


def test_preflight_still_requires_valid_host(backend):
    r = httpx.options(
        backend.base + "/health",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Host": "evil.com",
        },
        timeout=5,
    )
    assert r.status_code == 400


def test_actual_response_carries_cors_header_for_allowed_origin(backend):
    r = get(backend, headers={**backend.auth, "Origin": "tauri://localhost"})
    assert r.headers["access-control-allow-origin"] == "tauri://localhost"
    r401 = get(backend, headers={"Origin": "tauri://localhost"})
    assert r401.status_code == 401
    assert r401.headers["access-control-allow-origin"] == "tauri://localhost"
