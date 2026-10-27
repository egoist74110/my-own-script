"""S7 replay/watermark and owner Telegram two-step confirmation seams."""

import json
from types import SimpleNamespace

import pytest

from tests.independent.s4b.conftest import (
    buttons,
    message,
    open_telegram_app,
    outbox_texts,
    prepare,
    tap,
)
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.api.services_schemas import ServicesStatusData, ServicesStatusEvent
from toolbox_backend.api.ws import _drain_incoming, _subscribe_services
from toolbox_backend.services.events import EventHub
from toolbox_backend.services.services import ServicesService


async def test_services_ws_replay_watermark_live_unsubscribe_overflow(tmp_path):
    hub = EventHub(queue_size=4)
    svc = ServicesService(ConfigStore(tmp_path), hub, path_extras=[])
    snap = await svc.snapshot()
    sub, other = hub.subscribe(), hub.subscribe()

    def publish():
        hub.publish_services(
            ServicesStatusEvent,
            ServicesStatusData(services_seq=hub._state("services").last_seq + 1, snapshot=snap),
        )

    publish()
    publish()
    assert sub.queue.empty() and other.queue.empty()
    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(hub=hub)))
    await _subscribe_services(ws, sub, {"after_seq": 0})
    frames = [json.loads(sub.queue.get_nowait()) for _ in range(3)]
    assert [f["type"] for f in frames] == [
        "services.status",
        "services.status",
        "services.subscribed",
    ]
    assert [f["data"]["services_seq"] for f in frames[:2]] == [1, 2]
    assert frames[-1]["data"]["last_seq"] == 2
    publish()
    live = json.loads(sub.queue.get_nowait())
    assert live["data"]["services_seq"] == 3 and live["seq"] > frames[-1]["seq"]
    assert other.queue.empty()

    class Socket:
        app = ws.app
        messages = iter(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "unsubscribe", "topic": "services"}),
                },
                {"type": "websocket.disconnect"},
            ]
        )

        async def receive(self):
            return next(self.messages)

    await _drain_incoming(Socket(), sub)
    publish()
    assert sub.queue.empty()
    with pytest.raises(ValueError):
        await _subscribe_services(ws, sub, {"after_seq": 500})
    assert sub.services_after is None
    slow = hub.subscribe()
    slow.services_after = hub._state("services").last_seq
    for _ in range(5):
        publish()
    assert slow.overflowed.is_set()
    hub.unsubscribe(sub)
    hub.unsubscribe(other)
    await svc.close()


async def test_telegram_custom_tunnel_requires_input_then_confirm_and_same_validator(
    tmp_path, monkeypatch
):
    async with open_telegram_app(tmp_path) as ctx:
        await prepare(ctx, owner="6001")
        tg = ctx.app.state.telegram_service
        calls = []

        async def create(body):
            calls.append(body)

        monkeypatch.setattr(tg.services, "create_tunnel", create)
        async def vpn_snapshot():
            return SimpleNamespace(connected=False, ip=None)

        monkeypatch.setattr(tg.vpn, "snapshot", vpn_snapshot)
        await tg.process_updates([message(700, text="/services", chat=6002)])
        assert not calls
        await tg.process_updates([message(701, text="/services", chat=6001)])
        assert "VPN：未连接" in (await outbox_texts(ctx))[-1]
        assert any("连接 VPN" in button["text"] for button in await buttons(ctx))
        await tap(ctx, 702, "新增自定义隧道", chat=6001)
        await tg.process_updates([message(703, text="http://[::1]:45436", chat=6001)])
        assert not calls
        assert any("确认公开到公网" in b["text"] for b in await buttons(ctx))
        await tap(ctx, 704, "确认公开到公网", chat=6001)
        assert len(calls) == 1 and calls[0].ack_public is True
        assert calls[0].target_url == "http://[::1]:45436"
        await tap(ctx, 705, "新增自定义隧道", chat=6001)
        await tg.process_updates([message(706, text="http://localhost.evil.com:45436", chat=6001)])
        assert len(calls) == 1
        assert "本机回环" in (await outbox_texts(ctx))[-1]
