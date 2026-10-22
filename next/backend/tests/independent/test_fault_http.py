"""Fault paths for HTTP: Host guard, Bearer parsing, CORS preflight, alert body, docs."""

import httpx
import pytest

from .harness import Proc, h, raw_http

_DEFAULT = object()
TAURI = "tauri://localhost"


def send(
    b: Proc, path: str = "/health", *, host=_DEFAULT, auth=_DEFAULT, extra=(), version=b"HTTP/1.1"
):
    """Send an exact raw GET. ``host=None`` omits Host; ``auth=None`` omits Authorization."""
    headers: list[bytes] = []
    if host is _DEFAULT:
        host = f"127.0.0.1:{b.port}"
    if host is not None:
        headers.append(h(f"Host: {host}"))
    if auth is _DEFAULT:
        auth = f"Bearer {b.token}"
    if auth is not None:
        headers.append(b"Authorization: " + (auth if isinstance(auth, bytes) else h(auth)))
    headers.extend(extra)
    lines = [b"GET " + h(path) + b" " + version] + headers + [b"Connection: close"]
    return raw_http(b.port, lines)


def health_alert(b: Proc) -> bool:
    return httpx.get(b.base + "/health", headers=b.auth, timeout=5).json()["alert"]


def reset_alert(b: Proc) -> None:
    r = httpx.post(
        b.base + "/api/system/alert",
        headers=b.auth,
        json={"active": False, "reason": None},
        timeout=5,
    )
    assert r.status_code == 200


def test_control_exact_host_and_token_is_200(ind_backend):
    status, raw = send(ind_backend)
    assert status == 200, raw[:300]


# ---------- Host boundary: everything except the exact 127.0.0.1:<port> is 400


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1:{port}.",
        "LOCALHOST:{port}",
        "localhost:{port}",
        "[::1]:{port}",
        "127.0.0.2:{port}",
        "127.0.0.1:0{port}",
        "127.0.0.1:{port}:80",
        "127.0.0.1:{port},evil.com",
        "127.0.0.1:{port}@evil.com",
        "evil.com",
        "",
        "127.0.0.1:{port}%00",
    ],
)
def test_non_exact_host_rejected_400(ind_backend, host):
    b = ind_backend
    status, raw = send(b, host=host.format(port=b.port))
    assert status == 400, raw[:300]


def test_duplicate_host_headers_rejected(ind_backend):
    b = ind_backend
    status, raw = send(b, extra=[h("Host: evil.com")])
    assert status == 400, raw[:300]


def test_missing_host_http11_rejected(ind_backend):
    status, raw = send(ind_backend, host=None)
    assert status == 400, raw[:300]


def test_http10_without_host_rejected(ind_backend):
    status, raw = send(ind_backend, host=None, version=b"HTTP/1.0")
    assert status == 400, raw[:300]


# ---------- Authorization boundary


@pytest.mark.parametrize("scheme", ["bearer {t}", "BEARER {t}", "Bearer   {t}", "Bearer {t}   "])
def test_bearer_scheme_case_and_spacing_accepted(ind_backend, scheme):
    b = ind_backend
    status, raw = send(b, auth=scheme.format(t=b.token))
    assert status == 200, raw[:300]


@pytest.mark.parametrize(
    "auth",
    [
        "Bearer",
        "Bearer ",
        "Bearer {t}x",
        "Bearer {t_short}",
        "Bearer {t_swap}",
        "Basic {t}",
        "Token {t}",
        "Bearer\t{t}",
        "{t}",
        "Bearer {t}, Bearer x",
        "Bearer ''",
        "Bearer null",
        "Bearer undefined",
    ],
)
def test_bad_authorization_is_401(ind_backend, auth):
    b = ind_backend
    t = b.token
    subs = {"t": t, "t_short": t[:-1], "t_swap": t.swapcase()}
    assert subs["t_swap"] != t
    status, raw = send(b, auth=auth.format(**subs))
    assert status == 401, raw[:300]


def test_missing_authorization_is_401(ind_backend):
    status, raw = send(ind_backend, auth=None)
    assert status == 401, raw[:300]


