import asyncio
import threading
import time

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead, within
from toolbox_backend.adapters.html_sanitize import sanitize_html
from toolbox_backend.domain.settings import Library
from toolbox_backend.services import work_items

PAT = "FAKE_S2D_PAT_72"
LIB = Library(id="lib:s2d", name="S2-D", base_url="https://ado.example/root")


@pytest.mark.parametrize(
    "escaped",
    ["r%6Fot", "root%2Fchild", "root%2fchild", "root%5Cchild", "root%5cchild", "root%2Echild", "root%2echild"],
)
def test_within_rejects_encoded_prefix_and_path_separator_variants(escaped):
    assert not within(LIB, f"https://ado.example/{escaped}/item")


def test_within_preserves_non_traversal_double_encoded_slash():
    assert within(LIB, "https://ado.example/root/%252F/item")


def test_within_rejects_double_encoded_dot_traversal():
    assert not within(LIB, "https://ado.example/root/%252e%252e/item")


def test_within_rejects_double_encoded_nonreserved_prefix_escape():
    assert not within(LIB, "https://ado.example/r%256Fot/item")


@pytest.mark.parametrize("encoded", ["%2f", "%2F", "%5c", "%5C", "%2e", "%2E"])
def test_within_rejects_encoded_slash_backslash_and_dot_case_insensitively(encoded):
    assert not within(LIB, f"https://ado.example/root/a{encoded}b/item")


def test_within_allows_build_url_encoded_spaces_and_chinese_segments():
    seen = []
    client = AdoRead(httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200, json={"value": []}))[1]))

    payload = client.request_json(LIB, PAT, "GET", ["Collection One", "项目 Alpha", "_apis", "projects"])

    assert payload == {"value": []}
    raw_path = seen[0].url.raw_path.decode().partition("?")[0]
    assert raw_path == "/root/Collection%20One/%E9%A1%B9%E7%9B%AE%20Alpha/_apis/projects"


@pytest.mark.parametrize("key_or_value", ["key", "value"])
def test_json_redaction_replaces_isolated_surrogates_in_keys_and_values(key_or_value):
    response_body = b'{"bad\\ud800":"value"}' if key_or_value == "key" else b'{"safe":"bad\\udfff"}'
    client = AdoRead(httpx.MockTransport(lambda _: httpx.Response(200, content=response_body)))

    payload = client.request_json(LIB, PAT, "GET", ["_apis"])

    expected = "bad\ufffd"
    assert expected in (payload if key_or_value == "key" else payload.values())


@pytest.mark.parametrize("bad_relations", [{"added": "bad", "removed": []}, {"added": [], "removed": {}}])
async def test_updates_malformed_relation_lists_return_502(s2dctx, bad_relations):
    project_id = await s2dctx.create_project()
    s2dctx.mock_ado(lambda _: httpx.Response(200, json={"value": [{"id": 1, "relations": bad_relations}]}))

    response = await s2dctx.client.get("/api/work-items/1/updates", params={"project_id": project_id})

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["category"] == "bad_response"


@pytest.mark.parametrize("bad_fields", ["not-an-object", [], "", None, False])
async def test_children_malformed_child_fields_return_502(s2dctx, bad_fields):
    project_id = await s2dctx.create_project()

    def respond(request):
        if request.url.path.endswith("/workitems/1"):
            return httpx.Response(200, json={"id": 1, "fields": {}, "relations": [{"rel": "System.LinkTypes.Hierarchy-Forward", "url": "https://ado.example/root/_apis/wit/workItems/2"}]})
        return httpx.Response(200, json={"value": [{"id": 2, "fields": bad_fields}]})

    s2dctx.mock_ado(respond)
    response = await s2dctx.client.get("/api/work-items/1/children", params={"project_id": project_id})

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["category"] == "bad_response"


async def test_detail_response_combines_image_and_attachment_cap_at_200(s2dctx):
    project_id = await s2dctx.create_project()
    html_images = "".join(f'<img src="https://ado.example/root/image-{i}.png">' for i in range(199))
    relations = [
        {"rel": "AttachedFile", "url": f"https://ado.example/root/file-{i}.bin", "attributes": {"name": f"file-{i}.bin"}}
        for i in range(2)
    ]
    item = {"id": 1, "rev": 1, "fields": {"System.Description": html_images}, "relations": relations}
    s2dctx.mock_ado(lambda _: httpx.Response(200, json=item))

    response = await s2dctx.client.get("/api/work-items/1", params={"project_id": project_id})

    assert response.status_code == 200, response.text
    assert len(s2dctx.app.state.work_items_service.media.entries) == 200
    assert sum(bool(a["media_id"]) for a in response.json()["attachments"]) == 1
    assert response.json()["attachments"][1]["media_id"] is None


async def test_detail_replaces_images_over_single_response_cap(s2dctx):
    project_id = await s2dctx.create_project()
    html_images = "".join(f'<img src="https://ado.example/root/image-{i}.png">' for i in range(201))
    item = {"id": 1, "rev": 1, "fields": {"System.Description": html_images}, "relations": []}
    s2dctx.mock_ado(lambda _: httpx.Response(200, json=item))

    response = await s2dctx.client.get("/api/work-items/1", params={"project_id": project_id})

    assert response.status_code == 200, response.text
    assert len(s2dctx.app.state.work_items_service.media.entries) == 200
    assert "[图片过多未显示]" in response.json()["html"]["description"]["html"]


