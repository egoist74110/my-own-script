"""S2 service/route contract tests. All data and outbound traffic are synthetic."""

import asyncio
import base64
import json
import threading
from pathlib import Path

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.adapters.fake_ado import fake_transport
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import Library, Project
from toolbox_backend.services import work_items
from toolbox_backend.services.work_items import MediaRegistry, outbound
from toolbox_backend.settings import Settings

PAT = "FAKE_S2_EXECUTOR_PAT_391b7ac"
BASE = "https://ado.example.test/tfs"
LIB = Library(id="lib:s2", name="虚构库", base_url=BASE)
PROJECT = Project(id="proj:s2", library_id=LIB.id, collection="集合 +", project="项目 O'Neil")


def item(ident=10, **extra):
    return {
        "id": ident,
        "rev": 3,
        "fields": {
            "System.Title": "虚构标题",
            "System.WorkItemType": "用户情景",
            "System.AssignedTo": {"uniqueName": "fallback@example.test"},
            "System.Tags": " alpha ; beta; ; 中文 ",
            "Microsoft.VSTS.Common.Priority": 2,
            "System.Description": "<p>描述 <b>bold</b></p>",
        },
        "relations": [],
        **extra,
    }


@pytest.fixture
async def context(tmp_path):
    requests = []
    state = {"handler": lambda _: httpx.Response(200, json=item())}

    def handler(request):
        requests.append(request)
        return state["handler"](request)

    creds = MemoryCredentials()
    creds.values["ado_pat:" + LIB.id] = PAT
    app = create_app(
        Settings(
            token="s2-test-api-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=creds,
        legacy_credentials=MemoryCredentials(),
        ado_read=AdoRead(httpx.MockTransport(handler)),
    )
    await app.state.config_store.update(
        0, lambda c: (c.ado.libraries.append(LIB), c.ado.projects.append(PROJECT))
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer s2-test-api-token"},
    ) as client:
        yield app, client, creds, requests, state


async def get(client, suffix="", **params):
    return await client.get("/api/work-items" + suffix, params={"project_id": PROJECT.id, **params})


async def test_columns_and_wiql_batch_contract(context):
    _, client, _, requests, state = context
    response = await client.get("/api/work-items/columns")
    assert response.json() == {
        "columns": ["新建", "待开发", "开发中", "测试", "已关闭"],
        "default": "开发中",
    }
    ids = list(range(1, 501))

    def handler(request):
        if request.url.path.endswith("/wiql"):
            assert request.method == "POST"
            assert dict(request.url.params) == {"api-version": "7.0", "$top": "500"}
            query = json.loads(request.content)["query"]
            assert "[System.TeamProject] = '项目 O''Neil'" in query
            assert "[System.BoardColumn] = '开发中'" in query
            assert query.endswith(
                "ORDER BY [Microsoft.VSTS.Common.Priority] ASC, [System.ChangedDate] DESC"
            )
            return httpx.Response(200, json={"workItems": [{"id": x} for x in ids]})
        assert request.method == "POST" and request.url.path.endswith("/workitemsbatch")
        body = json.loads(request.content)
        assert body["errorPolicy"] == "omit"
        assert body["fields"] == work_items.DEFAULT_WORK_ITEM_FIELDS
        assert "$expand" not in body and len(body["ids"]) <= 200
        return httpx.Response(200, json={"value": [item(x) for x in body["ids"] if x != 42]})

    state["handler"] = handler
    response = await get(client)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["truncated"] and data["omitted"] == 1 and len(data["items"]) == 499
    assert data["items"][0]["tags"] == ["alpha", "beta", "中文"]
    assert data["items"][0]["assigned_to"] == "fallback@example.test"
    assert [len(json.loads(r.content)["ids"]) for r in requests[1:]] == [200, 200, 100]
    for request in requests:
        assert request.url.raw_path.startswith(b"/tfs/%E9%9B%86%E5%90%88%20%2B/")
        assert "%27" in str(request.url)
        assert (
            request.headers["Authorization"]
            == "Basic " + base64.b64encode((":" + PAT).encode()).decode()
        )


async def test_detail_relations_html_and_web_url(context):
    _, client, _, requests, state = context
    data = item()
    data["fields"].update(
        {
            "Microsoft.VSTS.TCM.ReproSteps": "<ol><li>复现</li></ol>",
            "Microsoft.VSTS.Common.AcceptanceCriteria": "<p>验收</p>",
        }
    )
    root = BASE + "/_apis/wit/"
    data["relations"] = [
        {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": root + "workitems/2"},
        {"rel": "System.LinkTypes.Hierarchy-Forward", "url": root + "workitems/11"},
        {
            "rel": "AttachedFile",
            "url": root + "attachments/a",
            "attributes": {"name": "../截图.png\r\n", "resourceSize": 123},
        },
        {
            "rel": "AttachedFile",
            "url": "https://outside.test/secret?query=hidden",
            "attributes": {"name": "outside.txt"},
        },
        {"rel": "ArtifactLink", "url": "vstfs:///Git/PullRequestId/project%2Frepo%2F123"},
        {"rel": "ArtifactLink", "url": "vstfs:///Git/Commit/project%2Frepo%2Fabc"},
        {"rel": "Hyperlink", "url": "https://example.test/docs", "attributes": {"name": "文档"}},
        {"rel": "Hyperlink", "url": "javascript:alert(1)"},
        {"rel": "other", "url": "https://not-returned.test/raw"},
    ]
    state["handler"] = lambda _: httpx.Response(200, json=data)
    response = await get(client, "/10")
    assert response.status_code == 200, response.text
    shaped = response.json()
    assert requests[0].method == "GET" and requests[0].url.path.endswith("/_apis/wit/workitems/10")
    assert dict(requests[0].url.params) == {"api-version": "7.0", "$expand": "relations"}
    assert shaped["rev"] == 3 and shaped["parent_id"] == 2 and shaped["child_ids"] == [11]
    assert "/_workitems/edit/10" in shaped["web_url"] and "%20%2B" in shaped["web_url"]
    assert shaped["html"]["repro_steps"]["html"] == "<ol><li>复现</li></ol>"
    assert shaped["attachments"][0]["size"] == 123
    assert shaped["attachments"][0]["name"] == "..截图.png"
    assert shaped["attachments"][1]["media_id"] is None
    assert shaped["attachments"][1]["blocked_origin"] == "https://outside.test:443"
    assert shaped["links"][0] == {"kind": "pull_request", "label": "PR #123", "url": None}
    assert shaped["links"][1]["kind"] == "commit" and shaped["links"][1]["url"] is None
    assert shaped["links"][2]["url"] == "https://example.test/docs"
    assert shaped["links"][3]["url"] is None and shaped["links"][4]["url"] is None
    assert "fields" not in shaped and "relations" not in shaped
    assert "query=hidden" not in response.text and root + "attachments" not in response.text


async def test_comments_contract_deleted_compatibility_truncation_and_sanitization(context):
    _, client, _, requests, state = context
    values = [
        {"id": 1, "isDeleted": True, "text": "hidden"},
        {
            "commentId": 2,
            "createdBy": {"name": "author fallback"},
            "text": "<p>comment<script>evil</script></p>",
        },
        {"id": 3, "text": "x" * ((1 << 20) + 1)},
    ] + [{"id": x, "text": ""} for x in range(4, 101)]
    state["handler"] = lambda _: httpx.Response(200, json={"comments": values})
    response = await get(client, "/10/comments")
    assert response.status_code == 200, response.text
    request = requests[0]
    assert request.url.path.endswith("/workItems/10/comments") and request.method == "GET"
    assert dict(request.url.params) == {"api-version": "7.0-preview.4", "$top": "100"}
    result = response.json()
    assert result["truncated"] and len(result["comments"]) == 99
    assert result["comments"][0]["id"] == 2 and result["comments"][0]["author"] == "author fallback"
    assert result["comments"][0]["html"] == "<p>comment</p>"
    assert result["comments"][1]["html"] is None and result["comments"][1]["omitted"] == "too_large"


async def test_updates_are_plain_text_with_2000_character_limit(context):
    _, client, _, requests, state = context
    state["handler"] = lambda _: httpx.Response(
        200,
        json={
            "value": [
                {
                    "id": 9,
                    "rev": 2,
                    "revisedBy": {"displayName": "Reviser"},
                    "revisedDate": "date",
                    "fields": {
                        "System.Description": {
                            "oldValue": "<p> old &amp; text </p>",
                            "newValue": "<b>" + "x" * 2100 + "</b>",
                        }
                    },
                    "relations": {"added": [{}, {}], "removed": [{}]},
                }
            ]
            * 100
        },
    )
    response = await get(client, "/10/updates")
    assert response.status_code == 200
    assert requests[0].url.path.endswith("/workItems/10/updates")
    assert dict(requests[0].url.params) == {"api-version": "7.0", "$top": "100"}
    data = response.json()
    assert data["truncated"] and len(data["updates"]) == 100
    update = data["updates"][0]
    assert update["fields"][0] == {
        "name": "System.Description",
        "old": "old & text",
        "new": "x" * 2000,
    }
    assert update["relations_added"] == 2 and update["relations_removed"] == 1


@pytest.mark.parametrize("shape", ["depth", "width", "width_deep", "cycle"])
async def test_children_bfs_depth_limit_count_limit_and_cycle(context, shape):
    _, client, _, requests, state = context

    def node(ident):
        if shape == "depth":
            children = [ident + 1]
        elif shape in {"width", "width_deep"}:
            children = (
                list(range(11, 512 if shape == "width" else 511))
                if ident == 10
                else ([ident + 1000] if shape == "width_deep" and ident < 1000 else [])
            )
        else:
            children = {10: [11, 12, 11], 11: [10, 13], 12: [13, 14], 13: [10], 14: []}[ident]
        return item(
            ident,
            relations=[
                {"rel": "System.LinkTypes.Hierarchy-Forward", "url": BASE + "/workitems/" + str(x)}
                for x in children
            ],
        )

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=node(10))
        body = json.loads(request.content)
        assert "$expand" in body and "fields" not in body and body["errorPolicy"] == "omit"
        assert len(body["ids"]) <= 200
        return httpx.Response(200, json={"value": [node(x) for x in body["ids"]]})

    state["handler"] = handler
    response = await get(client, "/10/children")
    assert response.status_code == 200, response.text
    data = response.json()
    ids = [x["id"] for x in data["items"]]
    assert len(ids) == len(set(ids)) and 10 not in ids
    if shape == "depth":
        assert data["truncated"] and ids == list(range(11, 19))
        assert [x["depth"] for x in data["items"]] == list(range(1, 9))
    elif shape in {"width", "width_deep"}:
        assert len(ids) == 500
        assert data["truncated"]
    else:
        assert not data["truncated"] and ids == [11, 12, 13, 14]
        assert [x["parent_id"] for x in data["items"]] == [10, 10, 11, 12]
    assert len(requests) <= 9


@pytest.mark.parametrize(
    "suffix",
    ["", "/columns", "/10", "/10/comments", "/10/updates", "/10/children", "/media/unknown"],
)
async def test_all_work_item_routes_require_bearer(context, suffix):
    _, client, _, requests, _ = context
    client.headers.pop("Authorization")
    response = await get(client, suffix)
    assert response.status_code == 401 and requests == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/ado/local-repos", {"revision": 1, "name": "repo", "path": "/tmp/repo"}),
        ("PATCH", "/api/ado/local-repos/repo:unknown", {"revision": 1, "name": "repo"}),
        ("DELETE", "/api/ado/local-repos/repo:unknown?revision=1", None),
    ],
)
async def test_local_repo_routes_require_bearer(context, method, path, body):
    _, client, _, _, _ = context
    client.headers.pop("Authorization")
    assert (await client.request(method, path, json=body)).status_code == 401


