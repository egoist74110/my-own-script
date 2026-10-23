"""The sole Bot API boundary: fixed origin, bounded streams, URL-free failures."""

import asyncio
import logging
import re

import httpx

from toolbox_backend.logging_setup import redact_exception, register_secret

_METHODS = frozenset({
    'getMe', 'getWebhookInfo', 'deleteWebhook', 'getUpdates', 'sendMessage',
    'editMessageText', 'answerCallbackQuery', 'sendMediaGroup',
})
TOKEN_RE = re.compile(r'^\d{5,16}:[A-Za-z0-9_-]{30,64}$')


class TelegramError(Exception):
    def __init__(self, category, description='', *, retry_after=None, connect_failed=False):
        self.category = category
        # Remote descriptions can embed arbitrary URLs, including a credential path.
        self.description = re.sub(
            r'https?://\S+', '[URL]', redact_exception(description)
        )[:200]
        self.retry_after = retry_after
        self.connect_failed = connect_failed
        super().__init__(category + (': ' + self.description if self.description else ''))


class TelegramHTTP:
    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None):
        if not TOKEN_RE.fullmatch(token):
            raise TelegramError('bad_response', 'Bot 凭据格式无效')
        register_secret(token)
        self._token = token
        self._poll = asyncio.Semaphore(1)
        self._send = asyncio.Semaphore(2)
        self._media = asyncio.Semaphore(1)
        # Telegram alone follows environment/macOS proxies; ADO remains isolated.
        self._client = httpx.AsyncClient(
            transport=transport, trust_env=True, follow_redirects=False,
            timeout=httpx.Timeout(35, connect=5, pool=5),
        )
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)

    async def request(self, method: str, payload: dict | None = None):
        if method not in _METHODS:
            raise TelegramError('bad_response', '不支持的 Bot API 方法')
        semaphore = self._poll if method == 'getUpdates' else (
            self._media if method == 'sendMediaGroup' else self._send
        )
        limit = 1024 * 1024 if method == 'getUpdates' else 64 * 1024
        try:
            async with semaphore, asyncio.timeout(40):
                async with self._client.stream(
                    'POST', f'https://api.telegram.org/bot{self._token}/{method}',
                    json=payload or {},
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > limit:
                            raise TelegramError('bad_response', 'Bot API 响应超过限额')
                        body.extend(chunk)
                    try:
                        import json
                        data = json.loads(body)
                    except (ValueError, UnicodeError):
                        data = None
                    code = response.status_code
                    if isinstance(data, dict) and data.get('ok') is False:
                        remote_code = data.get('error_code')
                        if type(remote_code) is int:
                            code = remote_code
                    if code >= 300 or not isinstance(data, dict) or data.get('ok') is not True:
                        category = (
                            'conflict' if code == 409 else
                            'unauthorized' if code in (401, 404) else
                            'rate_limited' if code == 429 else
                            'http_5xx' if code >= 500 else
                            'http_4xx' if 400 <= code < 500 else 'bad_response'
                        )
                        description = data.get('description', '') if isinstance(data, dict) else ''
                        parameters = data.get('parameters') if isinstance(data, dict) else None
                        retry = (
                            parameters.get('retry_after')
                            if isinstance(parameters, dict) else None
                        )
                        if type(retry) is not int or retry < 0:
                            retry = None
                        raise TelegramError(
                            category, description if isinstance(description, str) else '',
                            retry_after=retry,
                        )
                    if 'result' not in data:
                        raise TelegramError('bad_response', 'Bot API 响应无结果')
                    return data['result']
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            failure = TelegramError('network', connect_failed=True)
        except (httpx.TimeoutException, TimeoutError):
            failure = TelegramError('timeout')
        except httpx.HTTPError:
            failure = TelegramError('network')
        # Raise outside the handler: even __context__ must not retain the httpx URL.
        raise failure

    async def close(self):
        await self._client.aclose()
