"""ADO Server 6.0 制品表示、失败原因与运行日志回归。"""

# 协作测试复用邻近 fixture。
# ruff: noqa: F811

import asyncio
import itertools
import json

import httpx
import pytest

from tests.test_s3b_ado_tasks import create_run, task_harness  # noqa: F401
from toolbox_backend.adapters.ado_tasks import (
    artifact_build_id,
    attempt,
    deployment_result,
    manual_environment,
    require_artifact_identity,
)
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.logging_setup import register_secret


@pytest.mark.parametrize("operation", ["sync_build_release", "deploy_only", "rollback"])
@pytest.mark.parametrize("lost", [None, "release", "deploy"])
async def test_renamed_build_definition_keeps_artifact_identity(task_harness, operation, lost):
    fake, _, store, service, _ = task_harness
    server_deployment_responses(fake, lose_patch=lost == "deploy")
    original_artifact, original_handle = fake.artifact, fake.handle

    def artifact(*args):
        result = original_artifact(*args)
        result["definitionReference"]["definition"]["name"] = "缓存旧名"
        return result

    fake.artifact = artifact

    def handle(request):
        response = original_handle(request)
        if "/release/releases" in request.url.path and request.method in {"GET", "POST"}:
            payload = response.json()
            for release in payload.get("value", [payload]):
                for art in release.get("artifacts", []):
                    refs = art["definitionReference"]
                    refs["definition"]["name"] = "构建定义新名"
                    refs["definition"]["id"] = int(refs["definition"]["id"])
                    refs["project"]["id"] = refs["project"]["id"].upper()
                    refs["project"]["name"] = "项目展示新名"
            if lost == "release" and request.method == "POST":
                raise httpx.ReadError("创建回执丢失", request=request)
            return httpx.Response(200, json=payload)
        return response

    fake.handle = handle
    run = await create_run(task_harness, operation)
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    writes = list(fake.writes)
    if lost == "deploy" or (lost == "release" and operation != "rollback"):
        assert (await store.get(rid))["status"] == "unknown"
        await service.reconcile(rid)
        await asyncio.gather(*list(service.reconciliations.values()))
        assert fake.writes == writes
    result = await store.get(rid)
    if lost == "release" and operation != "rollback":
        # 只读核实确认创建已送达，不会补发尚未执行的部署。
        assert result["status"] == "failed"
        assert result["effects"][-1]["state"] == "confirmed"
        assert not any(w[0] == "PATCH" for w in writes)
    else:
        assert result["status"] == "succeeded", result
        assert len([w for w in writes if w[0] == "PATCH"]) == 1


@pytest.mark.parametrize("field,value", [
    ("definition", "999"), ("project", "other-project"), ("alias", "_other"),
])
async def test_artifact_identity_change_rejected_with_specific_reason(task_harness, field, value):
    fake, _, store, service, _ = task_harness
    server_deployment_responses(fake)
    original = fake.release

    def release(*args, **kwargs):
        result = original(*args, **kwargs)
        art = result["artifacts"][0]
        if field == "alias":
            art[field] = value
        else:
            art["definitionReference"][field]["id"] = value
        return result

    fake.release = release
    run = await create_run(task_harness)
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    before = await store.get(rid)
    key = "alias" if field == "alias" else f"definitionReference.{field}.id"
    assert before["status"] == "unknown"
    assert key in before["summary"] and value in before["summary"]
    assert key in await logs(store, rid)
    assert not any(w[0] == "PATCH" for w in fake.writes)
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    assert (await store.get(rid))["summary"].startswith(before["summary"])


def test_artifact_identity_checks_type_and_requires_project_id():
    artifact = {
        "alias": "_demo", "type": "Build",
        "definitionReference": {
            "project": {"id": "A3530F08-ABCD", "name": "旧名"},
            "definition": {"id": "168", "name": "旧名"},
        },
    }
    changed = {**artifact, "type": "Other"}
    with pytest.raises(SettingsError, match="type: 预期='Build'，实际='Other'"):
        require_artifact_identity(changed, artifact, "制品绑定不符")
    artifact["definitionReference"]["project"].pop("id")
    with pytest.raises(SettingsError, match="definitionReference.project.id 缺失或无效"):
        require_artifact_identity(artifact, artifact, "制品绑定不符")


async def test_definition_rename_between_confirmation_and_creation(task_harness):
    fake, _, store, service, _ = task_harness
    run = await create_run(task_harness)
    original = fake.artifact

    def artifact(*args):
        result = original(*args)
        result["definitionReference"]["definition"]["name"] = "确认后改名"
        return result

    fake.artifact = artifact
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "succeeded"
    assert len([w for w in fake.writes if w[0] == "PATCH"]) == 1