def test_token_in_query_string_is_not_accepted(ind_backend):
    b = ind_backend
    status, raw = send(b, path=f"/health?access_token={b.token}", auth=None)
    assert status == 401, raw[:300]


def test_non_ascii_authorization_bytes_are_401_not_500(ind_backend):
    status, raw = send(ind_backend, auth=b"Bearer \xff\xfe\x80")
    assert status == 401, raw[:300]
    assert health_ok_status(ind_backend) == 200


def test_oversized_header_does_not_crash_server(ind_backend):
    b = ind_backend
    pad = h("X-Pad: " + "a" * 100_000)
    status, raw = send(b, extra=[pad])
    # Acceptable: rejected by the HTTP layer (400/431) or connection dropped (None); never 5xx.
    assert status in (None, 200, 400, 431), raw[:200]
    assert health_ok_status(b) == 200


def health_ok_status(b: Proc) -> int:
    return httpx.get(b.base + "/health", headers=b.auth, timeout=5).status_code


# ---------- Alert body: malformed input is a client error, never 5xx, state unchanged


@pytest.mark.parametrize(
    "body",
    [
        b'{"active":',
        b"",
        b"[]",
        b'"true"',
        b'{"active": null}',
        b'{"active": "maybe"}',
        b'{"reason": "x"}',
        b'{"active": true, "reason": 123}',
        b'{"active": true, "reason": ["x"]}',
        b'{"active": true, "reason": {"a": 1}}',
        b"\x00\x01\x02",
    ],
)
def test_malformed_alert_body_is_422(ind_backend, body):
    b = ind_backend
    r = httpx.post(
        b.base + "/api/system/alert",
        headers={**b.auth, "Content-Type": "application/json"},
        content=body,
        timeout=5,
    )
    assert r.status_code == 422, r.text[:300]
    assert health_alert(b) is False


def test_invalid_utf8_alert_body_is_client_error(ind_backend):
    b = ind_backend
    r = httpx.post(
        b.base + "/api/system/alert",
        headers={**b.auth, "Content-Type": "application/json"},
        content=b'{"active": true, "reason": "\xff"}',
        timeout=5,
    )
    assert r.status_code in (400, 422), r.text[:300]
    assert health_alert(b) is False


def test_deeply_nested_alert_body_is_client_error_not_500(ind_backend):
    b = ind_backend
    body = b"[" * 50_000 + b"]" * 50_000
    r = httpx.post(
        b.base + "/api/system/alert",
        headers={**b.auth, "Content-Type": "application/json"},
        content=body,
        timeout=10,
    )
    assert r.status_code in (400, 422), (r.status_code, r.text[:200])
    assert health_ok_status(b) == 200


def test_huge_alert_reason_is_bounded_or_accepted_but_server_survives(ind_backend):
    """The contract sets no body limit. Record: 200 (accepted) or 413 (limited) both pass."""
    b = ind_backend
    r = httpx.post(
        b.base + "/api/system/alert",
        headers=b.auth,
        json={"active": True, "reason": "x" * 5_000_000},
        timeout=20,
    )
    assert r.status_code in (200, 413), r.status_code
    reset_alert(b)
    assert health_ok_status(b) == 200


def test_alert_wrong_method_and_unknown_routes(ind_backend):
    b = ind_backend
    assert httpx.get(b.base + "/api/system/alert", headers=b.auth, timeout=5).status_code == 405
    assert httpx.post(b.base + "/health", headers=b.auth, timeout=5).status_code == 405
    assert httpx.get(b.base + "/no/such", headers=b.auth, timeout=5).status_code == 404


# ---------- CORS / preflight


def preflight(
    b: Proc, origin: str, method="POST", headers="authorization, content-type", path="/health"
):
    req = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers is not None:
        req["Access-Control-Request-Headers"] = headers
    return httpx.options(b.base + path, headers=req, timeout=5)


def test_preflight_allowed_tauri_origin_without_token(ind_backend):
    r = preflight(ind_backend, TAURI, path="/api/system/alert")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == TAURI
    assert "access-control-allow-credentials" not in r.headers


