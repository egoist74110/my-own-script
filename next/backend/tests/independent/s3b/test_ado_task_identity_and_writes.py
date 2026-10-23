"""S3-B ADO task execution identity and write-boundary tests."""

import asyncio
import copy
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoFailure, AdoRead
from toolbox_backend.adapters.ado_tasks import AdoTaskExecutor
from toolbox_backend.adapters.run_store import RunStore
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Library, Project
from toolbox_backend.services.runs import ExecutionContext, RunService

PROJECT = Project(
    id="project-id", library_id="library-id", collection="collection", project="sample"
)
LIBRARY = Library(id="library-id", name="Fake", base_url="https://ado.test")
PAT = "FAKE_S3B_PAT_7193"
EXPECTED_COMMIT = "a" * 40
TARGET = {"target_index": 0, "name": "target", "definition_id": 7, "api_kind": "build"}


@pytest.fixture
async def run_environment(tmp_path):
    store = RunStore(tmp_path / "data")
    await store.initialize()
    service = RunService(SimpleNamespace(), store)
    try:
        yield service, store
    finally:
        await service.close()


class FakeWorkItems:
    def __init__(self, handler, source=None):
        self.http = AdoRead(httpx.MockTransport(handler))
        self.source = source or (PROJECT, LIBRARY, PAT)

    async def snapshot(self, project_id):
        assert project_id == "project-id"
        return self.source


def snapshot(*, queue_id="12"):
    return {
        "id": "task:s3b",
        "source": {
            "project_id": PROJECT.id,
            "library_id": LIBRARY.id,
            "base_url": LIBRARY.base_url,
            "collection": PROJECT.collection,
            "project": PROJECT.project,
        },
        "repo_id": "repo-1",
        "git_flow": {
            "build_branch": "main",
            "update_branches": [],
            "merges": [],
            "push_branches": [],
        },
        "agent_queue_id": queue_id,
        "local_repo_path": "",
        "prepared": {"commit": EXPECTED_COMMIT, "targets": [copy.deepcopy(TARGET)]},
    }


def build_detail(
    ident,
    *,
    project="sample",
    repository="repo-1",
    definition=7,
    branch="refs/heads/main",
    source_version=EXPECTED_COMMIT,
    queue=12,
):
    result = {
        "id": ident,
        "project": {"name": project},
        "repository": {"id": repository},
        "definition": {"id": definition},
        "sourceBranch": branch,
        "sourceVersion": source_version,
        "status": "inProgress",
    }
    if queue is not None:
        result["queue"] = {"id": queue}
    return result


async def active_context(service, store, run_snapshot):
    payload = {
        "task_id": "task:ado",
        "operation": "sync_build_release",
        "request_id": str(uuid.uuid4()),
        "request_hash": uuid.uuid4().hex,
        "config_revision": 1,
        "snapshot": run_snapshot,
        "resources": ["build:identity"],
        "steps": [{"kind": "build", "target_index": 0}],
        "deadline_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    run = await store.create(**payload)
    await store.transition(run["run_id"], 0, "running")
    return ExecutionContext(service, await store.get(run["run_id"]), asyncio.Event())


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("project_mismatch", "other-project"),
        ("project_missing", None),
        ("repository", "another-repo"),
        ("repository_missing", None),
        ("definition", 8),
        ("definition_missing", None),
        ("branch", "refs/heads/other"),
        ("branch_missing", None),
        ("source_version", "b" * 40),
        ("source_version_missing", None),
        ("queue", 99),
        ("queue_missing", None),
    ],
)
async def test_build_reuse_requires_every_identity_field(
    run_environment, field, wrong_value
):
    service, store = run_environment
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"value": [{"id": 81}]})
        if request.method == "GET" and path.endswith("/_apis/build/builds/81"):
            row = build_detail(81)
            if field == "queue_missing":
                row.pop("queue")
            elif field == "queue":
                row["queue"]["id"] = wrong_value
            elif field == "project_missing":
                row.pop("project")
            elif field == "project_mismatch":
                row["project"]["name"] = wrong_value
            elif field == "repository_missing":
                row.pop("repository")
            elif field == "repository":
                row["repository"]["id"] = wrong_value
            elif field == "definition_missing":
                row.pop("definition")
            elif field == "definition":
                row["definition"]["id"] = wrong_value
            elif field == "branch_missing":
                row.pop("sourceBranch")
            elif field == "branch":
                row["sourceBranch"] = wrong_value
            elif field == "source_version_missing":
                row.pop("sourceVersion")
            elif field == "source_version":
                row["sourceVersion"] = wrong_value
            else:
                raise AssertionError(f"unhandled identity field: {field}")
            return httpx.Response(200, json=row)
        if request.method == "POST" and path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"id": 92})
        if request.method == "GET" and path.endswith("/_apis/build/builds/92"):
            return httpx.Response(200, json=build_detail(92))
        raise AssertionError(f"unexpected ADO request: {request.method} {path}")

    service.executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())
    context = await active_context(service, store, snapshot())

    build, owned = await service.executor.acquire_build(context, TARGET, EXPECTED_COMMIT)

    assert build["id"] == 92
    assert owned is True
    post_requests = [r for r in requests if r.method == "POST"]
    assert len(post_requests) == 1
    sent = json.loads(post_requests[0].content)
    assert sent == {
        "definition": {"id": 7},
        "sourceBranch": "refs/heads/main",
        "sourceVersion": EXPECTED_COMMIT,
        "queue": {"id": 12},
    }
    current = await store.get(context.run_id)
    assert len(current["effects"]) == 1
    assert current["effects"][0]["kind"] == "build_create"
    assert current["effects"][0]["owned"] is True


