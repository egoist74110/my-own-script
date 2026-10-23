"""The fake Telegram development routes exist only behind all three dev gates."""

import pytest


async def test_fake_telegram_routes_are_absent_in_normal_app(tmp_path, telegram_app_factory):
    async with telegram_app_factory(tmp_path, dev=False) as ctx:
        injected = await ctx.client.post(
            "/api/dev/telegram/inject",
            json={"chat_id": "7001", "text": "/help"},
        )
        sent = await ctx.client.get("/api/dev/telegram/sent")
        assert injected.status_code == 404
        assert sent.status_code == 404


async def test_fake_telegram_setting_requires_dev_mode(tmp_path, telegram_app_factory, monkeypatch):
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_TELEGRAM", "1")
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    with pytest.raises(ValueError, match="requires --dev and memory credentials"):
        async with telegram_app_factory(tmp_path, dev=False):
            pass


async def test_fake_telegram_setting_requires_memory_credential_adapter(
    tmp_path, telegram_app_factory, monkeypatch
):
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_TELEGRAM", "1")
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    with pytest.raises(ValueError, match="requires --dev and memory credentials"):
        async with telegram_app_factory(tmp_path, dev=True, credentials=object()):
            pass


async def test_fake_telegram_routes_exist_only_when_all_three_gates_are_open(
    tmp_path, telegram_app_factory, monkeypatch
):
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_TELEGRAM", "1")
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    async with telegram_app_factory(tmp_path, dev=True) as ctx:
        injected = await ctx.client.post(
            "/api/dev/telegram/inject",
            json={"update": {"update_id": 1, "message": {"text": "/help"}}},
        )
        sent = await ctx.client.get("/api/dev/telegram/sent")
        assert injected.status_code == 200, injected.text
        assert sent.status_code == 200, sent.text
        assert sent.json() == {"items": []}
