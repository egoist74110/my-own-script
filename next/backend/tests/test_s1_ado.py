import base64
import ssl

import httpx
import pytest

from toolbox_backend.adapters.ado_http import LIMIT, AdoHTTP
from toolbox_backend.domain.settings import Library

from .test_s1_settings import PAT, PAT2, create_library, revision
from .test_s1_settings import context as context

LIBRARY = Library(id="lib:test", name="Test", base_url="https://ado.example.test/tfs")


@pytest.mark.parametrize(
    "status,category",
    [
        (200, "ok"),
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (301, "redirect"),
        (302, "redirect"),
        (307, "redirect"),
        (308, "redirect"),
        (500, "bad_response"),
    ],
)
def test_status_classification_no_redirect_or_body_echo(status, category):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://evil.test/path?pat=" + PAT},
            json={"value": [{"name": "Demo"}], "echo": PAT},
        )

    result, _ = AdoHTTP(httpx.MockTransport(handler)).projects(LIBRARY, "Collection + 中文", PAT)
    assert result.category == category
    assert result.http_status == status
    assert len(requests) == 1
    assert requests[0].url.host == "ado.example.test"
    assert requests[0].url.raw_path.startswith(b"/tfs/Collection%20%2B%20")
    assert (
        requests[0].headers["Authorization"]
        == "Basic " + base64.b64encode((":" + PAT).encode()).decode()
    )
    assert PAT not in result.model_dump_json()
    if category == "redirect":
        assert result.message == "被重定向到 https://evil.test:443"


@pytest.mark.parametrize(
    "error,category",
    [
        (httpx.ConnectTimeout("echo " + PAT), "timeout"),
        (httpx.ReadTimeout("echo " + PAT), "timeout"),
        (httpx.ConnectError("SSL certificate verification " + PAT), "tls"),
        (ssl.SSLError("echo " + PAT), "tls"),
        (httpx.ConnectError("connection refused " + PAT), "network"),
        (httpx.RemoteProtocolError("echo " + PAT), "network"),
    ],
)
def test_transport_errors_are_fixed_messages(error, category):
    def handler(request):
        raise error

    result, _ = AdoHTTP(httpx.MockTransport(handler)).projects(LIBRARY, "Default", PAT)
    assert result.category == category
    assert PAT not in result.model_dump_json()


class LargeStream(httpx.SyncByteStream):
    def __init__(self):
        self.read = 0
        self.closed = False

    def __iter__(self):
        for _ in range(1000):
            self.read += 65536
            yield b"x" * 65536

    def close(self):
        self.closed = True