async def test_exact_build_identity_is_reused_without_any_write(run_environment):
    service, store = run_environment
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"value": [{"id": 81}]})
        if request.method == "GET" and request.url.path.endswith("/_apis/build/builds/81"):
            return httpx.Response(200, json=build_detail(81))
        raise AssertionError(f"unexpected ADO request: {request.method} {request.url.path}")

    service.executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())
    context = await active_context(service, store, snapshot())

    build, owned = await service.executor.acquire_build(context, TARGET, EXPECTED_COMMIT)

    assert build["id"] == 81
    assert owned is False
    assert all(request.method == "GET" for request in requests)
    assert (await store.get(context.run_id))["effects"] == []
    assert (await store.get(context.run_id))["steps"][0]["checkpoint"]["owned"] is False


async def test_build_detail_failure_never_takes_over_or_cancels_list_candidate(run_environment):
    service, store = run_environment
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"value": [{"id": 81}]})
        if request.method == "GET" and path.endswith("/_apis/build/builds/81"):
            return httpx.Response(403, json={"message": "private remote detail"})
        if request.method == "POST" and path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"id": 92})
        if request.method == "GET" and path.endswith("/_apis/build/builds/92"):
            return httpx.Response(200, json=build_detail(92))
        raise AssertionError(f"unexpected ADO request: {request.method} {path}")

    service.executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())
    context = await active_context(service, store, snapshot())

    build, owned = await service.executor.acquire_build(context, TARGET, EXPECTED_COMMIT)

    assert (build["id"], owned) == (92, True)
    assert not any(
        request.method == "PATCH" and request.url.path.endswith("/_apis/build/builds/81")
        for request in requests
    )
    effect = (await store.get(context.run_id))["effects"][0]
    assert effect["remote_id"] == "92" and effect["owned"] is True


async def test_cancel_of_reused_unowned_build_sends_no_remote_write(run_environment):
    service, store = run_environment
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(500)

    service.executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())
    context = await active_context(service, store, snapshot())
    context.cancelled.set()

    result = await service.executor.wait_build(
        context, TARGET, build_detail(81), False, EXPECTED_COMMIT
    )

    assert result is None
    assert requests == []


@pytest.mark.parametrize(
    "pipeline",
    [
        {"id": 81, "_links": {}},
        {
            "id": 81,
            "_links": {
                "build": {
                    "href": "https://ado.test/collection/sample/_apis/pipelines/11/runs/81"
                }
            },
        },
    ],
)
async def test_pipeline_run_id_is_never_guessed_as_build_id(pipeline):
    requests = []

    def handler(request):
        requests.append(request)
        raise AssertionError("unverified pipeline IDs must not trigger a Build lookup")

    executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())
    target = {**TARGET, "api_kind": "pipeline"}

    with pytest.raises(SettingsError) as exc:
        await executor.pipeline_build(snapshot(), target, pipeline, EXPECTED_COMMIT)

    assert exc.value.code == "unsupported_task"
    assert requests == []


@pytest.mark.parametrize("operation", ["sync_build_release", "deploy_only", "rollback"])
async def test_disabled_target_is_never_prepared_for_execution(operation):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/_apis/git/repositories/repo-1/refs"):
            return httpx.Response(
                200,
                json={"value": [{"name": "refs/heads/main", "objectId": EXPECTED_COMMIT}]},
            )
        raise AssertionError(f"disabled target unexpectedly touched ADO: {request.url.path}")

    value = prepare_snapshot()
    value["targets"][0]["enabled"] = False
    executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())

    with pytest.raises(SettingsError) as exc:
        await executor.prepare(value, operation, 1 if operation == "rollback" else None)

    assert exc.value.code == "unsupported_task"
    assert all(request.method == "GET" for request in requests)
    assert not any("builds" in request.url.path or "releases" in request.url.path for request in requests)