@pytest.mark.parametrize(
    "suffix,params",
    [
        ("", {"column": "开发中' OR 1=1"}),
        ("/0", {}),
        ("/2147483648", {}),
        ("/abc", {}),
        ("/1/comments", {"project_id": "proj:missing"}),
    ],
)
async def test_invalid_input_or_project_prevents_outbound(context, suffix, params):
    _, client, _, requests, _ = context
    response = await get(client, suffix, **params)
    assert response.status_code in {404, 422} and requests == []


@pytest.mark.parametrize(
    "status,expected,category",
    [
        (401, 502, "unauthorized"),
        (403, 502, "forbidden"),
        (404, 404, None),
        (302, 502, "redirect"),
        (500, 502, "bad_response"),
    ],
)
async def test_remote_failures_and_missing_pat_are_safe(context, status, expected, category):
    _, client, credentials, requests, state = context
    state["handler"] = lambda _: httpx.Response(
        status, headers={"Location": "https://evil.test/" + PAT}, content=PAT.encode()
    )
    response = await get(client, "/10")
    assert response.status_code == expected and PAT not in response.text
    if category:
        assert response.json()["detail"]["category"] == category
    credentials.values.clear()
    requests.clear()
    response = await get(client, "/10")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "no_credential"
    assert requests == []