def test_response_size_is_bounded_and_stream_always_closed():
    stream = LargeStream()
    adapter = AdoHTTP(httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    result, _ = adapter.projects(LIBRARY, "Default", PAT)
    assert result.category == "bad_response"
    assert stream.read <= LIMIT + 65536
    assert stream.closed


@pytest.mark.parametrize("payload", [b"not json", b"[]", b'{"value":42}', b'{"value":[{}]}'])
def test_invalid_responses_are_not_reflected(payload):
    result, _ = AdoHTTP(
        httpx.MockTransport(lambda _: httpx.Response(200, content=payload))
    ).projects(LIBRARY, "Default", PAT)
    assert result.category == "bad_response"
    assert result.message == "远端响应格式无效"


def test_remote_project_count_is_capped_and_names_redacted():
    result, projects = AdoHTTP(
        httpx.MockTransport(lambda _: httpx.Response(200, json={"value": [{"name": PAT}] * 501}))
    ).projects(LIBRARY, "Default", PAT, listing=True)
    assert result.ok and len(projects) == 500
    assert all(PAT not in project.name for project in projects)


def test_no_credential_makes_no_request():
    def handler(_):
        raise AssertionError("must not send")

    result, projects = AdoHTTP(httpx.MockTransport(handler)).projects(LIBRARY, "Default", None)
    assert result.category == "no_credential" and projects == []


async def test_saved_and_candidate_credentials_http_endpoints(context):
    app, client, new, _, _, requests = context
    lid = await create_library(client)
    response = await client.post(f"/api/ado/libraries/{lid}/test", json={"collection": "Default"})
    assert response.json()["category"] == "no_credential" and requests == []
    response = await client.post(
        f"/api/ado/libraries/{lid}/test", json={"collection": "Default", "pat": PAT}
    )
    assert response.json()["ok"]
    assert new.values == {} and (await app.state.config_store.read()).credentials == {}
    assert PAT not in response.text
    response = await client.put(
        f"/api/ado/libraries/{lid}/pat", json={"revision": await revision(client), "pat": PAT2}
    )
    assert response.status_code == 200
    response = await client.get(
        f"/api/ado/libraries/{lid}/remote-projects", params={"collection": "Default"}
    )
    assert response.json() == [{"name": "Project A"}]
    assert requests[-1].url.params["$top"] == "500"
    assert PAT2 not in response.text
    response = await client.delete(
        f"/api/ado/libraries/{lid}/pat", params={"revision": await revision(client)}
    )
    assert response.status_code == 200 and new.values == {}


async def test_remote_list_without_pat_returns_409_without_http(context):
    _, client, _, _, _, requests = context
    lid = await create_library(client)
    response = await client.get(
        f"/api/ado/libraries/{lid}/remote-projects",
        params={"collection": "Default"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_credential"
    assert requests == []


@pytest.mark.parametrize("collection", [None, "slash/path", "back\\slash", "control\nchar", ""])
async def test_remote_list_invalid_parameters_return_422_before_http(context, collection):
    _, client, _, _, _, requests = context
    lid = await create_library(client)
    response = await client.get(
        f"/api/ado/libraries/{lid}/remote-projects",
        params={} if collection is None else {"collection": collection},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert requests == []


@pytest.mark.parametrize(
    "category",
    [
        "unauthorized",
        "forbidden",
        "not_found",
        "redirect",
        "tls",
        "timeout",
        "network",
        "bad_response",
    ],
)
async def test_remote_list_outbound_failure_is_502_with_safe_category(context, category):
    app, client, _, _, _, _ = context
    lid = await create_library(client, pat=PAT)
    requests = []

    def handler(request):
        requests.append(request)
        if category == "tls":
            raise httpx.ConnectError("SSL certificate " + PAT)
        if category == "timeout":
            raise httpx.ReadTimeout("echo " + PAT)
        if category == "network":
            raise httpx.ConnectError("connection refused " + PAT)
        status = {
            "unauthorized": 401,
            "forbidden": 403,
            "not_found": 404,
            "redirect": 302,
            "bad_response": 200,
        }[category]
        return httpx.Response(
            status, headers={"Location": "https://evil.test/" + PAT}, content=PAT.encode()
        )

    app.state.settings_service.http = AdoHTTP(httpx.MockTransport(handler))
    response = await client.get(
        f"/api/ado/libraries/{lid}/remote-projects",
        params={"collection": "Default"},
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ado_request_failed"
    assert response.json()["detail"]["category"] == category
    assert isinstance(response.json()["detail"]["message"], str)
    assert PAT not in response.text
    assert len(requests) == 1 and requests[0].url.host == "ado.example.test"


def test_remote_list_failure_contracts_share_connection_categories():
    import json

    from toolbox_backend.contracts import generate

    spec = json.loads(generate()["openapi.json"])
    schemas = spec["components"]["schemas"]
    assert (
        schemas["AdoRequestErrorDetail"]["properties"]["category"]["enum"]
        == schemas["ConnectionResult"]["properties"]["category"]["enum"]
    )
    responses = spec["paths"]["/api/ado/libraries/{id}/remote-projects"]["get"]["responses"]
    for status, model in (
        ("409", "NoCredentialErrorResponse"),
        ("502", "AdoRequestErrorResponse"),
        ("422", "ValidationErrorResponse"),
    ):
        assert responses[status]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{model}"
        }
