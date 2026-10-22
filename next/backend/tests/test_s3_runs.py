import asyncio
import sqlite3
import uuid

import pytest

from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.domain.errors import SettingsError


@pytest.fixture
async def store(tmp_path):
    result = RunStore(tmp_path / "data")
    await result.initialize()
    try:
        yield result
    finally:
        await result.close()


def request(task="task:a", key=None, resources=()):
    return dict(
        task_id=task,
        operation="sync_build_release",
        request_id=key or str(uuid.uuid4()),
        request_hash="hash",
        config_revision=1,
        snapshot={"id": task},
        resources=list(resources),
        deadline_at="2099-01-01T00:00:00+00:00",
    )


async def test_atomic_create_idempotency_and_restart_sequence(store):
    body = request(resources=["release:one"])
    one, two = await asyncio.gather(store.create(**body), store.create(**body))
    assert one["run_id"] == two["run_id"]
    assert one["last_seq"] == 1
    await store.transition(one["run_id"], 0, "running")
    await store.recover()
    result = await store.get(one["run_id"])
    assert result["status"] == "unknown"
    assert result["last_seq"] == 3
    with pytest.raises(SettingsError) as exc:
        await store.create(**request(task="task:b", resources=["release:one"]))
    assert exc.value.code == "resource_active"


async def test_rollback_has_no_run_reservation_or_broadcast(store):
    emitted = []
    store.on_event = emitted.append

    def fault(label):
        if label == "before_commit":
            raise sqlite3.OperationalError("injected")

    store.checkpoint = fault
    with pytest.raises(SettingsError):
        await store.create(**request(resources=["same"]))
    store.checkpoint = lambda _: None
    assert (await store.list())["items"] == []
    assert emitted == []
    assert (await store.create(**request(resources=["same"])))["last_seq"] == 1


async def test_cancel_is_idempotent_and_terminal_immutable(store):
    run = await store.create(**request())
    first = await store.cancel(run["run_id"])
    second = await store.cancel(run["run_id"])
    assert first == second
    assert first["status"] == "cancelled"
    with pytest.raises(SettingsError):
        await store.transition(run["run_id"], first["state_version"], "running")


async def test_future_database_never_reset(tmp_path):
    path = tmp_path / "runs.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    result = RunStore(tmp_path)
    try:
        await result.initialize()
        assert result.readonly_error
        with pytest.raises(SettingsError) as exc:
            await result.create(**request())
        assert exc.value.code == "run_store_unavailable"
    finally:
        await result.close()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


async def test_future_version_can_read_compatible_history_but_never_write(tmp_path):
    store = RunStore(tmp_path)
    await store.initialize()
    run = await store.create(**request())
    await store.close()
    with sqlite3.connect(tmp_path / "runs.sqlite3") as db:
        db.execute("PRAGMA user_version=99")
    store = RunStore(tmp_path)
    await store.initialize()
    try:
        assert store.readonly_error
        assert (await store.get(run["run_id"]))["status"] == "queued"
        with pytest.raises(SettingsError):
            await store.cancel(run["run_id"])
    finally:
        await store.close()


async def test_intent_receipt_rollback_and_restart_never_replays_write(store):
    run = await store.create(**request(), steps=[{"kind": "build"}])
    rid = run["run_id"]
    await store.transition(rid, 0, "running")
    effect = str(uuid.uuid4())
    await store.record(
        rid, 0, "intent", {"kind": "build_create", "definition_id": 1}, effect_id=effect
    )
    before = await store.get(rid)

    def fault(label):
        raise sqlite3.OperationalError("injected receipt failure")

    store.checkpoint = fault
    with pytest.raises(SettingsError):
        await store.record(
            rid,
            0,
            "receipt",
            {"remote_id": "18", "owned": True},
            effect_id=effect,
            state="confirmed",
        )
    store.checkpoint = lambda _: None
    after = await store.get(rid)
    assert before["last_seq"] == after["last_seq"]
    await store.recover()
    recovered = await store.get(rid)
    assert recovered["status"] == "unknown"
    assert recovered["effects"][0]["state"] == "intent"
    assert recovered["effects"][0]["remote_id"] is None


async def test_concurrent_reservation_and_stale_cas_have_one_winner(store):
    results = await asyncio.gather(
        store.create(**request(task="task:1", resources=["shared"])),
        store.create(**request(task="task:2", resources=["shared"])),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert [r.code for r in results if isinstance(r, SettingsError)] == ["resource_active"]
    run = next(r for r in results if isinstance(r, dict))
    results = await asyncio.gather(
        store.transition(run["run_id"], 0, "running"),
        store.transition(run["run_id"], 0, "failed"),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, SettingsError) for r in results) == 1


async def test_step_completion_preserves_recovery_checkpoint(store):
    run = await store.create(**request(), steps=[{"kind": "git"}])
    await store.transition(run["run_id"], 0, "running")
    await store.record(
        run["run_id"],
        0,
        "checkpoint",
        {"kind": "git", "original_refs": {"refs/heads/main": "a" * 40}},
    )
    await store.record(run["run_id"], 0, "step_finished", {"status": "succeeded"})
    row = await store.get(run["run_id"])
    assert row["steps"][0]["status"] == "succeeded"
    assert row["steps"][0]["checkpoint"]["original_refs"] == {"refs/heads/main": "a" * 40}


async def test_remote_id_cannot_persist_credential_or_arbitrary_remote_text(store):
    run = await store.create(**request(), steps=[{"kind": "build"}])
    rid, effect = run["run_id"], str(uuid.uuid4())
    await store.transition(rid, 0, "running")
    await store.record(
        rid, 0, "intent", {"kind": "build_create", "definition_id": 1}, effect_id=effect
    )
    with pytest.raises(SettingsError) as exc:
        await store.record(
            rid,
            0,
            "receipt",
            {"remote_id": "FAKE_REMOTE_PAT_731", "owned": True},
            effect_id=effect,
            state="confirmed",
        )
    assert exc.value.code == "validation_error"
    assert (await store.get(rid))["effects"][0]["remote_id"] is None