def server_artifact(artifact, sources):
    ident = artifact.pop("instanceReference")["id"]
    refs = artifact["definitionReference"]
    if "instance" in sources:
        artifact["instanceReference"] = {"id": ident}
    if "version" in sources:
        refs["version"] = {"id": ident, "name": ident}
    if "uri" in sources:
        refs["buildUri"] = {"id": f"vstfs:///Build/Build/{ident}", "name": None}


def server_responses(fake, sources, *, lose_release=False):
    original_release, original_handle = fake.release, fake.handle

    def release(*args, **kwargs):
        result = original_release(*args, **kwargs)
        server_artifact(result["artifacts"][0], sources)
        return result

    fake.release = release
    for result in fake.releases.values():
        server_artifact(result["artifacts"][0], sources)

    def handle(request):
        response = original_handle(request)
        if lose_release and request.method == "POST" and request.url.path.endswith("/releases"):
            raise httpx.ReadError("不应输出原始异常或授权头", request=request)
        return response

    fake.handle = handle


@pytest.mark.parametrize("operation", ["sync_build_release", "deploy_only", "rollback"])
@pytest.mark.parametrize("sources", [("version",), ("uri",), ("version", "uri")])
async def test_server_artifact_continues_only_selected_environment(task_harness, operation, sources):
    fake, _, store, service, _ = task_harness
    server_responses(fake, sources)
    run = await create_run(task_harness, operation)
    await service._execute_worker(run["run_id"], asyncio.Event())
    result = await store.get(run["run_id"])
    assert result["status"] == "succeeded", result
    deploys = [w for w in fake.writes if w[0] == "PATCH"]
    assert len(deploys) == 1 and deploys[0][1].endswith("1")
    assert all(
        r["environments"][1]["status"] == "notStarted"
        for r in fake.releases.values() if r["id"] > 200
    )


@pytest.mark.parametrize("sources", [(), ("instance", "version", "uri")])
async def test_bad_identity_never_deploys_and_preserves_reason(task_harness, sources):
    fake, _, store, service, _ = task_harness
    server_responses(fake, sources)
    if sources:
        original = fake.release

        def conflict(*args, **kwargs):
            result = original(*args, **kwargs)
            result["artifacts"][0]["definitionReference"]["version"]["id"] = "999"
            return result

        fake.release = conflict
    run = await create_run(task_harness)
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    before = await store.get(rid)
    assert before["status"] == "unknown"
    assert "Release 具体制品不符（Release #201 已创建，环境未部署）" in before["summary"]
    assert not any(w[0] == "PATCH" for w in fake.writes)
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    after = await store.get(rid)
    assert after["status"] == "failed"
    assert after["summary"].startswith(before["summary"])
    assert "剩余步骤未执行" in after["summary"]


@pytest.mark.parametrize("sources", [("version",), ("uri",), ("version", "uri")])
async def test_lost_receipt_reconciles_server_identity_without_writes(task_harness, sources):
    fake, _, store, service, _ = task_harness
    server_responses(fake, sources, lose_release=True)
    run = await create_run(task_harness)
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    assert (await store.get(rid))["status"] == "unknown"
    before = list(fake.writes)
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    result = await store.get(rid)
    assert result["status"] == "failed"
    assert result["effects"][-1]["state"] == "confirmed"
    assert fake.writes == before


@pytest.mark.parametrize("ids", list(itertools.product((64778, 999), repeat=3)))
def test_all_identity_sources_must_agree(ids):
    artifact = {
        "instanceReference": {"id": str(ids[0])},
        "definitionReference": {
            "version": {"id": str(ids[1])},
            "buildUri": {"id": f"vstfs:///Build/Build/{ids[2]}"},
        },
    }
    if len(set(ids)) == 1:
        assert artifact_build_id(artifact) == ids[0]
    else:
        with pytest.raises(SettingsError, match="Release 具体制品不符"):
            artifact_build_id(artifact)


async def logs(store, rid):
    events = await store.events(rid, limit=500)
    return "".join(e["payload"].get("text", "") for e in events["items"])


async def test_success_logs_include_build_release_and_redact_pat(task_harness):
    fake, _, store, service, task = task_harness
    secret = "fake-task-pat-1234"
    register_secret(secret)
    original_build = fake.build

    def build(*args):
        result = original_build(*args)
        result["definition"]["name"] = "演示定义 " + secret
        return result

    fake.build = build
    server_responses(fake, ("version", "uri"))
    run = await create_run(task_harness)
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    result = await store.get(rid)
    text = await logs(store, rid)
    assert result["status"] == "succeeded" and result["log_bytes"] > 0
    for expected in (
        "构建 #101", "Release #201", "commit aaaaaaaaaaaa", "开始部署",
        "部署结束", "核对", "buildId=101", "releaseId=201",
    ):
        assert expected in text
    assert secret not in text and "Authorization" not in text
    print(text)


