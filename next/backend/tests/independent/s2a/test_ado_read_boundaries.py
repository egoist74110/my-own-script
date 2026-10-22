import base64

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoFailure, AdoRead
from toolbox_backend.domain.settings import Library

PAT = "FAKE_S2A_ADO_PAT_943"


def library(base_url="https://ado.example/root"):
    return Library(id="lib:test", name="Example", base_url=base_url)


def test_json_reads_encode_each_path_segment_and_never_follow_redirects():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://outside.example/collect"})

    ado = AdoRead(httpx.MockTransport(handler))
    with pytest.raises(AdoFailure) as failure:
        ado.request_json(
            library(),
            PAT,
            "POST",
            ("Collection One", "Project & X", "_apis", "wit", "wiql"),
            {"api-version": "7.0"},
            {"query": "SELECT [System.Id]"},
        )

    assert failure.value.category == "redirect"
    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == "ado.example"
    assert request.url.raw_path.decode().partition("?")[0] == (
        "/root/Collection%20One/Project%20%26%20X/_apis/wit/wiql"
    )
    assert request.headers["authorization"] == "Basic " + base64.b64encode(
        (":" + PAT).encode()
    ).decode()
    assert request.url.params["api-version"] == "7.0"


@pytest.mark.parametrize(
    "url",
    [
        "https://ado.example/root-sibling/image.png",
        "https://user:pass@ado.example/root/image.png",
        "http://ado.example/root/image.png",
        "https://outside.example/root/image.png",
    ],
)
def test_media_initial_url_must_stay_inside_library_origin_and_path_prefix(url):
    seen = []
    ado = AdoRead(httpx.MockTransport(lambda request: seen.append(request)))

    with pytest.raises(AdoFailure) as failure:
        ado.fetch_media(library(), PAT, url, "image")

    assert failure.value.category == "blocked_origin"
    assert seen == []


@pytest.mark.parametrize(
    "target",
    [
        "https://cdn.example/image.png",
        "http://ado.example/root/image.png",
        "https://user:pass@ado.example/root/image.png",
    ],
)
def test_cross_origin_downgrade_and_userinfo_redirects_are_blocked_before_target_request(target):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": target})

    ado = AdoRead(httpx.MockTransport(handler))
    with pytest.raises(AdoFailure) as failure:
        ado.fetch_media(library(), PAT, "https://ado.example/root/image.png", "image")

    assert failure.value.category == "blocked_origin"
    assert len(seen) == 1
    assert seen[0].url.host == "ado.example"
    assert seen[0].headers["authorization"].startswith("Basic ")


def test_same_origin_media_redirect_chain_allows_five_hops():
    seen = []

    def handler(request):
        seen.append(request)
        hop = len(seen) - 1
        if hop < 5:
            return httpx.Response(302, headers={"Location": f"/root/image-{hop + 1}.png"})
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nimage")

    body = AdoRead(httpx.MockTransport(handler)).fetch_media(
        library(), PAT, "https://ado.example/root/image.png?sig=test", "image"
    )

    assert body == b"\x89PNG\r\n\x1a\nimage"
    assert len(seen) == 6
    assert seen[0].url.params["download"] == "true"
    assert all(request.url.host == "ado.example" for request in seen)
    assert all(request.headers["authorization"].startswith("Basic ") for request in seen)


def test_sixth_same_origin_media_redirect_returns_redirect_category():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": f"/root/next-{len(seen)}"})

    with pytest.raises(AdoFailure) as failure:
        AdoRead(httpx.MockTransport(handler)).fetch_media(
            library(), PAT, "https://ado.example/root/image.png", "image"
        )

    assert failure.value.category == "redirect"
    assert len(seen) == 6


@pytest.mark.parametrize("content_length", [True, False])
def test_media_body_limit_is_enforced_with_and_without_content_length(content_length):
    body = b"x" * ((10 << 20) + 1)
    headers = {"Content-Length": str(len(body))} if content_length else {}
    ado = AdoRead(
        httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(body), headers=headers))
    )

    with pytest.raises(AdoFailure) as failure:
        ado.fetch_media(library(), PAT, "https://ado.example/root/image.png", "image")

    assert failure.value.category == "too_large"


def test_attachment_content_length_limit_is_enforced_before_body_read():
    ado = AdoRead(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=b"small",
                headers={"Content-Length": str((25 << 20) + 1)},
            )
        )
    )

    with pytest.raises(AdoFailure) as failure:
        ado.fetch_media(library(), PAT, "https://ado.example/root/file.bin", "attachment")

    assert failure.value.category == "too_large"


def test_json_body_limit_is_four_mibibytes():
    oversized = b'{"value":[]}' + b" " * ((4 << 20) + 1)
    ado = AdoRead(httpx.MockTransport(lambda _: httpx.Response(200, content=oversized)))

    with pytest.raises(AdoFailure) as failure:
        ado.request_json(library(), PAT, "GET", ("Collection", "Project", "_apis"))

    assert failure.value.category == "too_large"
