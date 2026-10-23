"""CR-S3A-001: only remote uncertainty keeps a run's reservation."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.services.runs import RunService


def run_request(task_id: str, *, resources: tuple[str, ...], seconds: float = 60) -> dict:
    return {
        "task_id": task_id,
        "operation": "sync_build_release",
        "request_id": str(uuid.uuid4()),
        "request_hash": uuid.uuid4().hex,
        "config_revision": 1,
        "snapshot": {"id": task_id},
        "resources": list(resources),
        "steps": [{"kind": "build"}],
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
    }


@pytest.fixture
async def run_environment(tmp_path):
    store = RunStore(tmp_path / "data")
    await store.initialize()
    service = RunService(SimpleNamespace(), store)
    try:
        yield service, store
    finally:
        await service.close()


async def assert_resource_available(store, resource: str) -> None:
    replacement = await store.create(
        **run_request("task:replacement", resources=(resource,))
    )
    assert replacement["status"] == "queued"


async def assert_resource_reserved(store, resource: str) -> None:
    with pytest.raises(SettingsError) as exc:
        await store.create(**run_request("task:replacement", resources=(resource,)))
    assert getattr(exc.value, "code", None) == "resource_active"


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [("local_exception", "failed"), ("timeout", "cancelled")],
)
async def test_local_failure_without_remote_observation_releases_reservation(
    run_environment, failure, expected_status
):
    service, store = run_environment
    resource = "build:local-only"
    entered = asyncio.Event()

    class Executor:
        async def execute(self, context):
            entered.set()
            if failure == "timeout":
                await asyncio.Event().wait()
            raise ValueError("local validation failed before any remote request")

    service.executor = Executor()
    run = await store.create(
        **run_request(
            "task:local-only",
            resources=(resource,),
            seconds=0.03 if failure == "timeout" else 60,
        )
    )

    await service._execute_worker(run["run_id"], asyncio.Event())

    assert entered.is_set()
    result = await store.get(run["run_id"])
    assert result["status"] == expected_status
    assert not result["effects"]
    assert await store.list(status="unknown") == {
        "items": [],
        "cursor": None,
    }
    await assert_resource_available(store, resource)


async def test_reused_unowned_build_observation_keeps_unknown_reservation(run_environment):
    service, store = run_environment
    resource = "build:reused"

    class Executor:
        async def execute(self, context):
            await context.checkpoint(
                "build", {"build_id": 17, "owned": False, "result": "reused"}
            )
            raise ValueError("later local failure after observing reused build")

    service.executor = Executor()
    run = await store.create(
        **run_request("task:reused", resources=(resource,))
    )

    await service._execute_worker(run["run_id"], asyncio.Event())

    result = await store.get(run["run_id"])
    assert result["status"] == "unknown"
    assert result["effects"] == []
    assert result["steps"][0]["checkpoint"] == {
        "kind": "build",
        "build_id": 17,
        "owned": False,
        "result": "reused",
    }
    await assert_resource_reserved(store, resource)


async def test_existing_unknown_effect_keeps_reservation_after_local_failure(run_environment):
    service, store = run_environment
    resource = "build:uncertain"

    class Executor:
        async def execute(self, context):
            effect = await context.intent("build_create", {"definition_id": 23})
            await context.receipt(effect, "unknown")
            raise ValueError("local failure after ambiguous build response")

    service.executor = Executor()
    run = await store.create(
        **run_request("task:uncertain", resources=(resource,))
    )

    await service._execute_worker(run["run_id"], asyncio.Event())

    result = await store.get(run["run_id"])
    assert result["status"] == "unknown"
    assert len(result["effects"]) == 1
    assert result["effects"][0]["state"] == "unknown"
    await assert_resource_reserved(store, resource)
