"""Temporary Telegram app fixtures with in-memory credentials and MockTransport."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings

BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
APP_TOKEN = "telegram-s4a-app-token"


class MockBot:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.handler = self._default

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self.handler(request)

    async def _default(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 123456789, "username": "test_bot"}})
        if method == "getWebhookInfo":
            return httpx.Response(200, json={"ok": True, "result": {"url": ""}})
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": []})
        if method in {"sendMessage", "editMessageText", "answerCallbackQuery"}:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        if method == "deleteWebhook":
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": True, "result": True})


@dataclass
class TelegramContext:
    app: object
    client: httpx.AsyncClient
    bot: MockBot
    credentials: MemoryCredentials
    legacy_credentials: MemoryCredentials
    data_dir: Path


@asynccontextmanager
async def open_telegram_app(
    tmp_path: Path,
    *,
    data_dir: Path | None = None,
    bot: MockBot | None = None,
    credentials: MemoryCredentials | None = None,
    legacy_credentials: MemoryCredentials | None = None,
    dev: bool = False,
) -> AsyncIterator[TelegramContext]:
    bot = bot or MockBot()
    credentials = credentials or MemoryCredentials()
    legacy_credentials = legacy_credentials or MemoryCredentials()
    directory = data_dir or tmp_path / "data"
    app = create_app(
        Settings(
            token=APP_TOKEN,
            port=1234,
            dev=dev,
            data_dir=directory,
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=credentials,
        legacy_credentials=legacy_credentials,
        telegram_transport=httpx.MockTransport(bot),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": f"Bearer {APP_TOKEN}"},
        ) as client:
            yield TelegramContext(app, client, bot, credentials, legacy_credentials, directory)


@pytest.fixture
def telegram_app_factory():
    return open_telegram_app