async def test_detail_html_fields_share_single_response_cap(s2dctx):
    project_id = await s2dctx.create_project()
    def images(prefix):
        return "".join(
            f'<img src="https://ado.example/root/{prefix}-{i}.png">' for i in range(100)
        )
    item = {
        "id": 1,
        "rev": 1,
        "fields": {
            "System.Description": images("description"),
            "Microsoft.VSTS.TCM.ReproSteps": images("steps"),
            "Microsoft.VSTS.Common.AcceptanceCriteria": images("criteria"),
        },
        "relations": [],
    }
    s2dctx.mock_ado(lambda _: httpx.Response(200, json=item))

    response = await s2dctx.client.get("/api/work-items/1", params={"project_id": project_id})

    assert response.status_code == 200, response.text
    assert len(s2dctx.app.state.work_items_service.media.entries) == 200
    assert "[图片过多未显示]" in response.json()["html"]["acceptance_criteria"]["html"]


async def test_html_candidate_registration_stays_on_event_loop_thread(monkeypatch, s2dctx):
    project_id = await s2dctx.create_project()
    service = s2dctx.app.state.work_items_service
    original = service.media.register
    registration_threads = []
    loop_thread = threading.get_ident()

    def track_register(*args, **kwargs):
        registration_threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(service.media, "register", track_register)
    html_images = "".join(f'<img src="https://ado.example/root/{i}.png">' for i in range(3))
    s2dctx.mock_ado(
        lambda _: httpx.Response(200, json={"id": 1, "fields": {"System.Description": html_images}})
    )

    response = await s2dctx.client.get("/api/work-items/1", params={"project_id": project_id})

    assert response.status_code == 200, response.text
    assert registration_threads and set(registration_threads) == {loop_thread}


async def test_comments_share_media_cap_across_comment_list(s2dctx):
    project_id = await s2dctx.create_project()
    comments = [
        {"id": i + 1, "text": "".join(f'<img src="https://ado.example/root/{i}-{j}.png">' for j in range(101))}
        for i in range(2)
    ]
    s2dctx.mock_ado(lambda _: httpx.Response(200, json={"comments": comments}))

    response = await s2dctx.client.get("/api/work-items/1/comments", params={"project_id": project_id})

    assert response.status_code == 200, response.text
    assert len(s2dctx.app.state.work_items_service.media.entries) == 200
    assert "[图片过多未显示]" in response.json()["comments"][1]["html"]


async def test_html_sanitization_does_not_block_event_loop(monkeypatch, s2dctx):
    project_id = await s2dctx.create_project()
    started, release = threading.Event(), threading.Event()
    original = work_items.sanitize_html

    def slow_sanitize(value, register):
        started.set()
        release.wait(0.5)
        return original(value, register)

    monkeypatch.setattr(work_items, "sanitize_html", slow_sanitize)
    s2dctx.mock_ado(lambda _: httpx.Response(200, json={"id": 1, "fields": {"System.Description": "<p>safe</p>"}}))
    detail_task = asyncio.create_task(
        s2dctx.client.get("/api/work-items/1", params={"project_id": project_id})
    )
    started_at = time.monotonic()
    try:
        assert await asyncio.to_thread(started.wait, 1), "sanitizer did not start"
        health_task = asyncio.create_task(s2dctx.client.get("/health"))
        done, _ = await asyncio.wait({health_task}, timeout=0.2)
        elapsed = time.monotonic() - started_at
        assert health_task in done, "health did not complete while sanitization was held"
        health = await health_task
        assert health.status_code == 200
        assert elapsed < 0.2
        assert (await detail_task).status_code == 200
    finally:
        release.set()
        if not detail_task.done():
            await detail_task


def test_sanitizer_drops_generic_attributes():
    cleaned = sanitize_html('<p lang="zh" title="tip" dir="rtl">safe</p>', lambda _: (None, ""))

    assert cleaned.html is not None
    assert all(attribute not in cleaned.html for attribute in ("lang=", "title=", "dir="))


@pytest.mark.parametrize(
    ("route", "payload", "expected"),
    [
        ("detail", b'{"id":1,"fields":{"System.Title":"\\ud800"}}', "title"),
        ("description", b'{"id":1,"fields":{"System.Description":"before \\ud800 after"}}', "description"),
        ("updates", b'{"value":[{"id":1,"fields":{"bad\\ud800":{"oldValue":"x"}}}]}', "update_key"),
    ],
)
async def test_remote_surrogates_are_replaced_before_response(s2dctx, route, payload, expected):
    project_id = await s2dctx.create_project()
    s2dctx.mock_ado(lambda _: httpx.Response(200, content=payload))

    suffix = "/1/updates" if route == "updates" else "/1"
    response = await s2dctx.client.get(f"/api/work-items{suffix}", params={"project_id": project_id})

    assert response.status_code == 200, response.text
    body = response.json()
    if expected == "title":
        assert body["title"] == "\ufffd"
    elif expected == "description":
        assert "before \ufffd after" in body["html"]["description"]["html"]
    else:
        assert body["updates"][0]["fields"][0]["name"] == "bad\ufffd"
