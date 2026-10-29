"""Token 校验只读、持久化和凭据保密回归。"""

import asyncio
import json

import httpx
import pytest

from tests.independent.s4a.conftest import BOT_TOKEN, MockBot, open_telegram_app
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.adapters.credentials import MemoryCredentials

SLOTS = ["", "/ai-bots/claude_code", "/ai-bots/codex", "/ai-bots/gemini"]


def account(slot):
    return "ai_bot_token:" + slot.rsplit("/", 1)[-1] if slot else "telegram_bot_token"


def control(config, slot):
    return getattr(config.ai.bots, slot.rsplit("/", 1)[-1]) if slot else config.telegram.control


@pytest.mark.parametrize("slot", SLOTS)
@pytest.mark.parametrize("legacy", [False, True])
async def test_save_and_import_verify_identity_without_activation(tmp_path, slot, legacy, caplog):
    old = MemoryCredentials()
    old.set(account(slot), BOT_TOKEN)
    bot = MockBot()

    async def handler(request):
        if request.url.path.endswith("/getMe"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "id": 123456789,
                        "username": "test_bot",
                        "first_name": "测试机器人",
                    },
                },
            )
        return await bot._default(request)

    bot.handler = handler
    async with open_telegram_app(tmp_path, bot=bot, legacy_credentials=old) as ctx:
        base = "/api/telegram" + slot
        if legacy:
            response = await ctx.client.post(base + "/token/import-legacy", json={"revision": 0})
        else:
            response = await ctx.client.put(
                base + "/token", json={"revision": 0, "token": BOT_TOKEN}
            )
        assert response.status_code == 200, response.text
        assert response.json()["verify"]["ok"] is True
        config = await ctx.app.state.config_store.read()
        ctl = control(config, slot)
        assert ctl.verified_bot.id == "123456789"
        assert ctl.verified_bot.first_name == "测试机器人"
        reopened = await ConfigStore(ctx.data_dir).read()
        assert control(reopened, slot).verified_bot == ctl.verified_bot
        assert ctl.verified_bot.verified_at
        assert not ctl.enabled and ctl.bot_id is None
        view = await ctx.client.get(base)
        assert view.json()["bot"]["bot_id"] == "123456789"
        assert view.json()["bot"]["username"] == "test_bot"
        assert view.json()["bot"]["verify"]["ok"] is True
        assert [r.url.path.rsplit("/", 1)[-1] for r in bot.requests] == ["getMe", "getWebhookInfo"]
        assert ctx.credentials.get(account(slot)) == BOT_TOKEN
        assert BOT_TOKEN not in response.text + view.text + caplog.text
        persisted = json.loads((ctx.data_dir / "config.json").read_text())
        assert BOT_TOKEN not in json.dumps(persisted)


@pytest.mark.parametrize("slot", SLOTS)
@pytest.mark.parametrize(
    "failure,code",
    [
        ("401", "token_invalid"),
        ("network", "telegram_unreachable"),
        ("timeout", "telegram_unreachable"),
    ],
)
async def test_failed_verification_keeps_token_and_reports_safe_error(
    tmp_path, slot, failure, code, caplog
):
    bot = MockBot()

    async def fail(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(str(request.url), request=request)
        if failure == "network":
            raise httpx.ConnectError(str(request.url), request=request)
        return httpx.Response(401, json={"ok": False, "description": BOT_TOKEN})

    bot.handler = fail
    async with open_telegram_app(tmp_path, bot=bot) as ctx:
        base = "/api/telegram" + slot
        response = await ctx.client.put(base + "/token", json={"revision": 0, "token": BOT_TOKEN})
        assert response.status_code == 200
        verify = response.json()["verify"]
        assert verify["ok"] is False and verify["code"] == code
        if failure == "401":
            assert verify["message"] == "Token 无效或已被撤销"
        assert ctx.credentials.get(account(slot)) == BOT_TOKEN
        view = await ctx.client.get(base)
        assert view.json()["bot"]["verify"] == verify
        assert view.json()["bot"]["verified_bot"] is None
        assert BOT_TOKEN not in response.text + view.text + caplog.text
        assert len(bot.requests) == 1


@pytest.mark.parametrize("slot", SLOTS)
async def test_recheck_webhook_and_replace_delete_clear_identity(tmp_path, slot):
    bot = MockBot()
    async with open_telegram_app(tmp_path, bot=bot) as ctx:
        base = "/api/telegram" + slot
        missing = await ctx.client.post(base + "/token/verify", json={"revision": 0})
        assert missing.json()["detail"]["code"] == "no_credential"
        saved = await ctx.client.put(base + "/token", json={"revision": 0, "token": BOT_TOKEN})
        revision = saved.json()["revision"]

        async def webhook(request):
            if request.url.path.endswith("/getWebhookInfo"):
                return httpx.Response(
                    200, json={"ok": True, "result": {"url": "https://example.test/hook"}}
                )
            return await bot._default(request)

        bot.handler = webhook
        checked = await ctx.client.post(base + "/token/verify", json={"revision": revision})
        assert checked.status_code == 200
        assert checked.json()["verify"]["has_webhook"] is True
        assert ctx.credentials.get(account(slot)) == BOT_TOKEN
        stale = await ctx.client.post(base + "/token/verify", json={"revision": revision})
        assert stale.status_code == 409
        assert not control(await ctx.app.state.config_store.read(), slot).enabled
        assert all(
            r.url.path.rsplit("/", 1)[-1] in {"getMe", "getWebhookInfo"} for r in bot.requests
        )

        async def invalid(request):
            return httpx.Response(401, json={"ok": False})

        bot.handler = invalid
        changed = await ctx.client.put(
            base + "/token",
            json={
                "revision": checked.json()["revision"],
                "token": "987654321:" + "Z" * 32,
            },
        )
        assert changed.json()["verify"]["ok"] is False
        view = (await ctx.client.get(base)).json()
        assert view["bot"]["verified_bot"] is None
        assert view["bot"]["username"] is None
        deleted = await ctx.client.delete(
            base + "/token", params={"revision": changed.json()["revision"]}
        )
        assert deleted.status_code == 200
        ctl = control(await ctx.app.state.config_store.read(), slot)
        assert ctl.verified_bot is None and ctl.token_verify is None


@pytest.mark.parametrize("slot", SLOTS)
async def test_enable_refreshes_verified_identity_from_getme(tmp_path, slot):
    bot = MockBot()
    async with open_telegram_app(tmp_path, bot=bot) as ctx:
        base = "/api/telegram" + slot
        saved = await ctx.client.put(base + "/token", json={"revision": 0, "token": BOT_TOKEN})

        async def changed_identity(request):
            if request.url.path.endswith("/getMe"):
                return httpx.Response(
                    200, json={"ok": True, "result": {"id": 987654321, "username": "fresh_bot"}}
                )
            return await bot._default(request)

        bot.handler = changed_identity
        enabled = await ctx.client.post(
            base + "/control/enable",
            json={
                "revision": saved.json()["revision"],
                ("ack_old_bot_cleared" if slot else "ack_old_bot_stopped"): True,
            },
        )
        assert enabled.status_code == 200, enabled.text
        view = (await ctx.client.get(base)).json()
        assert view["control"]["bot_id"] == "987654321"
        assert view["bot"]["bot_id"] == "987654321"
        assert view["bot"]["username"] == "fresh_bot"
        await asyncio.sleep(0)
