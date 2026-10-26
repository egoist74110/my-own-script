"""Independent Telegram owner-only access checks for S7-A controls."""

from types import SimpleNamespace

import pytest

from tests.independent.s4a.conftest import open_telegram_app


def _callback(token, *, chat_id=6001, user_id=6001):
    return {
        "update_id": 71,
        "callback_query": {
            "id": "s7a-callback",
            "from": {"id": user_id},
            "message": {
                "date": 1_798_000_000,
                "chat": {"id": chat_id, "type": "private"},
                "text": "服务",
            },
            "data": token,
        },
    }


@pytest.fixture
def telegram_app(tmp_path):
    return open_telegram_app(tmp_path)


async def test_services_menu_callback_is_owner_only(telegram_app, monkeypatch):
    async with telegram_app as ctx:
        service = ctx.app.state.telegram_service
        dispatcher = service.dispatcher
        token = "a" * 22
        panels = []

        async def consume(*args):
            return {"kind": "menu", "payload": {"page": "services"}}

        async def owner_acl(_):
            return "owner", None

        async def group_acl(_):
            return "group", object()

        async def panel(_):
            panels.append("services")

        monkeypatch.setattr(service.store, "consume", consume)
        monkeypatch.setattr(service, "resolve_acl", owner_acl)
        monkeypatch.setattr(dispatcher, "services_panel", panel)
        assert await dispatcher.callback(_callback(token)) == "handled"
        assert panels == ["services"]

        panels.clear()
        monkeypatch.setattr(service, "resolve_acl", group_acl)
        assert await dispatcher.callback(_callback(token)) == "ignored"
        assert panels == []


async def test_service_action_callback_is_owner_only(telegram_app, monkeypatch):
    async with telegram_app as ctx:
        service = ctx.app.state.telegram_service
        dispatcher = service.dispatcher
        token = "b" * 22
        called = []

        async def consume(*args):
            return {
                "kind": "svc_action",
                "payload": {"name": "cloudflared", "action": "start"},
            }

        async def group_acl(_):
            return "group", object()

        async def action(*args):
            called.append(args)

        monkeypatch.setattr(service.store, "consume", consume)
        monkeypatch.setattr(service, "resolve_acl", group_acl)
        monkeypatch.setattr(dispatcher, "services_action", action)
        assert await dispatcher.callback(_callback(token)) == "ignored"
        assert called == []


async def test_services_panel_never_renders_password_or_token_fields(telegram_app, monkeypatch):
    async with telegram_app as ctx:
        service = ctx.app.state.telegram_service
        dispatcher = service.dispatcher
        code = SimpleNamespace(
            state="running",
            port=8080,
            password="S7_PANEL_PASSWORD_SECRET_MARKER",
        )
        global_tunnel = SimpleNamespace(
            state="running",
            url="https://example.trycloudflare.com",
            token="S7_PANEL_TUNNEL_TOKEN_SECRET_MARKER",
        )
        snapshot = SimpleNamespace(
            code_server=code,
            cloudflared=SimpleNamespace(global_=global_tunnel, tunnels=[]),
            settings=SimpleNamespace(cloudflared=SimpleNamespace(protocol="http2")),
            network=SimpleNamespace(lan_ip="192.168.10.7"),
        )
        messages = []

        async def get_snapshot():
            return snapshot

        async def panel(_update, text, _buttons=None):
            messages.append(text)

        async def button(_update, label, _kind, _payload):
            return {"text": label}

        monkeypatch.setattr(service.services, "snapshot", get_snapshot)
        monkeypatch.setattr(dispatcher, "panel", panel)
        monkeypatch.setattr(dispatcher, "button", button)
        await dispatcher.services_panel({})

        assert len(messages) == 1
        assert "S7_PANEL_PASSWORD_SECRET_MARKER" not in messages[0]
        assert "S7_PANEL_TUNNEL_TOKEN_SECRET_MARKER" not in messages[0]
