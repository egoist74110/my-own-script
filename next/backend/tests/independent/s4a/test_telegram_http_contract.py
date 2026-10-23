"""S4-A isolated HTTP boundary contract for the Telegram Bot API adapter."""

import asyncio

import httpx
import pytest

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
API_HOST = "api.telegram.org"


def _adapter_types():
    from toolbox_backend.adapters.telegram_http import TelegramError, TelegramHTTP

    return TelegramHTTP, TelegramError


def _call(coro):
    return asyncio.run(coro)


def test_token_is_in_fixed_origin_path_and_request_returns_bot_api_result():
    TelegramHTTP, _ = _adapter_types()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"id": 5}})

    async def scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(handler))
        try:
            result = await client.request("getMe")
            return result
        finally:
            await client.close()

    assert _call(scenario()) == {"id": 5}
    assert len(seen) == 1
    request = seen[0]
    assert request.url.scheme == "https"
    assert request.url.host == API_HOST
    assert str(request.url) == f"https://{API_HOST}/bot{TOKEN}/getMe"
    assert "Authorization" not in request.headers


def test_redirect_is_rejected_without_following_and_error_does_not_leak_token():
    TelegramHTTP, TelegramError = _adapter_types()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/collect"})

    async def scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(handler))
        try:
            await client.request("getMe")
        finally:
            await client.close()

    with pytest.raises(TelegramError) as caught:
        _call(scenario())
    assert len(seen) == 1
    assert caught.value.category == "bad_response"
    assert TOKEN not in str(caught.value)
    assert "evil.example" not in str(caught.value)


def test_response_size_limit_rejects_oversized_body_without_echoing_body():
    TelegramHTTP, TelegramError = _adapter_types()
    marker = "OVERSIZED_PRIVATE_RESPONSE_MARKER"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=(marker + "x" * (2 * 1024 * 1024)).encode())

    async def scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(handler))
        try:
            await client.request("getMe")
        finally:
            await client.close()

    with pytest.raises(TelegramError) as caught:
        _call(scenario())
    assert caught.value.category == "bad_response"
    assert marker not in str(caught.value)
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "payload", "category"),
    [
        (409, {"ok": False, "description": "Conflict: another getUpdates request"}, "conflict"),
        (401, {"ok": False, "description": f"Unauthorized {TOKEN}"}, "unauthorized"),
    ],
)
def test_conflict_and_unauthorized_have_fixed_sanitized_categories(status, payload, category):
    TelegramHTTP, TelegramError = _adapter_types()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    async def scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(handler))
        try:
            await client.request("getUpdates", {"timeout": 0})
        finally:
            await client.close()

    with pytest.raises(TelegramError) as caught:
        _call(scenario())
    assert caught.value.category == category
    assert TOKEN not in caught.value.description


def test_rate_limit_exposes_retry_after_but_not_remote_description():
    TelegramHTTP, TelegramError = _adapter_types()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"ok": False, "description": f"retry {TOKEN}", "parameters": {"retry_after": 17}},
        )

    async def scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(handler))
        try:
            await client.request("sendMessage", {"chat_id": 1, "text": "test"})
        finally:
            await client.close()

    with pytest.raises(TelegramError) as caught:
        _call(scenario())
    assert caught.value.category == "rate_limited"
    assert caught.value.retry_after == 17
    assert TOKEN not in caught.value.description


def test_transport_exception_url_is_not_exposed_or_chained():
    TelegramHTTP, TelegramError = _adapter_types()
    private_url = f"https://{API_HOST}/bot{TOKEN}/getUpdates?offset=private"

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed URL {private_url}")

    async def scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(handler))
        try:
            await client.request("getUpdates")
        finally:
            await client.close()

    with pytest.raises(TelegramError) as caught:
        _call(scenario())
    rendered = f"{caught.value!r} {caught.value} {caught.value.description}"
    assert TOKEN not in rendered
    assert private_url not in rendered
    assert caught.value.__cause__ is None


def test_timeout_and_invalid_json_return_fixed_bad_response_without_leaks():
    TelegramHTTP, TelegramError = _adapter_types()

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout at https://{API_HOST}/bot{TOKEN}/getMe")

    async def timeout_scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(timeout_handler))
        try:
            await client.request("getMe")
        finally:
            await client.close()

    with pytest.raises(TelegramError) as timed_out:
        _call(timeout_scenario())
    assert timed_out.value.category == "timeout"
    assert TOKEN not in str(timed_out.value)
    assert timed_out.value.__cause__ is None

    marker = "INVALID_JSON_PRIVATE_MARKER"

    def bad_json_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=f"{{invalid {marker}".encode())

    async def bad_json_scenario():
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(bad_json_handler))
        try:
            await client.request("getMe")
        finally:
            await client.close()

    with pytest.raises(TelegramError) as bad_json:
        _call(bad_json_scenario())
    assert bad_json.value.category == "bad_response"
    assert marker not in str(bad_json.value)


def test_client_close_releases_mock_transport():
    TelegramHTTP, _ = _adapter_types()

    class TrackingTransport(httpx.MockTransport):
        def __init__(self):
            super().__init__(lambda _request: httpx.Response(200, json={"ok": True, "result": 1}))
            self.closed = False

        async def aclose(self):
            self.closed = True
            await super().aclose()

    transport = TrackingTransport()

    async def scenario():
        client = TelegramHTTP(TOKEN, transport=transport)
        assert await client.request("getMe") == 1
        await client.close()

    _call(scenario())
    assert transport.closed


def test_send_message_concurrency_is_bounded_to_two():
    TelegramHTTP, _ = _adapter_types()
    entered = 0
    maximum = 0
    both_entered: asyncio.Event
    release: asyncio.Event

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal entered, maximum
        entered += 1
        maximum = max(maximum, entered)
        if entered == 2:
            both_entered.set()
        await release.wait()
        entered -= 1
        return httpx.Response(200, json={"ok": True, "result": True})

    async def scenario():
        nonlocal both_entered, release
        both_entered = asyncio.Event()
        release = asyncio.Event()
        client = TelegramHTTP(TOKEN, transport=httpx.MockTransport(handler))
        tasks = [
            asyncio.create_task(client.request("sendMessage", {"chat_id": i, "text": "x"}))
            for i in range(4)
        ]
        try:
            await asyncio.wait_for(both_entered.wait(), timeout=1)
            assert maximum == 2
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await client.close()

    _call(scenario())
    assert maximum == 2
