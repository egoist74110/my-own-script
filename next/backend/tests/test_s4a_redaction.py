from urllib.parse import quote

import pytest

from toolbox_backend.logging_setup import contains_secret, redact_exception, register_secret


@pytest.mark.parametrize('text', [
    'https://api.telegram.org/bot123456:unregistered_secret/getUpdates',
    '/bot123456%3Aunregistered_secret/sendMessage',
    'Authorization: Bearer unregistered_secret',
    "{'Proxy-Authorization': 'Basic unregistered_secret'}",
    '"X-Api-Token": "unregistered_secret"',
])
def test_telegram_patterns_do_not_need_registration(text):
    assert 'unregistered_secret' not in redact_exception(text)


def test_registered_url_encoded_secret_and_exception_chain():
    token = '7654321:' + 'regression_S4_token_123456789012345'
    register_secret(token)
    encoded = quote(token, safe='')
    assert contains_secret(encoded)
    inner = RuntimeError(encoded)
    outer = RuntimeError('outer')
    outer.__cause__ = inner
    assert encoded not in redact_exception(outer)
    assert '***' in redact_exception(outer)


async def test_http_transport_exception_chain_does_not_retain_request_url():
    import httpx

    from toolbox_backend.adapters.telegram_http import TelegramError, TelegramHTTP

    def fail(request):
        raise httpx.ReadTimeout(str(request.url), request=request)

    client = TelegramHTTP(
        '888888:' + 'safe_mock_token_12345678901234567890',
        transport=httpx.MockTransport(fail),
    )
    try:
        with pytest.raises(TelegramError) as caught:
            await client.request('getUpdates')
        assert 'api.telegram.org' not in redact_exception(caught.value)
        assert caught.value.__context__ is None
    finally:
        await client.close()