async def test_http_error_summary_and_log_are_safe(task_harness):
    fake, _, store, service, _ = task_harness
    run = await create_run(task_harness)
    original = fake.handle

    def forbidden(request):
        if request.method == "POST" and request.url.path.endswith("/releases"):
            return httpx.Response(403, json={"message": "fake-task-pat-1234 Authorization: secret"})
        return original(request)

    fake.handle = forbidden
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    result = await store.get(rid)
    assert "HTTP 403，无访问权限" in result["summary"]
    text = await logs(store, rid)
    assert "HTTP 403，无访问权限" in text
    assert "fake-task-pat-1234" not in text and "Authorization" not in text
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    assert (await store.get(rid))["summary"].startswith(result["summary"])


async def test_repeated_build_and_environment_polls_log_only_changes(task_harness):
    fake, _, store, service, _ = task_harness
    original = fake.handle
    build_reads = env_reads = 0

    def polling(request):
        nonlocal build_reads, env_reads
        response = original(request)
        if request.method != "GET":
            return response
        path = request.url.path
        if path.endswith("/builds/101"):
            build_reads += 1
            payload = response.json()
            if build_reads < 4:
                payload.update(status="inProgress", result=None)
            return httpx.Response(200, json=payload)
        if path.endswith("/releases/201"):
            payload = response.json()
            if payload["environments"][0]["deploySteps"]:
                env_reads += 1
                if env_reads < 4:
                    payload["environments"][0]["status"] = "inProgress"
            return httpx.Response(200, json=payload)
        return response

    fake.handle = polling
    run = await create_run(task_harness)
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    assert (await store.get(rid))["status"] == "succeeded"
    text = await logs(store, rid)
    assert build_reads == 4 and env_reads == 4
    assert text.count("构建 #101 状态：inProgress") == 1
    assert text.count("环境 演示（#2011）状态：inProgress") == 1
    assert text.count("环境 演示 部署结束：succeeded") == 1


@pytest.mark.parametrize("value", ["", "bad-uri", "vstfs:///Build/Build/0", "vstfs:///Build/Build/12/extra"])
def test_invalid_build_uri_cannot_be_hidden_by_valid_instance(value):
    with pytest.raises(SettingsError, match="Release 具体制品不符"):
        artifact_build_id({
            "instanceReference": {"id": "64778"},
            "definitionReference": {"buildUri": {"id": value}},
        })


def server_deployment_responses(fake, *, lose_patch=False, terminal="succeeded"):
    """采用用户核实的初始环境形状及 Server 的部署尝试结构。"""
    server_responses(fake, ("version", "uri"))
    original_release, original_handle = fake.release, fake.handle

    def release(*args, **kwargs):
        result = original_release(*args, **kwargs)
        for env in result["environments"]:
            env.update(conditions=[], triggerReason="Manual", scheduledDeploymentTime=None)
        return result

    fake.release = release
    for result in fake.releases.values():
        for env in result["environments"]:
            env.update(conditions=[], triggerReason="Manual", scheduledDeploymentTime=None)

    def handle(request):
        if "/release/" in request.url.path:
            expected = "6.0-preview.6" if request.method == "PATCH" else "6.0"
            assert request.url.params["api-version"] == expected
        if request.method == "PATCH":
            assert json.loads(request.content) == {
                "status": "inProgress", "comment": json.loads(request.content)["comment"],
            }
            assert json.loads(request.content)["comment"].startswith("toolbox-next run=")
        response = original_handle(request)
        if request.method == "PATCH":
            parts = request.url.path.split("/")
            env = next(
                e for e in fake.releases[int(parts[-3])]["environments"]
                if e["id"] == int(parts[-1])
            )
            env["status"] = terminal
            env["deploySteps"][-1].update(
                status="succeeded" if terminal == "succeeded" else "failed",
                preDeploymentGates={"status": "none"},
                postDeploymentGates={"status": "succeeded"},
                releaseDeployPhases=[{"status": "succeeded"}],
            )
            if lose_patch:
                raise httpx.ReadError("部署已送达但回执丢失", request=request)
            return httpx.Response(200, json=env)
        return response

    fake.handle = handle


