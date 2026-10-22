import ssl

import httpx
import pytest

from toolbox_backend.adapters import ado_read
from toolbox_backend.adapters.ado_read import (
    ATTACHMENT_LIMIT,
    IMAGE_LIMIT,
    JSON_LIMIT,
    AdoFailure,
    AdoRead,
)
from toolbox_backend.domain.settings import Library

PAT = "FAKE_S2_HTTP_PAT_b8c07"
LIB = Library(id="lib:test", name="fake", base_url="https://ado.example.test/tfs")


class Stream(httpx.SyncByteStream):
    def __init__(self, count=1, chunk=b"x", tick=None):
        self.closed, self.read, self.count, self.chunk, self.tick = False, 0, count, chunk, tick

    def __iter__(self):
        for _ in range(self.count):
            self.read += 1
            if self.tick:
                self.tick()
            yield self.chunk

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "kind,limit", [("json", JSON_LIMIT), ("image", IMAGE_LIMIT), ("attachment", ATTACHMENT_LIMIT)]
)
@pytest.mark.parametrize("declared", [False, True])
def test_response_limit_stream_closed_with_or_without_content_length(kind, limit, declared):
    stream = Stream(count=limit // 65536 + 2, chunk=b"x" * 65536)
    headers = {"Content-Length": str(limit + 1)} if declared else {}
    client = AdoRead(
        httpx.MockTransport(lambda _: httpx.Response(200, headers=headers, stream=stream))
    )
    with pytest.raises(AdoFailure) as caught:
        if kind == "json":
            client.request_json(LIB, PAT, "GET", ["_apis", "wit"])
        else:
            client.fetch_media(LIB, PAT, LIB.base_url + "/media", kind)
    assert caught.value.category == "too_large" and stream.closed
    assert stream.read == (0 if declared else limit // 65536 + 1)


@pytest.mark.parametrize("kind,seconds", [("json", 15), ("image", 30), ("attachment", 30)])
def test_small_drip_checks_total_deadline_and_closes(kind, seconds, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(ado_read.time, "monotonic", lambda: now[0])

    def tick():
        now[0] += 0.5

    stream = Stream(count=100, chunk=b" ", tick=tick)
    client = AdoRead(httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    with pytest.raises(AdoFailure) as caught:
        if kind == "json":
            client.request_json(LIB, PAT, "GET", ["_apis", "wit"])
        else:
            client.fetch_media(LIB, PAT, LIB.base_url + "/media", kind)
    assert caught.value.category == "timeout"
    assert stream.closed and stream.read <= seconds * 2


@pytest.mark.parametrize(
    "bad", ["..", ".", "../outside", "a/b", "a\\b", "bad\x00", "%2e%2e", "%252e%252e"]
)
def test_invalid_segments_cannot_escape_base_path(bad):
    seen = []
    adapter = AdoRead(httpx.MockTransport(lambda request: seen.append(request)))
    with pytest.raises(AdoFailure):
        adapter.request_json(LIB, PAT, "GET", [bad])
    assert seen == []


@pytest.mark.parametrize(
    "target",
    [
        "/outside/file",
        "https://ado.example.test/tfs-evil/file",
        "/tfs/%2e%2e/private",
        "//other.example.test/tfs/x",
    ],
)
def test_redirect_path_boundary_rechecked_without_second_request(target):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": target})

    with pytest.raises(AdoFailure) as caught:
        AdoRead(httpx.MockTransport(handler)).fetch_media(
            LIB, PAT, LIB.base_url + "/image", "image"
        )
    assert caught.value.category == "blocked_origin" and len(requests) == 1


@pytest.mark.parametrize("payload", [b"not json", b"[]", b"null", b'"str"'])
def test_invalid_json_returns_safe_bad_response(payload):
    client = AdoRead(httpx.MockTransport(lambda _: httpx.Response(200, content=payload)))
    with pytest.raises(AdoFailure) as caught:
        client.request_json(LIB, PAT, "GET", ["_apis"])
    assert caught.value.category == "bad_response" and payload.decode() not in str(caught.value)


@pytest.mark.parametrize(
    "exc,category",
    [
        (httpx.ReadTimeout(PAT), "timeout"),
        (httpx.ConnectTimeout(PAT), "timeout"),
        (httpx.ConnectError("certificate " + PAT), "tls"),
        (ssl.SSLError(PAT), "tls"),
        (httpx.ConnectError(PAT), "network"),
        (httpx.RemoteProtocolError(PAT), "network"),
    ],
)
def test_fixed_failure_messages_never_echo_transport_errors(exc, category):
    def handler(_):
        raise exc

    with pytest.raises(AdoFailure) as caught:
        AdoRead(httpx.MockTransport(handler)).request_json(LIB, PAT, "GET", ["_apis"])
    assert caught.value.category == category and PAT not in str(caught.value)