async def test_pat_never_in_shaped_responses_events_logs_or_config(context, caplog):
    app, client, _, _, state = context
    data = item()
    data["fields"]["System.Title"] = PAT
    data["fields"]["System.Description"] = "<p>" + PAT + "</p>"
    data["relations"] = [
        {"rel": "AttachedFile", "url": BASE + "/a?pat=" + PAT, "attributes": {"name": PAT}}
    ]
    state["handler"] = lambda _: httpx.Response(200, json=data)
    subscriber = app.state.hub.subscribe()
    try:
        response = await get(client, "/10")
        assert response.status_code == 200 and PAT not in response.text
        assert PAT not in caplog.text
        assert PAT not in app.state.config_store.path.read_text()
        assert subscriber.queue.empty()
    finally:
        app.state.hub.unsubscribe(subscriber)


async def test_shared_outbound_gate_queues_seventh_and_reports_busy(monkeypatch):
    monkeypatch.setattr(work_items, "OUTBOUND", asyncio.Semaphore(6))
    entered, release = [], threading.Event()

    def slow(index):
        entered.append(index)
        assert release.wait(3)
        return index

    tasks = [asyncio.create_task(outbound(slow, i)) for i in range(6)]
    try:
        for _ in range(100):
            if len(entered) == 6:
                break
            await asyncio.sleep(0.001)
        assert len(entered) == 6
        seventh = asyncio.create_task(outbound(lambda: 7))
        await asyncio.sleep(0.01)
        assert not seventh.done()
        monkeypatch.setattr(work_items, "QUEUE_TIMEOUT_S", 0.01)
        from toolbox_backend.domain.errors import SettingsError

        with pytest.raises(SettingsError) as caught:
            await outbound(lambda: "must not run")
        assert caught.value.code == "busy" and caught.value.status == 503
    finally:
        release.set()
        assert await asyncio.gather(*tasks) == list(range(6))
    assert await seventh == 7