@pytest.mark.parametrize("operation", ["sync_build_release", "deploy_only", "rollback"])
@pytest.mark.parametrize("lose_patch", [False, True])
async def test_server_manual_shape_full_flow_and_readonly_reconcile(
    task_harness, operation, lose_patch
):
    fake, _, store, service, task = task_harness
    server_deployment_responses(fake, lose_patch=lose_patch)
    run = await create_run(task_harness, operation)
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    assert (await store.get(rid))["status"] == ("unknown" if lose_patch else "succeeded")
    writes = list(fake.writes)
    if lose_patch:
        await service.reconcile(rid)
        await asyncio.gather(*list(service.reconciliations.values()))
        assert (await store.get(rid))["status"] == "succeeded"
        assert fake.writes == writes
    assert len([w for w in writes if w[0] == "PATCH"]) == 1
    target = task["prepared"]["targets"][0]
    release = fake.releases[target.get("release_id", 201)]
    assert release["environments"][0]["status"] == "succeeded"
    assert release["environments"][1]["status"] == (
        "succeeded" if operation == "rollback" else "notStarted"
    )
    if operation != "rollback":
        assert "Server conditions=[] 且 triggerReason=Manual" in await logs(store, rid)


@pytest.mark.parametrize("change", [
    {"status": "inProgress"}, {"deploySteps": [{"attempt": 1}]},
    {"deploySteps": None}, {"scheduledDeploymentTime": "2026-10-29T00:00:00Z"},
    {"conditions": [{"conditionType": "manual"}, {"conditionType": "event"}]},
    {"triggerReason": "ReleaseStarted"}, {"triggerReason": None},
    {"conditions": None}, {"conditions": [None]},
])
async def test_server_unsafe_initial_environment_never_patches(task_harness, change):
    fake, _, store, service, _ = task_harness
    server_deployment_responses(fake)
    original = fake.release

    def release(*args, **kwargs):
        result = original(*args, **kwargs)
        # 未选环境也必须核实，不能只检查部署目标。
        result["environments"][1].update(change)
        return result

    fake.release = release
    run = await create_run(task_harness, "deploy_only")
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "unknown"
    assert not any(w[0] == "PATCH" for w in fake.writes)


@pytest.mark.parametrize("reason", ["Manual", "manual", "MANUAL"])
def test_manual_reason_case_and_missing_deploy_steps(reason):
    assert manual_environment({"status": "notStarted", "conditions": [], "triggerReason": reason})


@pytest.mark.parametrize("terminal", ["failed", "cancelled", "canceled", "rejected", "partiallySucceeded"])
@pytest.mark.parametrize("lose_patch", [False, True])
async def test_server_terminal_failure_does_not_wait_for_timeout(task_harness, terminal, lose_patch):
    fake, _, store, service, _ = task_harness
    server_deployment_responses(fake, terminal=terminal, lose_patch=lose_patch)
    run = await create_run(task_harness, "deploy_only")
    rid = run["run_id"]
    await asyncio.wait_for(service._execute_worker(rid, asyncio.Event()), 5)
    writes = list(fake.writes)
    if lose_patch:
        assert (await store.get(rid))["status"] == "unknown"
        await service.reconcile(rid)
        await asyncio.gather(*list(service.reconciliations.values()))
    assert (await store.get(rid))["status"] == "failed"
    assert fake.writes == writes


@pytest.mark.parametrize("state", ["queued", "scheduled", "inProgress", "undefined", "futureState"])
def test_nonterminal_environment_never_succeeds(state):
    assert deployment_result({"status": state, "deploySteps": [{"attempt": 1}]}) is None


@pytest.mark.parametrize("blocker", ["attempt", "phase", "pre_gate", "post_gate", "pre_approval", "post_approval"])
async def test_rollback_stale_success_waits_for_current_attempt_evidence(task_harness, blocker):
    fake, _, store, service, task = task_harness
    server_deployment_responses(fake, lose_patch=True)
    run = await create_run(task_harness, "rollback")
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    target = task["prepared"]["targets"][0]
    env = fake.releases[target["release_id"]]["environments"][0]
    step = env["deploySteps"][-1]
    if blocker == "attempt":
        step["status"] = "inProgress"
    elif blocker == "phase":
        step["releaseDeployPhases"][0]["status"] = "inProgress"
    elif blocker.endswith("gate"):
        step["preDeploymentGates" if blocker == "pre_gate" else "postDeploymentGates"]["status"] = "pending"
    else:
        env["preDeployApprovals" if blocker == "pre_approval" else "postDeployApprovals"] = [
            {"attempt": step["attempt"] - 1, "status": "rejected"},
            {"attempt": step["attempt"], "status": "pending"},
        ]
    writes = list(fake.writes)
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    assert (await store.get(rid))["status"] == "unknown"
    step.update(status="succeeded", releaseDeployPhases=[{"status": "succeeded"}],
                preDeploymentGates={"status": "succeeded"}, postDeploymentGates={"status": "succeeded"})
    for key in ("preDeployApprovals", "postDeployApprovals"):
        for approval in env.get(key, []):
            if approval["attempt"] == step["attempt"]:
                approval["status"] = "approved"
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    assert (await store.get(rid))["status"] == "succeeded"
    assert fake.writes == writes