@pytest.mark.parametrize(
    "changed_source",
    [
        (Project(id="other-project-id", library_id="library-id", collection="collection", project="sample"), LIBRARY, "OTHER_PAT"),
        (PROJECT, Library(id="other-library", name="Fake", base_url="https://elsewhere.test"), "OTHER_PAT"),
        (Project(id="project-id", library_id="library-id", collection="collection", project="renamed"), LIBRARY, "OTHER_PAT"),
    ],
)
async def test_changed_ado_source_blocks_before_any_request(run_environment, changed_source):
    service, store = run_environment
    requests = []

    def handler(request):
        requests.append(request)
        raise AssertionError("changed ADO source must be rejected before transport")

    service.executor = AdoTaskExecutor(
        FakeWorkItems(handler, source=changed_source), SimpleNamespace()
    )
    context = await active_context(service, store, snapshot())

    with pytest.raises(SettingsError) as exc:
        await service.executor.acquire_build(context, TARGET, EXPECTED_COMMIT)

    assert exc.value.code == "plan_changed"
    assert requests == []


def release_definition(*, artifacts=None):
    return {
        "id": 9,
        "artifacts": artifacts
        if artifacts is not None
        else [
            {
                "alias": "_self",
                "type": "Build",
                "definitionReference": {
                    "definition": {"id": "7"},
                    "project": {"name": "sample"},
                },
            }
        ],
        "environments": [
            {"id": 1, "name": "Build"},
            {"id": 2, "name": "Deploy"},
            {"id": 3, "name": "Verify"},
        ],
    }


class BuildCreateTransport:
    def __init__(self, *, lose_create_response=False):
        self.requests = []
        self.delivered = False
        self.lose_create_response = lose_create_response

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/_apis/git/repositories/repo-1/refs"):
            return httpx.Response(
                200,
                json={"value": [{"name": "refs/heads/main", "objectId": EXPECTED_COMMIT}]},
            )
        if request.method == "GET" and path.endswith("/_apis/build/definitions/7"):
            return httpx.Response(200, json={"id": 7, "repository": {"id": "repo-1"}})
        if request.method == "GET" and path.endswith("/_apis/release/definitions/9"):
            return httpx.Response(200, json=release_definition())
        if request.method == "GET" and path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"value": []})
        if request.method == "POST" and path.endswith("/_apis/build/builds"):
            self.delivered = True
            if self.lose_create_response:
                raise httpx.ReadTimeout("response deliberately lost", request=request)
            return httpx.Response(200, json={"id": 92})
        if request.method == "GET" and path.endswith("/_apis/build/builds/92"):
            return httpx.Response(200, json=build_detail(92))
        raise AssertionError(f"unexpected ADO request: {request.method} {path}")


async def execution_context_for(service, store, executor):
    run_snapshot = prepare_snapshot()
    prepared = await executor.prepare(run_snapshot, "sync_build_release", None)
    run_snapshot["prepared"] = prepared.frozen
    return await active_context(service, store, run_snapshot)


def prepare_snapshot(*, stage_ids=None):
    value = snapshot(queue_id=None)
    value["targets"] = [
        {
            "name": "target",
            "enabled": True,
            "build_kind": "build",
            "build_id": "7",
            "release_id": "9",
            "release_stage_ids": stage_ids or ["2"],
            "release_stage_names": [],
        }
    ]
    value.pop("prepared")
    return value


async def test_prepare_blocks_multiple_release_artifacts_before_any_write():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/_apis/git/repositories/repo-1/refs"):
            return httpx.Response(
                200,
                json={"value": [{"name": "refs/heads/main", "objectId": EXPECTED_COMMIT}]},
            )
        if request.url.path.endswith("/_apis/build/definitions/7"):
            return httpx.Response(200, json={"id": 7, "repository": {"id": "repo-1"}})
        if request.url.path.endswith("/_apis/release/definitions/9"):
            definition = release_definition()
            definition["artifacts"].append(copy.deepcopy(definition["artifacts"][0]))
            return httpx.Response(200, json=definition)
        raise AssertionError(f"unexpected ADO request: {request.method} {request.url.path}")

    executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())
    with pytest.raises(SettingsError) as exc:
        await executor.prepare(prepare_snapshot(), "sync_build_release", None)

    assert exc.value.code == "unsupported_task"
    assert all(request.method == "GET" for request in requests)


