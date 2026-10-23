import asyncio
import json
import uuid

import httpx
import pytest

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import DynamicTask, Library, Project
from toolbox_backend.domain.task_execution import ExecutionOutcome, PreparedExecution
from toolbox_backend.logging_setup import register_secret
from toolbox_backend.settings import Settings


class Executor:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.writes = 0

    async def prepare(self, snapshot, operation, offset):
        assert "future_extension" not in snapshot
        return PreparedExecution(
            steps=[{"kind": "build", "target_index": 0}],
            resources=["fake:release"],
            budget_seconds=300,
        )

    async def execute(self, context):
        effect = await context.intent("build_create", {"definition_id": 1})
        self.writes += 1
        await context.receipt(effect, "confirmed", remote_id="17", owned=True)
        self.entered.set()
        await self.release.wait()
        await context.complete_step()
        return ExecutionOutcome("succeeded")

    async def reconcile(self, context):
        assert context.readonly
        return ExecutionOutcome("unknown", "remote_unknown")


@pytest.fixture
async def execution(tmp_path):
    fake = Executor()
    app = create_app(
        Settings(
            token="s3-fake-bearer-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
        task_executor=fake,
    )
    async with app.router.lifespan_context(app):

        def seed(c):
            c.ado.libraries = [Library(id="lib:a", name="Fake", base_url="https://ado.test")]
            c.ado.projects = [Project(id="proj:a", library_id="lib:a", collection="c", project="p")]
            c.tasks.items = [
                DynamicTask(
                    id="task:a",
                    name="Fake",
                    project_id="proj:a",
                    git_flow={"build_branch": "main"},
                    future_extension="keep",
                )
            ]

        await app.state.config_store.update(0, seed)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer s3-fake-bearer-token"},
        ) as client:
            yield app, client, fake
        fake.release.set()


async def start(client):
    plan = await client.post(
        "/api/tasks/task:a/preflight", json={"revision": 1, "operation": "sync_build_release"}
    )
    assert plan.status_code == 200, plan.text
    body = {
        "plan_id": plan.json()["plan_id"],
        "request_id": str(uuid.uuid4()),
        "ack_old_app_idle": True,
    }
    response = await client.post("/api/tasks/task:a/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"], body


async def test_fake_executor_idempotency_and_active_configuration(execution):
    app, client, fake = execution
    rid, body = await start(client)
    await asyncio.wait_for(fake.entered.wait(), 2)
    again = await client.post("/api/tasks/task:a/runs", json=body)
    assert again.json() == {"run_id": rid}
    assert fake.writes == 1
    edit = await client.patch("/api/tasks/task:a", json={"revision": 1, "name": "blocked"})
    assert edit.status_code == 409 and edit.json()["detail"]["code"] == "task_active"
    project = await client.patch(
        "/api/ado/projects/proj:a", json={"revision": 1, "project": "different"}
    )
    assert project.status_code == 409 and project.json()["detail"]["code"] == "resource_active"
    first = await client.post(f"/api/runs/{rid}/cancel")
    second = await client.post(f"/api/runs/{rid}/cancel")
    assert first.json() == second.json()
    fake.release.set()
    await asyncio.gather(*list(app.state.run_service.workers.values()))
    run = (await client.get(f"/api/runs/{rid}")).json()
    assert run["status"] == "succeeded" and run["cancel_requested_at"]
    events = (await client.get(f"/api/runs/{rid}/events?limit=2")).json()
    assert events["has_more"] and events["next_seq"] == 2
    assert [e["run_seq"] for e in events["items"]] == [1, 2]


async def test_cross_chunk_redaction_and_unbounded_line(tmp_path):
    from toolbox_backend.adapters.run_log import StreamRedactor

    secret = "FAKE_S3_PAT_very_private_731"
    register_secret(secret)
    stream = StreamRedactor()
    pieces = []
    for part in [
        b"prefix FAKE_S3_",
        b"PAT_very_",
        b"private_731\n",
        b"Authorization: Bear",
        b"er another-private-token\n",
        b"x" * 100000,
    ]:
        pieces.extend(stream.feed(part))
    pieces.extend(stream.finish())
    encoded = json.dumps(pieces)
    assert secret not in encoded and "another-private-token" not in encoded
    assert "prefix" in encoded
    assert sum(map(len, pieces)) < 20000