async def test_cancelled_outbound_retains_permit_until_worker_closes(monkeypatch):
    gate = asyncio.Semaphore(1)
    monkeypatch.setattr(work_items, "OUTBOUND", gate)
    release, started = threading.Event(), threading.Event()
    closed = []

    def worker():
        started.set()
        try:
            assert release.wait(3)
        finally:
            closed.append(True)

    task = asyncio.create_task(outbound(worker))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and gate.locked()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed == [True] and not gate.locked()


def test_registry_non_sliding_ttl_dedup_and_fifo():
    now = [0]
    registry = MediaRegistry(ttl_s=1800, limit=2, clock=lambda: now[0])
    one, _ = registry.register(PROJECT.id, LIB, BASE + "/a", "image")
    now[0] = 1000
    assert registry.register(PROJECT.id, LIB, BASE + "/a", "image")[0] == one
    two, _ = registry.register(PROJECT.id, LIB, BASE + "/b", "attachment")
    registry.register(PROJECT.id, LIB, BASE + "/c", "attachment")
    from toolbox_backend.domain.errors import SettingsError

    with pytest.raises(SettingsError):
        registry.get(one)
    now[0] = 2800
    with pytest.raises(SettingsError):
        registry.get(two)
    assert len(registry.entries) == 0


@pytest.mark.parametrize("dev,mode", [(False, "memory"), (True, "keyring"), (False, "keyring")])
def test_fake_ado_rejects_unsafe_mode_without_io(monkeypatch, tmp_path, dev, mode):
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_ADO", str(tmp_path / "missing"))
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", mode)
    with pytest.raises(ValueError, match="requires --dev"):
        fake_transport(dev)


