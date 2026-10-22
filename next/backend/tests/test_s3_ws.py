import asyncio
import json
from types import SimpleNamespace

from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.api.ws import _drain_incoming, _subscribe_run
from toolbox_backend.services.events import EventHub

from .test_s3_runs import request


async def test_replay_live_boundary_is_gapless_and_unsubscribed_clients_receive_nothing(tmp_path):
    hub = EventHub(queue_size=256)
    store = RunStore(tmp_path, hub.publish_run)
    await store.initialize()
    try:
        run = await store.create(**request())
        rid = run["run_id"]
        for i in range(270):
            await store.log(rid, f"line {i}")
        sub, other = hub.subscribe(), hub.subscribe()
        ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(hub=hub, run_store=store)))
        get = store.get

        async def race(run_id):
            snapshot = await get(run_id)
            await store.log(run_id, "during replay")
            return snapshot

        store.get = race
        messages = []

        async def consume():
            while True:
                message = json.loads(await sub.queue.get())
                messages.append(message)
                if message["type"] == "run.event" and message["data"]["run_seq"] == 272:
                    return

        consumer = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(_subscribe_run(ws, sub, {"run_id": rid, "after_seq": 0}), 3)
            await asyncio.wait_for(consumer, 3)
        finally:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
            hub.unsubscribe(sub)
            hub.unsubscribe(other)
        sequences = [e["data"]["run_seq"] for e in messages if e["type"] == "run.event"]
        assert sequences == list(range(1, 273))
        assert any(e["type"] == "run.subscribed" and e["data"]["last_seq"] == 271 for e in messages)
        assert [e["seq"] for e in messages] == sorted(e["seq"] for e in messages)
        assert other.queue.empty()
        assert not sub.overflowed.is_set()
    finally:
        await store.close()


async def test_run_subscription_limit_and_slow_subscriber(tmp_path):
    hub = EventHub(queue_size=2)
    sub = hub.subscribe()
    sub.runs["one"] = 0
    for i in range(3):
        hub.publish_run(
            {"run_id": "one", "run_seq": i + 1, "type": "log", "payload": {"text": "a"}}
        )
    assert sub.overflowed.is_set()
    assert hub.subscriber_count == 0


async def test_s0_post_auth_garbage_remains_ignored():
    class Socket:
        def __init__(self):
            self.messages = iter(
                [
                    {"type": "websocket.receive", "bytes": b"\x00\xff"},
                    {"type": "websocket.receive", "text": "x" * 1000},
                    {"type": "websocket.receive", "text": "[" * 100000},
                    {"type": "websocket.receive", "text": '{"type":"ping"}'},
                    {"type": "websocket.disconnect"},
                ]
            )
            self.closed = []

        async def receive(self):
            return next(self.messages)

        async def close(self, code):
            self.closed.append(code)

    ws = Socket()
    await _drain_incoming(ws, EventHub().subscribe())
    assert ws.closed == []