def test_nested_legacy_extensions_survive_read():
    task = DynamicTask.model_validate(
        {
            "id": "task:legacy",
            "git_flow": {"build_branch": "main", "future_flow": {"keep": True}},
            "targets": [{"name": "target", "future_target": ["keep"]}],
        }
    )
    assert task.model_dump()["git_flow"]["future_flow"] == {"keep": True}
    assert task.model_dump()["targets"][0]["future_target"] == ["keep"]


async def test_active_library_rejected_before_credential_side_effect(execution, monkeypatch):
    app, client, fake = execution
    await start(client)
    await asyncio.wait_for(fake.entered.wait(), 2)
    writes = []
    monkeypatch.setattr(
        app.state.settings_service.credentials, "set", lambda key, value: writes.append(key)
    )
    response = await client.patch(
        "/api/ado/libraries/lib:a",
        json={
            "revision": 1,
            "base_url": "https://changed.test",
            "pat": "FAKE_NEW_S3_CREDENTIAL_123",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_active"
    assert writes == []


async def test_nested_extensions_are_preserved_but_never_enter_execution(execution):
    app, client, fake = execution

    def extension(c):
        c.tasks.items[0].git_flow.future_flow = {"arbitrary": "not-executable"}

    await app.state.config_store.update(1, extension)
    response = await client.post(
        "/api/tasks/task:a/preflight", json={"revision": 2, "operation": "sync_build_release"}
    )
    assert response.status_code == 200, response.text
    plan = app.state.run_service.plans[response.json()["plan_id"]]
    assert "future_flow" not in plan["snapshot"]["git_flow"]
    assert (await app.state.config_store.read()).tasks.items[0].git_flow.future_flow == {
        "arbitrary": "not-executable"
    }


async def test_budget_uses_raw_bytes_and_redacts_control_obfuscated_secret(tmp_path):
    from tests.test_s3_runs import request
    from toolbox_backend.adapters.run_log import StreamRedactor
    from toolbox_backend.adapters.run_store import RunStore

    secret = "FAKE_S3_ANSI_PRIVATE_731"
    register_secret(secret)
    redactor = StreamRedactor()
    result = "".join(redactor.feed(b"FAKE_S3_\x1b[31mANSI_PRIVATE_731\n"))
    assert secret not in result
    store = RunStore(tmp_path)
    await store.initialize()
    try:
        run = await store.create(**request())
        await store.log(run["run_id"], "safe", raw_bytes=20 * 1024 * 1024)
        before = await store.get(run["run_id"])
        await store.log(run["run_id"], "must drop")
        after = await store.get(run["run_id"])
        assert before["log_bytes"] == after["log_bytes"] == 20 * 1024 * 1024
        assert before["last_seq"] == after["last_seq"]
        events = await store.events(run["run_id"])
        assert sum("日志已达上限" in e["payload"].get("text", "") for e in events["items"]) == 1
    finally:
        await store.close()


async def test_queued_cancel_exits_worker_without_waiting_for_slot(execution):
    app, client, fake = execution
    app.state.run_service._semaphore = asyncio.Semaphore(0)
    rid, _ = await start(client)
    worker = app.state.run_service.workers[rid]
    result = await client.post(f"/api/runs/{rid}/cancel")
    assert result.json()["status"] == "cancelled"
    await asyncio.wait_for(asyncio.shield(worker), 0.5)
    assert fake.writes == 0
    assert rid not in app.state.run_service.workers


async def test_expired_plan_replays_persistent_idempotency_but_not_new_key(execution):
    app, client, fake = execution
    rid, body = await start(client)
    app.state.run_service.plans[body["plan_id"]]["expires"] = 0
    same = await client.post("/api/tasks/task:a/runs", json=body)
    assert same.status_code == 202 and same.json()["run_id"] == rid
    other = await client.post(
        "/api/tasks/task:a/runs", json={**body, "request_id": str(uuid.uuid4())}
    )
    assert other.status_code == 409 and other.json()["detail"]["code"] == "plan_expired"
    changed = await client.post("/api/tasks/task:other/runs", json=body)
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "idempotency_conflict"


async def test_unknown_reconcile_is_read_only_and_stops_at_manual_deadline(execution, monkeypatch):
    app, client, fake = execution

    async def uncertain(context):
        effect = await context.intent("build_create", {"definition_id": 1})
        fake.writes += 1
        await context.receipt(effect, "unknown")
        return ExecutionOutcome("unknown", "remote_unknown")

    monkeypatch.setattr(fake, "execute", uncertain)
    rid, _ = await start(client)
    await asyncio.gather(*list(app.state.run_service.workers.values()))
    assert (await app.state.run_store.get(rid))["status"] == "unknown"
    await app.state.run_service.reconcile(rid)
    await asyncio.gather(*list(app.state.run_service.reconciliations.values()))
    assert fake.writes == 1

    async def expired(_):
        return "2000-01-01T00:00:00+00:00"

    monkeypatch.setattr(app.state.run_store, "recovery_started", expired)
    await app.state.run_service._recovery_round()
    result = await app.state.run_store.get(rid)
    assert result["status"] == "unknown" and result["recovery_state"] == "manual_required"
    assert result["effects"][0]["state"] == "unknown"
    assert app.state.run_store.active_snapshots()[0]["run_id"] == rid


async def test_unavailable_run_database_does_not_hide_task_config_or_unrelated_settings(
    execution, monkeypatch
):
    from toolbox_backend.domain.errors import SettingsError

    app, client, _ = execution

    def unavailable():
        raise SettingsError("run_store_unavailable", "injected", 503)

    monkeypatch.setattr(app.state.run_store, "task_summaries", unavailable)
    tasks = await client.get("/api/tasks")
    assert tasks.status_code == 200, tasks.text
    assert tasks.json()["items"][0]["warnings"]
    response = await client.put(
        "/api/ado/active", json={"revision": 1, "library_id": "lib:a", "project_id": "proj:a"}
    )
    assert response.status_code == 200, response.text


async def test_shutdown_race_with_worker_completion_has_no_registry_keyerror(
    execution, monkeypatch
):
    app, client, fake = execution
    rid, _ = await start(client)
    await asyncio.wait_for(fake.entered.wait(), 2)
    worker = app.state.run_service.workers[rid]
    cancel = app.state.run_store.cancel

    async def complete_during_cancel(run_id, reason="user"):
        result = await cancel(run_id, reason)
        fake.release.set()
        await worker
        return result

    monkeypatch.setattr(app.state.run_store, "cancel", complete_during_cancel)
    await app.state.run_service.close()
    assert not app.state.run_service.workers


@pytest.mark.parametrize("ack", [False, 1, "true", None])
async def test_start_requires_actual_boolean_idle_ack(execution, ack):
    _, client, fake = execution
    plan = await client.post(
        "/api/tasks/task:a/preflight", json={"revision": 1, "operation": "sync_build_release"}
    )
    response = await client.post(
        "/api/tasks/task:a/runs",
        json={
            "plan_id": plan.json()["plan_id"],
            "request_id": str(uuid.uuid4()),
            "ack_old_app_idle": ack,
        },
    )
    assert response.status_code == 422
    assert fake.writes == 0


async def test_duplicate_logical_effect_cannot_issue_a_second_remote_write(execution, monkeypatch):
    app, client, fake = execution

    async def duplicate(context):
        for _ in range(2):
            effect = await context.intent("build_create", {"definition_id": 1})
            fake.writes += 1
            await context.receipt(effect, "confirmed", remote_id="17", owned=True)
        return ExecutionOutcome("unknown", "remote_unknown")

    monkeypatch.setattr(fake, "execute", duplicate)
    rid, _ = await start(client)
    await asyncio.gather(*list(app.state.run_service.workers.values()))
    run = await app.state.run_store.get(rid)
    assert fake.writes == 1
    assert len(run["effects"]) == 1
    assert run["status"] == "unknown"


async def test_owned_build_cancel_has_journal_intent_after_stop_request(execution, monkeypatch):
    app, client, fake = execution

    async def owned(context):
        effect = await context.intent("build_create", {"definition_id": 1})
        fake.writes += 1
        await context.receipt(effect, "confirmed", remote_id="17", owned=True)
        fake.entered.set()
        await context.cancelled.wait()
        effect = await context.intent("build_cancel", {"build_id": 17, "api_kind": "build"})
        fake.writes += 1
        await context.receipt(effect, "confirmed", remote_id="17")
        await context.complete_step("failed")
        return ExecutionOutcome("cancelled")

    monkeypatch.setattr(fake, "execute", owned)
    rid, _ = await start(client)
    await asyncio.wait_for(fake.entered.wait(), 2)
    await client.post(f"/api/runs/{rid}/cancel")
    await asyncio.gather(*list(app.state.run_service.workers.values()))
    run = await app.state.run_store.get(rid)
    assert run["status"] == "cancelled"
    assert fake.writes == 2
    assert [e["kind"] for e in run["effects"]] == ["build_create", "build_cancel"]


@pytest.mark.parametrize(
    "owned,remote_id,stop", [(False, 17, True), (True, 99, True), (True, 17, False)]
)
async def test_remote_cancel_requires_stop_and_matching_owned_creation(
    execution, monkeypatch, owned, remote_id, stop
):
    app, client, fake = execution

    async def attempt(context):
        effect = await context.intent("build_create", {"definition_id": 1})
        fake.writes += 1
        await context.receipt(effect, "confirmed", remote_id="17", owned=owned)
        fake.entered.set()
        if stop:
            await context.cancelled.wait()
        effect = await context.intent("build_cancel", {"build_id": remote_id, "api_kind": "build"})
        fake.writes += 1
        await context.receipt(effect, "unknown")
        return ExecutionOutcome("unknown")

    monkeypatch.setattr(fake, "execute", attempt)
    rid, _ = await start(client)
    await asyncio.wait_for(fake.entered.wait(), 2)
    if stop:
        await client.post(f"/api/runs/{rid}/cancel")
    await asyncio.gather(*list(app.state.run_service.workers.values()))
    assert fake.writes == 1
    assert len((await app.state.run_store.get(rid))["effects"]) == 1


def test_json_escaped_credentials_are_rejected_and_redacted():
    from toolbox_backend.logging_setup import contains_secret, redact_exception

    secret = 'FAKE_S3_QUOTED_"_KEY_731'
    register_secret(secret)
    encoded = json.dumps({"text": secret})
    assert contains_secret(encoded)
    assert secret not in json.loads(redact_exception(encoded))["text"]


async def test_readonly_storage_error_is_visible_while_history_remains_readable(execution):
    from tests.test_s3_runs import request

    app, client, _ = execution
    run = await app.state.run_store.create(**request())
    app.state.run_store.readonly_error = "injected storage error"
    response = await client.get("/api/runs/" + run["run_id"])
    assert response.status_code == 200
    assert response.json()["store_error"] == "injected storage error"
    assert (await client.get("/api/tasks")).json()["items"][0]["warnings"]
    assert (await client.post("/api/runs/" + run["run_id"] + "/cancel")).status_code == 503


async def test_reconcile_rejects_client_supplied_remote_identity(execution):
    from tests.test_s3_runs import request

    app, client, fake = execution
    run = await app.state.run_store.create(**request())
    await app.state.run_store.transition(run["run_id"], 0, "running")
    await app.state.run_store.transition(run["run_id"], 1, "unknown")
    response = await client.post(
        "/api/runs/" + run["run_id"] + "/reconcile", json={"remote_id": "999", "owned": True}
    )
    assert response.status_code == 422
    assert fake.writes == 0


async def test_unexpected_reconcile_exception_remains_unknown_without_raw_error(
    execution, monkeypatch
):
    from tests.test_s3_runs import request

    app, _, fake = execution
    run = await app.state.run_store.create(**request())
    rid = run["run_id"]
    await app.state.run_store.transition(rid, 0, "running")
    await app.state.run_store.transition(rid, 1, "unknown")

    async def broken(_):
        raise RuntimeError("FAKE_RAW_REMOTE_BODY_MUST_NOT_ESCAPE")

    monkeypatch.setattr(fake, "reconcile", broken)
    await app.state.run_service.reconcile(rid)
    results = await asyncio.gather(
        *list(app.state.run_service.reconciliations.values()), return_exceptions=True
    )
    assert not any(isinstance(r, Exception) for r in results)
    row = await app.state.run_store.get(rid)
    assert row["status"] == "unknown"
    assert "FAKE_RAW_REMOTE_BODY" not in json.dumps(row)