def test_preflight_lowercase_and_spaced_request_headers_allowed(ind_backend):
    r = preflight(ind_backend, TAURI, headers="authorization,content-type")
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == TAURI


@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH"])
def test_preflight_disallowed_method_rejected(ind_backend, method):
    # Starlette echoes Allow-Origin on the 400 for an allowed origin; browsers still fail a
    # non-2xx preflight, so the contract is: 400, and the method is not in the allow list.
    r = preflight(ind_backend, TAURI, method=method)
    assert r.status_code == 400, r.text
    assert method not in r.headers.get("access-control-allow-methods", "")


@pytest.mark.parametrize("headers", ["x-evil", "authorization, x-custom"])
def test_preflight_disallowed_request_header_rejected(ind_backend, headers):
    r = preflight(ind_backend, TAURI, headers=headers)
    assert r.status_code == 400, r.text
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-evil" not in allowed and "x-custom" not in allowed


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "https://tauri.localhost",
        "tauri://localhost.evil.com",
        "http://tauri.localhost:8080",
        "http://localhost:1420",
        "http://evil.example",
        "https://evil.example",
    ],
)
def test_preflight_foreign_origin_not_allowed(ind_backend, origin):
    r = preflight(ind_backend, origin)
    assert r.status_code == 400, r.text
    assert "access-control-allow-origin" not in r.headers


def test_options_without_request_method_is_not_a_preflight_and_needs_token(ind_backend):
    """A bare OPTIONS is not a preflight, so the preflight exemption must not apply."""
    r = httpx.options(ind_backend.base + "/health", headers={"Origin": TAURI}, timeout=5)
    assert r.status_code in (401, 405), r.status_code


def test_preflight_never_runs_the_handler(ind_backend):
    """An unauthenticated preflight to the POST route must not change alert state."""
    b = ind_backend
    reset_alert(b)
    r = preflight(b, TAURI, path="/api/system/alert")
    assert r.status_code == 200
    assert health_alert(b) is False


def test_actual_request_from_foreign_origin_gets_no_cors_header(ind_backend):
    b = ind_backend
    r = httpx.get(
        b.base + "/health", headers={**b.auth, "Origin": "http://evil.example"}, timeout=5
    )
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_actual_request_from_tauri_origin_echoes_exact_origin_never_wildcard(ind_backend):
    b = ind_backend
    r = httpx.get(b.base + "/health", headers={**b.auth, "Origin": TAURI}, timeout=5)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == TAURI
    assert "access-control-allow-credentials" not in r.headers


def test_dev_origins_absent_in_non_dev_on_actual_request(ind_backend):
    for origin in ("http://localhost:1420", "http://127.0.0.1:1420"):
        r = httpx.get(
            ind_backend.base + "/health", headers={**ind_backend.auth, "Origin": origin}, timeout=5
        )
        assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:1420/",
        "http://localhost:14200",
        "https://localhost:1420",
        "http://localhost",
        "http://127.0.0.1:1421",
    ],
)
def test_dev_mode_origin_must_match_exactly(ind_dev, origin):
    r = preflight(ind_dev, origin)
    assert r.status_code == 400, r.text
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("origin", ["http://localhost:1420", "http://127.0.0.1:1420"])
def test_dev_mode_allows_vite_origins(ind_dev, origin):
    r = preflight(ind_dev, origin)
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == origin


def test_dev_mode_host_guard_still_enforced(ind_dev):
    status, raw = send(ind_dev, host=f"localhost:{ind_dev.port}")
    assert status == 400, raw[:300]


# ---------- Docs / schema endpoints are off in both modes


@pytest.mark.parametrize(
    "path", ["/docs", "/docs/", "/redoc", "/redoc/", "/openapi.json", "/openapi.json/"]
)
def test_docs_endpoints_absent_with_valid_token(ind_backend, path):
    r = httpx.get(ind_backend.base + path, headers=ind_backend.auth, timeout=5)
    assert r.status_code == 404
    assert "swagger" not in r.text.lower()


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_docs_endpoints_need_token_before_404(ind_backend, path):
    r = httpx.get(ind_backend.base + path, timeout=5)
    assert r.status_code == 401
