import base64

import httpx
import pytest

from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.domain.settings import DynamicTask

PAT = "FAKE_S1_ADO_PAT_943"


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://ado.example.test",
        "https://user:pass@ado.example.test",
        "https://ado.example.test/path?token=x",
        "https://ado.example.test/path#frag",
        "https:///missing-host",
        "https://ado.example.test/" + "a" * 2050,
    ],
)
async def test_invalid_library_base_urls_are_rejected_without_echo(s1ctx, base_url):
    response = await s1ctx.create_library(base_url=base_url)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert base_url not in response.text


async def test_duplicate_library_name_and_dangling_project_library_are_rejected(s1ctx):
    first = await s1ctx.create_library(name="Repeated")
    assert first.status_code == 200, first.text
    duplicate = await s1ctx.create_library(name="Repeated")
    assert duplicate.status_code == 422
    revision = await s1ctx.revision()
    dangling = await s1ctx.client.post(
        "/api/ado/projects",
        json={
            "revision": revision,
            "library_id": "lib:missing",
            "collection": "Default",
            "project": "Project",
        },
    )
    assert dangling.status_code == 422
    assert dangling.json()["detail"]["code"] == "validation_error"


@pytest.mark.parametrize("segment", ["slash/name", "back\\slash", "line\nbreak"])
async def test_project_segments_and_collection_query_reject_path_injection(s1ctx, segment):
    library = await s1ctx.create_library()
    library_id = library.json()["id"]
    revision = await s1ctx.revision()
    project = await s1ctx.client.post(
        "/api/ado/projects",
        json={
            "revision": revision,
            "library_id": library_id,
            "collection": segment,
            "project": "Safe",
        },
    )
    assert project.status_code == 422
    project2 = await s1ctx.client.post(
        "/api/ado/projects",
        json={
            "revision": revision,
            "library_id": library_id,
            "collection": "Default",
            "project": segment,
        },
    )
    assert project2.status_code == 422
    remote = await s1ctx.client.get(
        f"/api/ado/libraries/{library_id}/remote-projects", params={"collection": segment}
    )
    assert remote.status_code == 422
    assert s1ctx.requests == []


async def test_library_and_project_in_use_cannot_be_deleted(s1ctx):
    library = await s1ctx.create_library()
    library_id = library.json()["id"]
    project_response = await s1ctx.client.post(
        "/api/ado/projects",
        json={
            "revision": await s1ctx.revision(),
            "library_id": library_id,
            "collection": "Default",
            "project": "Build",
        },
    )
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]
    config = await s1ctx.app.state.config_store.read()

    def add_task(current):
        current.tasks.items.append(
            DynamicTask(id="task:ref", name="Release task", project_id=project_id)
        )

    await s1ctx.app.state.config_store.update(config.revision, add_task)
    delete_project = await s1ctx.client.delete(
        f"/api/ado/projects/{project_id}", params={"revision": await s1ctx.revision()}
    )
    assert delete_project.status_code == 409
    assert delete_project.json()["detail"]["code"] == "in_use"
    delete_library = await s1ctx.client.delete(
        f"/api/ado/libraries/{library_id}", params={"revision": await s1ctx.revision()}
    )
    assert delete_library.status_code == 409
    assert delete_library.json()["detail"]["code"] == "in_use"


async def test_origin_change_requires_replacement_or_explicit_keep(s1ctx):
    created = await s1ctx.create_library(pat=PAT)
    library_id = created.json()["id"]
    rejected = await s1ctx.client.patch(
        f"/api/ado/libraries/{library_id}",
        json={"revision": await s1ctx.revision(), "base_url": "https://other.example.test"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "pat_origin_change"
    assert not s1ctx.requests
    accepted = await s1ctx.client.patch(
        f"/api/ado/libraries/{library_id}",
        json={
            "revision": await s1ctx.revision(),
            "base_url": "https://other.example.test",
            "keep_pat": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert not s1ctx.requests


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (302, "redirect"),
        (500, "bad_response"),
    ],
)
async def test_remote_list_classifies_http_failures_and_never_follows_redirect(
    s1ctx, status, category
):
    library = await s1ctx.create_library(pat=PAT)
    library_id = library.json()["id"]
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://evil.example/collect?pat=" + PAT},
            content=PAT.encode(),
        )

    s1ctx.app.state.settings_service.http = AdoHTTP(httpx.MockTransport(handler))
    response = await s1ctx.client.get(
        f"/api/ado/libraries/{library_id}/remote-projects", params={"collection": "Default"}
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ado_request_failed"
    assert response.json()["detail"]["category"] == category
    assert PAT not in response.text
    assert len(seen) == 1
    assert seen[0].url.host == "ado.example.test"
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(
        (":" + PAT).encode()
    ).decode()


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (httpx.ConnectError("fake transport"), "network"),
        (httpx.ConnectTimeout("fake timeout"), "timeout"),
        (httpx.ConnectError("SSL certificate failure"), "tls"),
    ],
)
async def test_remote_list_classifies_transport_errors(s1ctx, error, category):
    library = await s1ctx.create_library(pat=PAT)
    library_id = library.json()["id"]

    def handler(_):
        raise error

    s1ctx.app.state.settings_service.http = AdoHTTP(httpx.MockTransport(handler))
    response = await s1ctx.client.get(
        f"/api/ado/libraries/{library_id}/remote-projects", params={"collection": "Default"}
    )
    assert response.status_code == 502
    assert response.json()["detail"]["category"] == category
    assert PAT not in response.text


async def test_remote_list_body_over_one_mib_is_rejected(s1ctx):
    library = await s1ctx.create_library(pat=PAT)
    library_id = library.json()["id"]
    oversized = b'{"value":[]}' + b" " * ((1 << 20) + 1)
    s1ctx.app.state.settings_service.http = AdoHTTP(
        httpx.MockTransport(lambda _: httpx.Response(200, content=oversized))
    )
    response = await s1ctx.client.get(
        f"/api/ado/libraries/{library_id}/remote-projects", params={"collection": "Default"}
    )
    assert response.status_code == 502
    assert response.json()["detail"]["category"] == "bad_response"


async def test_remote_list_without_pat_returns_409_without_outbound_request(s1ctx):
    library = await s1ctx.create_library()
    response = await s1ctx.client.get(
        f"/api/ado/libraries/{library.json()['id']}/remote-projects",
        params={"collection": "Default"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_credential"
    assert not s1ctx.requests


async def test_remote_list_invalid_collection_is_422_without_outbound_request(s1ctx):
    library = await s1ctx.create_library(pat=PAT)
    response = await s1ctx.client.get(
        f"/api/ado/libraries/{library.json()['id']}/remote-projects",
        params={"collection": "bad/name"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert not s1ctx.requests
