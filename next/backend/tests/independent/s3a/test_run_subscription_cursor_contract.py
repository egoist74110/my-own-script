"""Run event subscriptions must reject cursors beyond durable history."""

import uuid
from types import SimpleNamespace

import pytest

from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.api.ws import _subscribe_run
from toolbox_backend.services.events import EventHub


def run_request():
    task_id = "task:s3a-ws"
    return {
        "task_id": task_id,
        "operation": "sync_build_release",
        "request_id": str(uuid.uuid4()),
        "request_hash": "isolated-request-hash",
        "config_revision": 1,
        "snapshot": {"id": task_id},
        "resources": [],
        "deadline_at": "2099-01-01T00:00:00+00:00",
    }


async def test_future_after_seq_is_rejected_and_subscription_state_is_removed(tmp_path):
    hub = EventHub()
    store = RunStore(tmp_path / "data", hub.publish_run)
    await store.initialize()
    subscriber = hub.subscribe()
    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(hub=hub, run_store=store)))
    try:
        run = await store.create(**run_request())
        run_id = run["run_id"]

        with pytest.raises(ValueError, match="future cursor"):
            await _subscribe_run(
                ws,
                subscriber,
                {"run_id": run_id, "after_seq": run["last_seq"] + 1},
            )

        assert run_id not in subscriber.runs
        assert run_id not in subscriber.replaying
        assert subscriber.queue.empty()
    finally:
        hub.unsubscribe(subscriber)
        await store.close()
