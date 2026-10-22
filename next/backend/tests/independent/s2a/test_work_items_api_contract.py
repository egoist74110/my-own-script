import httpx
import pytest

PAT = "FAKE_S2A_ADO_PAT_943"
PNG = b"\x89PNG\r\n\x1a\nfixture-png"


def work_item(*, description="", relations=None):
    return {
        "id": 41,
        "rev": 7,
        "fields": {
            "System.Title": "Test item",
            "System.WorkItemType": "Bug",
            "System.State": "Active",
            "System.Description": description,
        },
        "relations": relations or [],
    }


async def detail_with(s2ctx, payload):
    project_id = await s2ctx.create_project()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    s2ctx.mock_ado(handler)
    response = await s2ctx.client.get(
        "/api/work-items/41", params={"project_id": project_id}
    )
    assert response.status_code == 200, response.text
    return project_id, response, requests


async def test_detail_html_is_sanitized_and_media_is_opaque_magic_checked_no_store(s2ctx):
    image_url = "https://ado.example/root/Collection%20One/_apis/attachment?id=local"
    description = (
        '<p onclick="x">safe<script>alert(1)</script>'
        '<a href="javascript:alert(1)">bad link</a>'
        '<img src="' + image_url + '" alt="diagram" onerror="alert(2)">'
        '<img src="https://evil.example/x.png">'
        '<img src="data:image/png;base64,AAAA">'
        '<svg onload="alert(3)"><text>secret</text></svg>'
        '<iframe src="https://evil.example">private</iframe>'
        '<div style="background:url(javascript:alert(4))">styled</div>'
        '<img src="https://ado.example/root/Collection%20One/a.png" '
        'srcset="https://evil.example/x 2x">'
        '</p>'
    )
    project_id = await s2ctx.create_project()
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/workitems/41"):
            return httpx.Response(200, json=work_item(description=description))
        return httpx.Response(200, content=PNG, headers={"Content-Type": "image/svg+xml"})

    s2ctx.mock_ado(handler)
    response = await s2ctx.client.get(
        "/api/work-items/41", params={"project_id": project_id}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    cleaned = body["html"]["description"]["html"]
    assert "alert(" not in cleaned
    assert "secret" not in cleaned and "private" not in cleaned
    assert "javascript:" not in cleaned
    assert "onerror" not in cleaned and "onclick" not in cleaned
    assert "style=" not in cleaned and "srcset" not in cleaned
    assert 'data-media-id="' in cleaned
    assert "data-blocked-origin=\"https://evil.example:443\"" in cleaned
    assert "[内嵌图片未显示]" in cleaned
    assert image_url not in response.text
    assert PAT not in response.text
    assert seen[0].url.raw_path.decode().startswith(
        "/root/Collection%20One/Project%20%26%20X/_apis/wit/workitems/41?"
    )

    media_id = cleaned.split('data-media-id="', 1)[1].split('"', 1)[0]
    media_response = await s2ctx.client.get(f"/api/work-items/media/{media_id}")
    assert media_response.status_code == 200, media_response.text
    assert media_response.content == PNG
    assert media_response.headers["content-type"] == "image/png"
    assert media_response.headers["x-content-type-options"] == "nosniff"
    assert media_response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert media_response.headers["cache-control"] == "private, no-store"
    assert all(request.url.host == "ado.example" for request in seen)
    assert all(request.headers["authorization"].startswith("Basic ") for request in seen)


@pytest.mark.parametrize(
    "target",
    [
        "https://cdn.example/image.png",
        "http://ado.example/root/Collection%20One/image.png",
        "https://user:pass@ado.example/root/Collection%20One/image.png",
    ],
)
async def test_media_redirect_to_other_origin_downgrade_or_userinfo_is_blocked_without_follow(
    s2ctx, target
):
    url = "https://ado.example/root/Collection%20One/attachment.png"
    project_id = await s2ctx.create_project()
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/workitems/41"):
            return httpx.Response(200, json=work_item(description=f'<img src="{url}">'))
        return httpx.Response(302, headers={"Location": target})

    s2ctx.mock_ado(handler)
    detail = await s2ctx.client.get(
        "/api/work-items/41", params={"project_id": project_id}
    )
    media_id = detail.json()["html"]["description"]["html"].split(
        'data-media-id="', 1
    )[1].split('"', 1)[0]
    response = await s2ctx.client.get(f"/api/work-items/media/{media_id}")

    assert response.status_code == 502
    assert response.json()["detail"]["category"] == "blocked_origin"
    assert PAT not in response.text
    assert len(seen) == 2
    assert all(request.url.host == "ado.example" for request in seen)


async def test_svg_is_not_served_as_an_image(s2ctx):
    project_id = await s2ctx.create_project()
    image_url = "https://ado.example/root/Collection%20One/unsafe.svg"

    def handler(request):
        if request.url.path.endswith("/workitems/41"):
            return httpx.Response(200, json=work_item(description=f'<img src="{image_url}">'))
        return httpx.Response(200, content=b'<svg onload="alert(1)"></svg>')

    s2ctx.mock_ado(handler)
    detail = await s2ctx.client.get(
        "/api/work-items/41", params={"project_id": project_id}
    )
    media_id = detail.json()["html"]["description"]["html"].split(
        'data-media-id="', 1
    )[1].split('"', 1)[0]
    response = await s2ctx.client.get(f"/api/work-items/media/{media_id}")

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_media"
    assert "alert(1)" not in response.text


async def test_attachment_filename_is_cleaned_and_delivered_as_download(s2ctx):
    project_id = await s2ctx.create_project()
    relations = [
        {
            "rel": "AttachedFile",
            "url": "https://ado.example/root/Collection%20One/file.txt",
            "attributes": {"name": "../report\r\nfinal.txt", "resourceSize": 12},
        }
    ]

    def handler(request):
        if request.url.path.endswith("/workitems/41"):
            return httpx.Response(200, json=work_item(relations=relations))
        return httpx.Response(200, content=b"attachment")

    s2ctx.mock_ado(handler)
    detail = await s2ctx.client.get(
        "/api/work-items/41", params={"project_id": project_id}
    )
    attachment = detail.json()["attachments"][0]
    assert attachment["name"] == "..reportfinal.txt"
    assert attachment["media_id"]
    response = await s2ctx.client.get(
        f"/api/work-items/media/{attachment['media_id']}"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    disposition = response.headers["content-disposition"]
    assert disposition == "attachment; filename*=UTF-8''..reportfinal.txt"
    assert "\r" not in disposition and "\n" not in disposition and "/" not in disposition


async def test_media_id_expires_when_its_project_is_removed_without_outbound_request(s2ctx):
    project_id = await s2ctx.create_project()
    requests = []
    image_url = "https://ado.example/root/Collection%20One/image.png"

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=work_item(description=f'<img src="{image_url}">'))

    s2ctx.mock_ado(handler)
    detail = await s2ctx.client.get(
        "/api/work-items/41", params={"project_id": project_id}
    )
    media_id = detail.json()["html"]["description"]["html"].split(
        'data-media-id="', 1
    )[1].split('"', 1)[0]
    removed = await s2ctx.client.delete(
        f"/api/ado/projects/{project_id}", params={"revision": await s2ctx.revision()}
    )
    assert removed.status_code == 200, removed.text
    requests.clear()

    response = await s2ctx.client.get(f"/api/work-items/media/{media_id}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "media_expired"
    assert requests == []


async def test_every_work_item_route_requires_bearer_before_outbound_io(s2ctx):
    paths = [
        "/api/work-items/columns",
        "/api/work-items?project_id=proj%3Amissing",
        "/api/work-items/41?project_id=proj%3Amissing",
        "/api/work-items/41/comments?project_id=proj%3Amissing",
        "/api/work-items/41/updates?project_id=proj%3Amissing",
        "/api/work-items/41/children?project_id=proj%3Amissing",
        "/api/work-items/media/unregistered-media-id",
    ]
    s2ctx.client.headers.pop("Authorization")
    for path in paths:
        response = await s2ctx.client.get(path)
        assert response.status_code == 401, (path, response.status_code, response.text)
    assert s2ctx.requests == []