async def test_fake_fixture_covers_read_flows_without_socket(context, monkeypatch):
    app, client, _, _, _ = context
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_ADO", str(Path(__file__).parent / "fixtures/fake-ado"))
    app.state.work_items_service.http = AdoRead(fake_transport(True))
    response = await get(client)
    assert len(response.json()["items"]) == 2
    response = await get(client, "/101")
    detail = response.json()
    assert response.status_code == 200
    assert "data-media-id" in detail["html"]["description"]["html"]
    assert "https://external.example.test:443" in detail["html"]["description"]["html"]
    attachment = await client.get("/api/work-items/media/" + detail["attachments"][0]["media_id"])
    assert attachment.status_code == 200 and attachment.content == "虚构附件\n".encode()
    assert len((await get(client, "/101/children")).json()["items"]) == 1
    assert len((await get(client, "/101/comments")).json()["comments"]) == 1
    assert len((await get(client, "/101/updates")).json()["updates"]) == 1


@pytest.mark.parametrize(
    "change", ["delete_library", "origin", "prefix", "no_pat", "ttl", "evict", "unknown"]
)
async def test_media_revalidates_store_and_registration_before_io(context, change):
    app, client, credentials, requests, _ = context
    registry = app.state.work_items_service.media
    mid, _ = registry.register(PROJECT.id, LIB, BASE + "/image.png", "image")
    if change == "delete_library":

        def remove(c):
            c.ado.projects = []
            c.ado.libraries = []

        await app.state.config_store.update(1, remove)
    elif change in {"origin", "prefix"}:
        new_base = "https://other.example.test/tfs" if change == "origin" else BASE + "/new"
        await app.state.config_store.update(
            1, lambda c: setattr(c.ado.libraries[0], "base_url", new_base)
        )
        credentials.values.clear()  # expiration takes precedence over missing PAT
    elif change == "no_pat":
        credentials.values.clear()
    elif change == "ttl":
        registry.clock = lambda: registry.entries[mid].created_at + 1800
    elif change == "evict":
        registry.limit = 1
        registry.register(PROJECT.id, LIB, BASE + "/other", "image")
    else:
        mid = "not-registered"
    response = await client.get("/api/work-items/media/" + mid)
    assert response.status_code == (409 if change == "no_pat" else 404)
    assert response.json()["detail"]["code"] == (
        "no_credential" if change == "no_pat" else "media_expired"
    )
    assert requests == []


@pytest.mark.parametrize(
    "body,mime",
    [
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"\xff\xd8\xffrest", "image/jpeg"),
        (b"GIF87arest", "image/gif"),
        (b"GIF89arest", "image/gif"),
        (b"RIFFxxxxWEBPrest", "image/webp"),
        (b"BMrest", "image/bmp"),
        (b"unknown", None),
        (b'<svg onload="x"/>', None),
    ],
)
async def test_media_magic_only_and_all_security_headers(context, body, mime):
    app, client, _, _, state = context
    mid, _ = app.state.work_items_service.media.register(PROJECT.id, LIB, BASE + "/image", "image")
    state["handler"] = lambda _: httpx.Response(
        200, content=body, headers={"Content-Type": "image/svg+xml"}
    )
    response = await client.get("/api/work-items/media/" + mid)
    assert response.status_code == (200 if mime else 415)
    if mime:
        assert response.headers["Content-Type"] == mime
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
        assert response.headers["Cache-Control"] == "private, no-store"


