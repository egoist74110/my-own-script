"""CR-S3A-002: recovery of exited workers never replays external writes."""
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from tests.test_s3_runs import request
from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.task_execution import ExecutionOutcome
from toolbox_backend.services.runs import RunService


@pytest.mark.parametrize("failure", ["database", "cas", "readonly"])
@pytest.mark.parametrize("stopping", [False, True])
async def test_lost_worker_recovers_in_process_without_replaying_writes(
    tmp_path, monkeypatch, caplog, failure, stopping
):
    store = RunStore(tmp_path / "data")
    await store.initialize()
    entered, release = asyncio.Event(), asyncio.Event()
    observations, writes = [], []

    class Executor:
        async def execute(self, context):
            writes.append(context.run_id)
            entered.set()
            await release.wait()
            return ExecutionOutcome("unknown", "remote_unknown")

        async def reconcile(self, context):
            observations.append(context)
            assert context.readonly
            with pytest.raises(RuntimeError, match="read-only recovery"):
                await context.intent("build_create", {})
            return ExecutionOutcome("unknown", "remote_unknown")

    service = RunService(SimpleNamespace(), store, Executor())
    run = await store.create(**request(resources=["exclusive"]))
    rid = run["run_id"]
    healthy = await store.create(**request(task="task:healthy"))
    await store.transition(healthy["run_id"], 0, "running")
    worker = asyncio.create_task(service._execute(rid, asyncio.Event()))
    service.workers[rid] = worker
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if stopping:
            await store.cancel(rid)
        before = await store.get(rid)
        with monkeypatch.context() as patch:
            if failure in {"database", "readonly"}:
                def broken_commit(label):
                    if label == "before_commit":
                        error = sqlite3.OperationalError("FAKE_PRIVATE_DATABASE_ERROR")
                        if failure == "readonly":
                            error.sqlite_errorcode = sqlite3.SQLITE_FULL
                        raise error
                patch.setattr(store, "checkpoint", broken_commit)
            else:
                def conflicting(*args, **kwargs):
                    raise SettingsError("state_conflict", "FAKE_PRIVATE_CAS_ERROR")
                async def async_conflicting(*args, **kwargs):
                    conflicting()
                patch.setattr(store, "transition", async_conflicting)
                patch.setattr(store, "_transition", conflicting)
            release.set()
            results = await asyncio.gather(worker, return_exceptions=True)
            assert rid in getattr(service, "lost_workers", {}), "exited worker was forgotten"
            assert results == [None]
            assert service.lost_workers[rid] == "运行收尾未落盘；保留预约，等待只读恢复"
            assert rid not in service.workers
            for _ in range(2):
                await service._recovery_round()
                current = await store.get(rid)
                assert current["status"] == before["status"]
                assert current["last_seq"] == before["last_seq"]
                assert rid in service.lost_workers
                with pytest.raises(SettingsError) as exc:
                    await store.create(**request(task="task:blocked", resources=["exclusive"]))
                assert exc.value.code == (
                    "run_store_unavailable" if failure == "readonly" else "resource_active"
                )
            assert not observations
        await service._recovery_round()
        if service.reconciliations:
            await asyncio.gather(*service.reconciliations.values())
        recovered = await store.get(rid)
        assert recovered["status"] == "unknown"
        assert recovered["recovery_state"] == "pending"
        assert rid not in service.lost_workers
        assert (await store.get(healthy["run_id"]))["status"] == "running"
        assert writes == [rid]
        assert len(observations) == 1
        with pytest.raises(SettingsError) as exc:
            await store.create(**request(task="task:blocked", resources=["exclusive"]))
        assert exc.value.code == "resource_active"
        assert "运行收尾未落盘；保留预约，等待只读恢复" in caplog.text
        assert "FAKE_PRIVATE" not in caplog.text
    finally:
        release.set()
        await asyncio.gather(worker, return_exceptions=True)
        await service.close()
