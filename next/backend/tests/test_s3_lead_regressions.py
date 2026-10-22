import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest

from tests.test_s3_runs import request
from toolbox_backend.adapters import task_git
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.api.task_schemas import StartRequest
from toolbox_backend.app import create_app
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import DynamicTask, Library, Project
from toolbox_backend.domain.task_execution import ExecutionOutcome, PreparedExecution
from toolbox_backend.services.runs import RunService
from toolbox_backend.settings import Settings


async def test_log_failure_after_supervisor_exit_cannot_be_reported_as_success(
    tmp_path, monkeypatch
):
    original_spawn = asyncio.create_subprocess_exec
    holder = {}

    async def spawn(*args, **kwargs):
        proc = await original_spawn(*args, **kwargs)
        holder["proc"] = proc
        return proc

    monkeypatch.setattr(task_git.asyncio, "create_subprocess_exec", spawn)
    adapter = task_git.GitAdapter(tmp_path / "data", test_remote_root=tmp_path)

    async def sink(_text, **_kwargs):
        # Force the process-exit waiter to win before the journal fails.
        await holder["proc"].wait()
        await asyncio.sleep(0.02)
        raise SettingsError("run_store_unavailable", "injected journal failure", 503)

    async with asyncio.timeout(3):
        with pytest.raises(SettingsError) as exc:
            await adapter.command(tmp_path, ["--version"], output=sink)
    assert exc.value.code == "run_store_unavailable"


async def test_committed_start_survives_request_cancellation(tmp_path, monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    committed = asyncio.Event()
    handoff = asyncio.Event()

    class Executor:
        async def prepare(self, snapshot, operation, offset):
            return PreparedExecution(budget_seconds=30)

        async def execute(self, context):
            entered.set()
            await release.wait()
            return ExecutionOutcome("succeeded")

        async def reconcile(self, context):
            return ExecutionOutcome("unknown")

    app = create_app(
        Settings(
            token="lead-fake-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
        task_executor=Executor(),
    )
    async with app.router.lifespan_context(app):

        def seed(c):
            c.ado.libraries = [Library(id="lib:a", name="Fake", base_url="https://ado.test")]
            c.ado.projects = [Project(id="proj:a", library_id="lib:a", collection="c", project="p")]
            c.tasks.items = [
                DynamicTask(id="task:a", project_id="proj:a", git_flow={"build_branch": "main"})
            ]

        await app.state.config_store.update(0, seed)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer lead-fake-token"},
        ) as client:
            plan = await client.post(
                "/api/tasks/task:a/preflight",
                json={"revision": 1, "operation": "sync_build_release"},
            )
            assert plan.status_code == 200, plan.text
            body = StartRequest(
                plan_id=plan.json()["plan_id"], request_id=uuid.uuid4(), ack_old_app_idle=True
            )
            config_store = app.state.config_store
            original_run = config_store.run

            async def disconnected_after_commit(*args, **kwargs):
                result = await original_run(*args, **kwargs)
                assert result["status"] == "queued"
                committed.set()
                await handoff.wait()
                return result

            try:
                with monkeypatch.context() as patch:
                    patch.setattr(config_store, "run", disconnected_after_commit)
                    request = asyncio.create_task(app.state.run_service.start("task:a", body))
                    await asyncio.wait_for(committed.wait(), 2)
                    request.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await request
                    handoff.set()
                stored = await app.state.run_store.lookup(str(body.request_id))
                assert stored is not None  # accepted durably before HTTP cancellation
                await asyncio.wait_for(entered.wait(), 2)
            finally:
                handoff.set()
                release.set()


async def test_shutdown_still_reaps_workers_and_closes_store_if_cancel_journal_fails(
    tmp_path, monkeypatch
):
    store = RunStore(tmp_path / "data")
    await store.initialize()
    service = RunService(SimpleNamespace(), store)
    stopped = asyncio.Event()
    signal = asyncio.Event()

    async def worker():
        await signal.wait()
        stopped.set()

    task = asyncio.create_task(worker())
    service.workers["fake-run"] = task
    service.cancellations["fake-run"] = signal

    async def failed_cancel(*args):
        raise SettingsError("run_store_unavailable", "injected failure", 503)

    monkeypatch.setattr(store, "cancel", failed_cancel)
    try:
        await service.close()
        assert stopped.is_set()
        assert task.done()
        assert store._db is None and store._fd is None
    finally:
        signal.set()
        await task
        await store.close()


async def test_checkpoint_for_missing_step_is_rejected_without_an_event(tmp_path):
    store = RunStore(tmp_path / "data")
    await store.initialize()
    try:
        run = await store.create(**request())
        run = await store.transition(run["run_id"], 0, "running")
        with pytest.raises(SettingsError) as exc:
            await store.record(run["run_id"], 0, "checkpoint", {"kind": "git"})
        assert exc.value.code == "not_found"
        assert (await store.get(run["run_id"]))["last_seq"] == run["last_seq"]
    finally:
        await store.close()


async def test_raw_log_budget_does_not_publish_empty_events(tmp_path):
    store = RunStore(tmp_path / "data")
    await store.initialize()
    try:
        run = await store.create(**request())
        await store.log(run["run_id"], "", raw_bytes=4096)
        after = await store.get(run["run_id"])
        assert after["log_bytes"] == 4096
        assert after["last_seq"] == run["last_seq"]
        await store.log(run["run_id"], "safe line", raw_bytes=0)
        after = await store.get(run["run_id"])
        assert after["log_bytes"] == 4096
        assert after["last_seq"] == run["last_seq"] + 1
    finally:
        await store.close()