async def test_prepare_freezes_manual_environments_and_new_build_commit(run_environment):
    service, store = run_environment
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/_apis/git/repositories/repo-1/refs"):
            return httpx.Response(
                200,
                json={"value": [{"name": "refs/heads/main", "objectId": EXPECTED_COMMIT}]},
            )
        if request.url.path.endswith("/_apis/build/definitions/7"):
            return httpx.Response(200, json={"id": 7, "repository": {"id": "repo-1"}})
        if request.url.path.endswith("/_apis/release/definitions/9"):
            return httpx.Response(200, json=release_definition())
        if request.method == "GET" and request.url.path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"value": []})
        if request.method == "POST" and request.url.path.endswith("/_apis/build/builds"):
            return httpx.Response(200, json={"id": 92})
        if request.method == "GET" and request.url.path.endswith("/_apis/build/builds/92"):
            return httpx.Response(200, json=build_detail(92))
        raise AssertionError(f"unexpected ADO request: {request.method} {request.url.path}")

    executor = AdoTaskExecutor(FakeWorkItems(handler), SimpleNamespace())
    run_snapshot = prepare_snapshot()
    prepared = await executor.prepare(run_snapshot, "sync_build_release", None)

    frozen = prepared.frozen["targets"][0]
    assert prepared.frozen["commit"] == EXPECTED_COMMIT
    assert frozen["stage_ids"] == [2]
    assert frozen["manual_environments"] == ["Build", "Deploy", "Verify"]
    run_snapshot["prepared"] = prepared.frozen
    context = await active_context(service, store, run_snapshot)
    build, owned = await executor.acquire_build(
        context, frozen, prepared.frozen["commit"]
    )

    assert build["id"] == 92 and owned is True
    post = next(request for request in requests if request.method == "POST")
    assert json.loads(post.content)["sourceVersion"] == prepared.frozen["commit"]
    assert json.loads(post.content)["sourceBranch"] == "refs/heads/main"


async def test_lost_build_create_response_is_recorded_and_never_resent(run_environment):
    service, store = run_environment
    transport = BuildCreateTransport(lose_create_response=True)
    executor = AdoTaskExecutor(FakeWorkItems(transport), SimpleNamespace())
    service.executor = executor
    context = await execution_context_for(service, store, executor)

    with pytest.raises(AdoFailure):
        await executor.execute(context)

    after_delivery = await store.get(context.run_id)
    assert after_delivery["effects"][0]["state"] == "intent"
    assert after_delivery["effects"][0]["kind"] == "build_create"
    delivery_boundary = len(transport.requests)

    await store.recover()
    recovered = await store.get(context.run_id)
    readonly = ExecutionContext(service, recovered, asyncio.Event(), readonly=True)
    first = await executor.reconcile(readonly)
    second = await executor.reconcile(readonly)

    assert first.status == second.status == "unknown"
    assert sum(request.method == "POST" for request in transport.requests) == 1
    assert all(request.method == "GET" for request in transport.requests[delivery_boundary:])


async def test_receipt_commit_failure_after_delivery_stays_unknown_without_replay(
    run_environment,
):
    service, store = run_environment
    transport = BuildCreateTransport()
    executor = AdoTaskExecutor(FakeWorkItems(transport), SimpleNamespace())
    service.executor = executor
    context = await execution_context_for(service, store, executor)
    original_checkpoint = store.checkpoint

    def fail_commit_after_remote_delivery(label):
        if transport.delivered:
            raise sqlite3.OperationalError("injected receipt commit failure")
        original_checkpoint(label)

    store.checkpoint = fail_commit_after_remote_delivery
    try:
        with pytest.raises(SettingsError) as exc:
            await executor.execute(context)
        assert exc.value.code == "run_store_unavailable"
    finally:
        store.checkpoint = original_checkpoint

    before_recovery = await store.get(context.run_id)
    assert before_recovery["effects"][0]["state"] == "intent"
    assert sum(request.method == "POST" for request in transport.requests) == 1
    delivery_boundary = len(transport.requests)
    await store.recover()
    recovered = await store.get(context.run_id)
    readonly = ExecutionContext(service, recovered, asyncio.Event(), readonly=True)

    result = await executor.reconcile(readonly)

    assert result.status == "unknown"
    assert sum(request.method == "POST" for request in transport.requests) == 1
    assert all(request.method == "GET" for request in transport.requests[delivery_boundary:])
    with pytest.raises(SettingsError) as reservation:
        await store.create(
            **{
                "task_id": "task:replacement",
                "operation": "sync_build_release",
                "request_id": str(uuid.uuid4()),
                "request_hash": uuid.uuid4().hex,
                "config_revision": 1,
                "snapshot": {"id": "task:replacement"},
                "resources": ["build:identity"],
                "steps": [],
                "deadline_at": "2099-01-01T00:00:00+00:00",
            }
        )
    assert reservation.value.code == "resource_active"