async def test_local_repo_name_unique_normalization_conflicts_and_readonly(context, tmp_path):
    app, client, _, _, _ = context
    response = await client.post(
        "/api/ado/local-repos",
        json={"revision": 1, "name": " Workspace ", "path": str(tmp_path) + "/./not-present//"},
    )
    assert response.status_code == 200, response.text
    rid = response.json()["id"]
    result = (await client.get("/api/ado")).json()
    assert result["local_repos"][0]["path"] == str(tmp_path / "not-present")
    assert (
        result["local_repos"][0]["name"] == "Workspace" and not result["local_repos"][0]["exists"]
    )
    response = await client.post(
        "/api/ado/local-repos", json={"revision": 2, "name": "Workspace", "path": str(tmp_path)}
    )
    assert response.status_code == 422
    response = await client.delete("/api/ado/local-repos/" + rid, params={"revision": 1})
    assert response.status_code == 409
    await app.state.config_store.update(
        2, lambda c: c.imported.work_items.update({"local_repo_id": rid})
    )
    response = await client.delete("/api/ado/local-repos/" + rid, params={"revision": 3})
    assert response.status_code == 200
    assert (await app.state.config_store.read()).imported.work_items["local_repo_id"] == rid
    app.state.config_store.path.write_text("{broken")
    for method, path, body in [
        ("POST", "/api/ado/local-repos", {"revision": 4, "name": "x", "path": str(tmp_path)}),
        ("PATCH", "/api/ado/local-repos/repo:missing", {"revision": 4, "name": "x"}),
        ("DELETE", "/api/ado/local-repos/repo:missing?revision=4", None),
    ]:
        response = await client.request(method, path, json=body)
        assert (
            response.status_code == 503 and response.json()["detail"]["code"] == "store_unavailable"
        )
    assert (await client.get("/api/work-items/columns")).status_code == 200
    assert app.state.config_store.path.read_text() == "{broken"


async def test_remote_media_echoing_pat_is_rejected_without_exposing_bytes(context):
    app, client, _, _, state = context
    mid, _ = app.state.work_items_service.media.register(
        PROJECT.id, LIB, BASE + "/file", "attachment"
    )
    state["handler"] = lambda _: httpx.Response(200, content=PAT.encode())
    response = await client.get("/api/work-items/media/" + mid)
    assert response.status_code == 502 and PAT not in response.text
    assert response.json()["detail"]["category"] == "bad_response"


@pytest.mark.parametrize("dev,mode", [(False, "memory"), (True, "keyring"), (False, "keyring")])
def test_invalid_fake_mode_fails_main_before_bind(monkeypatch, tmp_path, dev, mode):
    from toolbox_backend import server

    monkeypatch.setenv("TOOLBOX_DEV_FAKE_ADO", str(tmp_path / "unused"))
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", mode)
    monkeypatch.setattr(server, "bind_socket", lambda: pytest.fail("must reject before binding"))
    monkeypatch.setattr(server, "setup_logging", lambda _: None)
    assert server.main(["--dev"] if dev else []) == 1


def test_html_cannot_forge_generated_media_attributes():
    from toolbox_backend.adapters.html_sanitize import sanitize_html

    cleaned = sanitize_html(
        '<span data-blocked-origin="https://forged.test:443">text</span>'
        '<img data-media-id="forged-id" src="data:image/png;base64,A">',
        lambda _: (None, ""),
    )
    assert "forged" not in cleaned.html and "data-media-id" not in cleaned.html
    assert "[内嵌图片未显示]" in cleaned.html


async def test_legacy_repo_name_patch_does_not_validate_untouched_legacy_path(context):
    from toolbox_backend.domain.settings import LocalRepo

    app, client, _, _, _ = context
    await app.state.config_store.update(
        1,
        lambda c: c.ado.local_repos.append(
            LocalRepo(id="repo:legacy", name="Legacy", path="relative/../old")
        ),
    )
    response = await client.patch(
        "/api/ado/local-repos/repo:legacy", json={"revision": 2, "name": "Renamed"}
    )
    assert response.status_code == 200, response.text
    repo = (await client.get("/api/ado")).json()["local_repos"][0]
    assert repo["name"] == "Renamed" and repo["path"] == "relative/../old" and repo["warnings"]


async def test_comment_id_null_uses_legacy_comment_id(context):
    _, client, _, _, state = context
    state["handler"] = lambda _: httpx.Response(
        200, json={"comments": [{"id": None, "commentId": 7, "text": "legacy"}]}
    )
    response = await get(client, "/10/comments")
    assert response.status_code == 200 and response.json()["comments"][0]["id"] == 7