@pytest.mark.parametrize("state", ["queued", "scheduled", "inProgress", "approval", "gate", "phase"])
async def test_server_poll_waits_without_replaying_patch(task_harness, state):
    fake, _, store, service, _ = task_harness
    server_deployment_responses(fake)
    original = fake.handle
    polls = 0

    def handle(request):
        nonlocal polls
        response = original(request)
        if request.method == "GET" and request.url.path.endswith("/releases/201"):
            payload = response.json()
            env = payload["environments"][0]
            if env["deploySteps"]:
                polls += 1
                if polls < 3:
                    if state == "approval":
                        env["postDeployApprovals"] = [{"attempt": 1, "status": "pending"}]
                    elif state == "gate":
                        env["deploySteps"][-1]["postDeploymentGates"] = {"status": "inProgress"}
                    elif state == "phase":
                        env["deploySteps"][-1]["releaseDeployPhases"] = [{"status": "inProgress"}]
                    else:
                        env["status"] = state
                return httpx.Response(200, json=payload)
        return response

    fake.handle = handle
    run = await create_run(task_harness, "deploy_only")
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "succeeded"
    assert polls == 3
    assert len([w for w in fake.writes if w[0] == "PATCH"]) == 1


@pytest.mark.parametrize("change", [
    {"deploySteps": [{"attempt": 1}]},
    {"scheduledDeploymentTime": "2026-10-29T00:00:00Z"},
])
async def test_unselected_environment_new_remote_activity_is_not_success(task_harness, change):
    fake, _, store, service, _ = task_harness
    server_deployment_responses(fake)
    original = fake.handle

    def handle(request):
        response = original(request)
        if request.method == "PATCH":
            fake.releases[201]["environments"][1].update(change)
        return response

    fake.handle = handle
    run = await create_run(task_harness, "deploy_only")
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    assert (await store.get(rid))["status"] == "unknown"
    writes = list(fake.writes)
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    assert (await store.get(rid))["status"] == "failed"
    assert fake.writes == writes


def test_server_attempt_history_is_not_an_array_position_or_phase_id():
    env = {"status": "succeeded", "deploySteps": [
        {"attempt": "2", "status": "succeeded", "releaseDeployPhases": [{"id": 990, "status": "succeeded"}]},
        {"attempt": 1, "status": "failed", "releaseDeployPhases": [{"status": "failed"}]},
    ]}
    assert attempt(env) == 2
    assert deployment_result(env) is True
    for steps in ([{"id": 990}], [None], None):
        with pytest.raises(SettingsError):
            attempt({"deploySteps": steps})


async def test_negotiated_cloud_version_is_preserved_for_patch_and_polls(task_harness):
    fake, _, store, service, _ = task_harness
    original = fake.handle
    versions = []

    def handle(request):
        if "/release/" in request.url.path:
            version = request.url.params["api-version"]
            if version == "6.0":
                return httpx.Response(400, json={"typeKey": "VssVersionNotSupportedException"})
            versions.append((request.method, version))
        return original(request)

    fake.handle = handle
    run = await create_run(task_harness, "deploy_only")
    await service._execute_worker(run["run_id"], asyncio.Event())
    assert (await store.get(run["run_id"]))["status"] == "succeeded"
    assert ("PATCH", "7.0") in versions
    assert all(version == "7.0" for _, version in versions)


async def test_rollback_old_success_without_new_attempt_cannot_confirm_delivery(task_harness):
    fake, _, store, service, task = task_harness
    server_deployment_responses(fake, lose_patch=True)
    run = await create_run(task_harness, "rollback")
    rid = run["run_id"]
    await service._execute_worker(rid, asyncio.Event())
    target = task["prepared"]["targets"][0]
    env = fake.releases[target["release_id"]]["environments"][0]
    env["deploySteps"].pop()
    writes = list(fake.writes)
    await service.reconcile(rid)
    await asyncio.gather(*list(service.reconciliations.values()))
    result = await store.get(rid)
    assert result["status"] == "unknown"
    assert result["effects"][-1]["state"] == "intent"
    assert fake.writes == writes
