"""VPN Telegram entry checks with memory credentials and no native actions."""

import pytest

from tests.independent.s4a.conftest import open_telegram_app
from tests.test_s4a_boundaries import message, prepare
from tests.test_s4b_execution import latest, tap
from toolbox_backend.domain.errors import SettingsError


@pytest.mark.parametrize("entry", ["command", "menu"])
@pytest.mark.parametrize(
    "seed,desktop,error,expected,starts",
    [
        (False, "none", None, "请先在桌面端配置 VPN（TOTP 种子）", 0),
        (False, "unsubscribed", None, "请先在桌面端配置 VPN（TOTP 种子）", 0),
        (False, "vpn", None, "已开始", 1),
        (True, "none", None, "已开始", 1),
        (True, "none", "vpn_busy", "VPN 正在执行其他操作，请稍后重试", 1),
        (True, "none", "vpn_not_configured", "请先在桌面端配置 VPN 凭据", 1),
        (True, "none", "vpn_future_error", "VPN 操作失败，请在桌面端检查配置或稍后重试", 1),
    ],
)
async def test_vpn_start_replies_through_command_and_menu(
    tmp_path, monkeypatch, entry, seed, desktop, error, expected, starts
):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx)
        tg = ctx.app.state.telegram_service
        if seed:
            tg.vpn.credentials.set("vpn_totp_secret", "S8_FAKE_SEED")
        hub = tg.hub
        sub = hub.subscribe() if desktop != "none" else None
        if desktop == "vpn":
            sub.vpn_after = 0
        elif sub:
            sub.vpn_after = 0
            sub.vpn_unsubscribed = True
        called = []

        async def start(**kwargs):
            called.append(kwargs)
            if error:
                raise SettingsError(error, "S8_FAKE_SECRET_MUST_NOT_BE_REPLIED", 409)

        monkeypatch.setattr(tg.vpn, "start", start)
        try:
            if entry == "command":
                await tg.process_updates([message(101, text="/vpn on")])
            else:
                update = message(100)
                button = await tg.dispatcher.button(update, "连接", "vpn_connect", {})
                await tap(ctx.app, tg, 101, "", chat=6001, token=button["callback_data"])
            assert latest(ctx.app)[0] == expected
            assert len(called) == starts
            assert "S8_FAKE" not in latest(ctx.app)[0]
        finally:
            if sub:
                hub.unsubscribe(sub)
