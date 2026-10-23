"""S3-B transport contract and fault injection; all remote state is in memory."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.ado_tasks import AdoTaskExecutor
from toolbox_backend.adapters.fake_task_ado import FakeTaskADO
from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.domain.settings import Library, Project
from toolbox_backend.services.runs import ExecutionContext, RunService


def test_production_executor_is_available():
    from toolbox_backend.adapters.ado_tasks import AdoTaskExecutor

    assert callable(AdoTaskExecutor.prepare)


def test_release_version_error_is_explicit_and_bounded():
    import httpx
    import pytest

    from toolbox_backend.adapters.ado_read import AdoFailure, AdoRead
    from toolbox_backend.domain.settings import Library

    library = Library(id="lib:a", name="Fake", base_url="https://ado.test")
    for status, payload, supported in [
        (400, {"typeKey": "VssVersionNotSupportedException"}, True),
        (404, {"typeKey": "VssVersionNotSupportedException"}, True),
        (404, {"message": "not found"}, False),
        (403, {"typeKey": "VssVersionNotSupportedException"}, False),
    ]:
        http = AdoRead(
            httpx.MockTransport(
                lambda request, status=status, payload=payload: httpx.Response(status, json=payload)
            )
        )
        with pytest.raises(AdoFailure) as exc:
            http.request_json(library, "fake-pat-1234", "GET", ["c", "p", "_apis", "release"])
        assert getattr(exc.value, "version_unsupported", False) is supported


@pytest.fixture
async def task_harness(tmp_path):
    fake = FakeTaskADO(project="sample")
    project = Project(id="proj:a", library_id="lib:a", collection="c", project="sample")
    library = Library(id="lib:a", name="Fake", base_url="https://ado.test")

    async def snapshot(ident):
        assert ident == project.id
        return project, library, "fake-task-pat-1234"

    work = SimpleNamespace(http=AdoRead(httpx.MockTransport(fake)), snapshot=snapshot)
    executor = AdoTaskExecutor(work, None, build_interval=0.001, release_interval=0.001)
    store = RunStore(tmp_path / "data")
    await store.initialize()
    service = RunService(SimpleNamespace(), store, executor)
    task = {
        "id": "task:a",
        "name": "demo",
        "repo_id": "demo-repo",
        "local_repo_path": "",
        "agent_queue_id": None,
        "source": {
            "project_id": project.id,
            "library_id": library.id,
            "base_url": library.base_url,
            "collection": project.collection,
            "project": project.project,
        },
        "git_flow": {
            "build_branch": "main",
            "update_branches": [],
            "merges": [],
            "push_branches": [],
        },
        "targets": [
            {
                "name": "target",
                "enabled": True,
                "build_id": "11",
                "build_kind": "build",
                "release_id": "11",
                "release_stage_ids": ["1"],
                "release_stage_names": [],
            }
        ],
    }
    try:
        yield fake, executor, store, service, task
    finally:
        await service.close()


async def create_run(harness, operation="sync_build_release"):
    fake, executor, store, service, task = harness
    prepared = await executor.prepare(task, operation, 1 if operation == "rollback" else None)
    task["prepared"] = prepared.frozen
    run = await store.create(
        task_id=task["id"],
        operation=operation,
        request_id=str(uuid.uuid4()),
        request_hash="hash",
        config_revision=1,
        snapshot=task,
        resources=["fake:release"],
        steps=prepared.steps,
        deadline_at=(datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
    )
    return run


@pytest.mark.parametrize("operation", ["sync_build_release", "deploy_only", "rollback"])
async def test_three_operations_only_deploy_selected_environment(task_harness, operation):
    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness, operation)
    await service._execute_worker(run["run_id"], asyncio.Event())
    result = await store.get(run["run_id"])
    assert result["status"] == "succeeded", result
    writes = fake.writes
    deploys = [w for w in writes if w[0] == "PATCH"]
    assert len(deploys) == 1 and deploys[0][1].endswith("1")
    if operation == "rollback":
        assert len(writes) == 1
    else:
        releases = [w for w in writes if w[0] == "POST" and w[1].endswith("/releases")]
        assert len(releases) == 1
        assert releases[0][2]["manualEnvironments"] == ["演示", "未选环境"]
    if operation == "deploy_only":
        assert not any(w[1].endswith("/builds") for w in writes)
    if operation == "sync_build_release":
        assert writes[0][2]["sourceVersion"] == "a" * 40


async def test_response_loss_never_replays_release_or_deployment(task_harness):
    fake, executor, store, service, task = task_harness
    task["targets"][0].update(build_id="13", release_id="13")
    run = await create_run(task_harness, "deploy_only")
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "unknown"
    before = list(fake.writes)
    for _ in range(2):
        await service.reconcile(run["run_id"])
        await asyncio.gather(*list(service.reconciliations.values()))
        await service.cancel(run["run_id"])
    assert fake.writes == before
    assert len(before) == 2


async def test_partial_success_never_creates_release(task_harness):
    fake, executor, store, service, task = task_harness
    original = fake.build

    def partial(ident, definition):
        return {**original(ident, definition), "result": "partiallySucceeded"}

    fake.build = partial
    run = await create_run(task_harness)
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "failed"
    assert not any("/release/" in w[1] for w in fake.writes)
    assert (await store.get(run["run_id"]))["steps"][0]["status"] == "failed"


async def test_lost_env_receipt_is_queried_and_confirmed_without_rewrite(task_harness):
    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness, "deploy_only")
    original = fake.handle
    lost = False

    def lose(request):
        nonlocal lost
        response = original(request)
        if request.method == "PATCH" and not lost:
            lost = True
            raise httpx.ReadError("delivered", request=request)
        return response

    fake.handle = lose
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "unknown"
    before = list(fake.writes)
    await service.reconcile(run["run_id"])
    await asyncio.gather(*list(service.reconciliations.values()))
    result = await store.get(run["run_id"])
    assert result["status"] == "succeeded"
    assert all(e["state"] == "confirmed" for e in result["effects"])
    assert before == fake.writes


async def test_one_failed_stage_does_not_hide_another_running_stage(task_harness):
    fake, executor, store, service, task = task_harness
    task["targets"][0]["release_stage_ids"] = ["1", "2"]
    run = await create_run(task_harness, "deploy_only")
    stop = asyncio.Event()
    original = fake.handle

    def mixed(request):
        response = original(request)
        if request.method == "PATCH":
            ident = int(request.url.path.split("/")[-1])
            release = fake.releases[int(request.url.path.split("/")[-3])]
            env = next(e for e in release["environments"] if e["id"] == ident)
            env["status"] = "rejected" if ident % 10 == 1 else "inProgress"
            if ident % 10 == 2:
                stop.set()
        return response

    fake.handle = mixed
    await service._execute_worker(run["run_id"], stop)
    assert (await store.get(run["run_id"]))["status"] == "unknown"


async def test_cancel_poll_does_not_busy_loop_on_set_event(task_harness):
    import time

    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness)
    await store.transition(run["run_id"], 0, "running")
    stop = asyncio.Event()
    stop.set()
    context = ExecutionContext(service, await store.get(run["run_id"]), stop)
    start = time.monotonic()
    await executor.pause(context, 0.02)
    assert time.monotonic() - start >= 0.015


def test_artifact_snapshot_does_not_copy_unrecognized_remote_json(task_harness):
    # Pure shaping can be inspected without an active request context.
    artifact = {
        "alias": "demo",
        "type": "Build",
        "definitionReference": {
            "project": {
                "id": "sample",
                "name": "sample",
                "secret_extension": {"arbitrary": "remote"},
            },
            "definition": {"id": "11", "name": "demo"},
            "future": {"unbounded": ["remote"]},
        },
    }
    _, executor, *_ = task_harness
    result = executor.artifact(
        {"source": {"project": "sample"}}, {"definition_id": 11}, {"artifacts": [artifact]}
    )
    assert set(result["definitionReference"]) == {"project", "definition"}
    assert set(result["definitionReference"]["project"]) == {"id", "name"}


async def test_rollback_freezes_environment_identity_and_attempt(task_harness):
    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness, "rollback")
    target = task["prepared"]["targets"][0]
    old = fake.releases[target["release_id"]]["environments"][0]
    old["id"] += 10000
    old["deploySteps"].append({"attempt": 2})
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert fake.writes == []
    assert (await store.get(run["run_id"]))["status"] == "failed"


async def test_s1_s2_s3_share_six_outbound_permits(task_harness, monkeypatch):
    import threading

    import toolbox_backend.services.work_items as common
    from toolbox_backend.adapters.ado_http import AdoHTTP
    from toolbox_backend.api.settings_schemas import TestRequest
    from toolbox_backend.services.settings import SettingsService
    from toolbox_backend.services.work_items import WorkItemsService

    fake, executor, store, service, task = task_harness
    active = maximum = entered = 0
    lock, release = threading.Lock(), threading.Event()
    six = threading.Event()

    def handler(request):
        nonlocal active, maximum, entered
        with lock:
            active += 1
            entered += 1
            maximum = max(maximum, active)
            if active == 6:
                six.set()
        try:
            assert release.wait(3)
            return httpx.Response(200, json={"value": []})
        finally:
            with lock:
                active -= 1

    # Reset only loop affinity; all three real callers import this same process gate.
    monkeypatch.setattr(common, "OUTBOUND", asyncio.Semaphore(6))
    transport = httpx.MockTransport(handler)
    executor.http = AdoRead(transport)
    project, library, pat = await executor.source(task)

    class ConfigSnapshot:
        async def run(self, revision, fn):
            config = SimpleNamespace(ado=SimpleNamespace(libraries=[library]))
            return fn(SimpleNamespace(config=config))

    settings = object.__new__(SettingsService)
    settings.store, settings.http = ConfigSnapshot(), AdoHTTP(transport)
    settings._get = lambda key: pat
    work_items = WorkItemsService(settings, executor.http)
    jobs = [
        asyncio.create_task(fn)
        for _ in range(4)
        for fn in (
            settings.connection(library.id, TestRequest(collection=project.collection)),
            work_items.request((project, library, pat), "GET", ["workitems", "1"]),
            executor.request(task, ["build", "builds", 1]),
        )
    ]
    try:
        assert await asyncio.to_thread(six.wait, 2)
        await asyncio.sleep(0.02)
        assert maximum == 6 and entered == 6
        release.set()
        await asyncio.gather(*jobs)
        assert maximum == 6 and entered == 12
    finally:
        release.set()
        await asyncio.gather(*jobs, return_exceptions=True)


@pytest.mark.parametrize("fault", ["empty_manual_conditions", "unselected_started"])
async def test_unproven_or_broken_manual_environment_guarantee_never_succeeds(task_harness, fault):
    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness, "deploy_only")
    original = fake.handle

    def unsafe(request):
        response = original(request)
        if fault == "empty_manual_conditions" and request.method == "POST":
            for release in fake.releases.values():
                for env in release["environments"]:
                    env["conditions"] = []
        if fault == "unselected_started" and request.method == "PATCH":
            release = fake.releases[int(request.url.path.split("/")[-3])]
            release["environments"][1]["status"] = "inProgress"
        return response

    fake.handle = unsafe
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "unknown"
    if fault == "empty_manual_conditions":
        assert len(fake.writes) == 1


@pytest.mark.parametrize(
    "point", ["build_create", "pipeline_create", "release_create", "env_deploy", "build_cancel"]
)
@pytest.mark.parametrize("receipt_failure", [False, True])
async def test_every_remote_write_delivery_gap_survives_restart_without_replay(
    task_harness, point, receipt_failure
):
    import sqlite3

    fake, executor, store, service, task = task_harness
    if point == "pipeline_create":
        task["targets"][0]["build_kind"] = "pipeline"
    run = await create_run(task_harness)
    stop = asyncio.Event()
    original = fake.handle
    triggered = False
    loop = asyncio.get_running_loop()

    def delivery_gap(request):
        nonlocal triggered
        response = original(request)
        path, method = request.url.path, request.method
        if point == "build_cancel" and method == "POST" and path.endswith("/builds"):
            fake.builds[response.json()["id"]]["status"] = "inProgress"
        if (
            point == "build_cancel"
            and method == "GET"
            and "/build/builds/" in path
            and int(path.split("/")[-1]) > 100
        ):
            loop.call_soon_threadsafe(stop.set)
        matches = (
            point == "build_create"
            and method == "POST"
            and path.endswith("/builds")
            or point == "pipeline_create"
            and method == "POST"
            and path.endswith("/runs")
            or point == "release_create"
            and method == "POST"
            and path.endswith("/releases")
            or point == "env_deploy"
            and method == "PATCH"
            and "/environments/" in path
            or point == "build_cancel"
            and method == "PATCH"
            and "/build/builds/" in path
        )
        if matches and not triggered:
            triggered = True
            if receipt_failure:

                def fail(label):
                    raise sqlite3.OperationalError("injected receipt commit")

                store.checkpoint = fail
            else:
                raise httpx.ReadError("delivered but response lost", request=request)
        return response

    fake.handle = delivery_gap
    try:
        await service._execute(run["run_id"], stop)
    finally:
        store.checkpoint = lambda _: None
    assert triggered
    await store.recover()
    assert (await store.get(run["run_id"]))["status"] == "unknown"
    writes = list(fake.writes)
    for _ in range(2):
        await service.reconcile(run["run_id"])
        await asyncio.gather(*list(service.reconciliations.values()))
    assert fake.writes == writes
    assert (await store.get(run["run_id"]))["status"] in {
        "unknown",
        "failed",
        "succeeded",
        "cancelled",
    }


async def test_owned_build_cancel_requires_terminal_confirmation(task_harness):
    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness)
    stop = asyncio.Event()
    original = fake.handle
    loop = asyncio.get_running_loop()

    def running(request):
        response = original(request)
        if request.method == "POST" and request.url.path.endswith("/builds"):
            fake.builds[response.json()["id"]]["status"] = "inProgress"
        if (
            request.method == "GET"
            and "/build/builds/" in request.url.path
            and int(request.url.path.split("/")[-1]) > 100
        ):
            loop.call_soon_threadsafe(stop.set)
        return response

    fake.handle = running
    await service._execute_worker(run["run_id"], stop)
    result = await store.get(run["run_id"])
    assert result["status"] == "cancelled"
    assert sum(w[0] == "PATCH" and "/build/builds/" in w[1] for w in fake.writes) == 1
    assert not any("/release/" in w[1] for w in fake.writes)


async def test_artifact_identity_is_never_truncated(task_harness):
    from toolbox_backend.domain.errors import SettingsError

    fake, executor, store, service, task = task_harness
    artifact = fake.artifact(11)
    artifact["alias"] = "a" * 201
    with pytest.raises(SettingsError) as exc:
        executor.artifact(task, {"definition_id": 11}, {"artifacts": [artifact]})
    assert exc.value.code == "unsupported_task"


@pytest.mark.parametrize("field", ["project", "repository", "definition", "queue"])
async def test_malformed_identity_containers_are_not_reusable(task_harness, field):
    fake, executor, store, service, task = task_harness
    task["agent_queue_id"] = "1"
    target = {"definition_id": 11}
    detail = fake.build(11, 11)
    detail[field] = None
    assert executor.identity(task, target, detail, "a" * 40) is False


@pytest.mark.parametrize(
    "suffix", [["build", "..", "builds"], ["build", "%2e%2e", "builds"], ["build", "x/y", "builds"]]
)
async def test_task_path_escape_is_rejected_before_transport(task_harness, suffix):
    from toolbox_backend.adapters.ado_read import AdoFailure

    fake, executor, store, service, task = task_harness
    calls = []
    executor.http = AdoRead(
        httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json={}))
    )
    with pytest.raises(AdoFailure):
        await executor.request(task, suffix)
    assert calls == []


async def test_task_redirect_never_forwards_credentials(task_harness):
    from toolbox_backend.adapters.ado_read import AdoFailure

    fake, executor, store, service, task = task_harness
    calls = []
    executor.http = AdoRead(
        httpx.MockTransport(
            lambda request: (
                calls.append(request)
                or httpx.Response(302, headers={"location": "https://evil.test/collect"})
            )
        )
    )
    with pytest.raises(AdoFailure) as exc:
        await executor.request(task, ["build", "builds", 1])
    assert exc.value.category == "redirect"
    assert len(calls) == 1 and calls[0].url.host == "ado.test"


async def test_real_executor_start_and_cancel_are_idempotent(task_harness):
    # The real executor's delivery counts stay stable across the durable HTTP acceptance path.
    fake, executor, store, service, task = task_harness
    from toolbox_backend.api.task_schemas import StartRequest

    run = await create_run(task_harness)
    await service._execute_worker(run["run_id"], asyncio.Event())
    result = await store.get(run["run_id"])
    assert result["status"] == "succeeded"
    before = list(fake.writes)
    await service.cancel(run["run_id"])
    await service.cancel(run["run_id"])
    assert await service.reconcile(run["run_id"]) == await store.get(run["run_id"])
    assert fake.writes == before
    # Matching request hash is checked before touching an expired plan/config.
    import hashlib

    body = StartRequest(plan_id=uuid.uuid4(), request_id=uuid.uuid4(), ack_old_app_idle=True)
    digest = hashlib.sha256(
        json.dumps(
            {"task_id": "task:stored", **body.model_dump(mode="json")}, sort_keys=True
        ).encode()
    ).hexdigest()
    accepted = await store.create(
        task_id="task:stored",
        operation="sync_build_release",
        request_id=str(body.request_id),
        request_hash=digest,
        config_revision=1,
        snapshot=task,
        resources=[],
        steps=[],
        deadline_at=(datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
    )
    for _ in range(2):
        assert await service.start("task:stored", body) == {"run_id": accepted["run_id"]}
    assert fake.writes == before


@pytest.mark.parametrize(
    "status,explicit,count",
    [
        (400, True, 2),
        (404, True, 2),
        (400, False, 1),
        (404, False, 1),
        (401, True, 1),
        (403, True, 1),
    ],
)
async def test_release_get_negotiation_only_for_explicit_version_error(
    task_harness, status, explicit, count
):
    from toolbox_backend.adapters.ado_read import AdoFailure

    fake, executor, store, service, task = task_harness
    seen = []

    def handler(request):
        seen.append(request.url.params["api-version"])
        if len(seen) == 1:
            return httpx.Response(
                status,
                json={"typeKey": "VssVersionNotSupportedException" if explicit else "NotFound"},
            )
        return httpx.Response(200, json={"id": 11})

    executor.http = AdoRead(httpx.MockTransport(handler))
    if count == 2:
        definition, version = await executor.definition(task, 11)
        assert definition["id"] == 11 and version == "7.0"
        assert seen == ["6.0", "7.0"]
    else:
        with pytest.raises(AdoFailure):
            await executor.definition(task, 11)
        assert seen == ["6.0"]


async def test_release_marker_cannot_override_wrong_artifact_binding(task_harness):
    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness, "deploy_only")
    original = fake.handle

    def loss(request):
        response = original(request)
        if request.method == "POST" and request.url.path.endswith("/releases"):
            fake.releases[response.json()["id"]]["artifacts"][0]["alias"] = "wrong-alias"
            raise httpx.ReadError("delivered", request=request)
        return response

    fake.handle = loss
    await service._execute_worker(run["run_id"], asyncio.Event())
    await service.reconcile(run["run_id"])
    await asyncio.gather(*list(service.reconciliations.values()))
    result = await store.get(run["run_id"])
    assert result["status"] == "unknown"
    assert result["effects"][0]["state"] == "intent"
    assert len(fake.writes) == 1


async def test_stop_during_readonly_head_check_is_local_cancelled(task_harness):
    fake, executor, store, service, task = task_harness
    run = await create_run(task_harness)
    stop = asyncio.Event()
    original = fake.handle
    loop = asyncio.get_running_loop()

    def stop_on_head(request):
        response = original(request)
        if request.url.path.endswith("/refs"):
            loop.call_soon_threadsafe(stop.set)
        return response

    fake.handle = stop_on_head
    await service._execute_worker(run["run_id"], stop)
    result = await store.get(run["run_id"])
    assert result["status"] == "cancelled"
    assert result["effects"] == []
    assert fake.writes == []


async def test_malformed_preflight_remote_shape_is_a_bounded_ado_error(task_harness):
    from toolbox_backend.adapters.ado_read import AdoFailure

    fake, executor, store, service, task = task_harness
    original = fake.handle

    def malformed(request):
        if "/release/definitions/" in request.url.path:
            return httpx.Response(200, json={"id": 11, "artifacts": None, "environments": []})
        return original(request)

    fake.handle = malformed
    with pytest.raises(AdoFailure) as exc:
        await executor.prepare(task, "deploy_only", None)
    assert exc.value.category == "bad_response"
    assert fake.writes == []
