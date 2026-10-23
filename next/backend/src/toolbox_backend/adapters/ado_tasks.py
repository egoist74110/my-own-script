"""Frozen ADO plans and journaled, single-delivery writes over the S2 transport.

No method in reconciliation reaches the write helper. Unprovable delivery remains unknown.
"""

import asyncio
import re
import time
from urllib.parse import urlsplit

from toolbox_backend.adapters.ado_read import AdoFailure, build_url, within
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.task_execution import ExecutionOutcome, PreparedExecution
from toolbox_backend.services.work_items import integer, outbound


def unsupported(message):
    raise SettingsError("unsupported_task", message)


def number(value):
    result = integer(value)
    if result is None:
        unsupported("远端身份字段缺失或无效")
    return result


def values(payload):
    result = payload.get("value")
    if (
        not isinstance(result, list)
        or len(result) > 500
        or any(not isinstance(x, dict) for x in result)
    ):
        unsupported("远端列表格式无效或超限")
    return result


def commit(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
        unsupported("远端缺少精确提交身份")
    return value.lower()


def attempt(env):
    steps = env.get("deploySteps", [])
    if not isinstance(steps, list):
        unsupported("无法核实部署尝试")
    return max([0, *(number(s.get("attempt")) for s in steps)])


class AdoTaskExecutor:
    def __init__(self, work_items, git, *, build_interval=4, release_interval=5):
        self.work_items, self.http, self.git = work_items, work_items.http, git
        self.build_interval, self.release_interval = build_interval, release_interval

    async def source(self, snapshot):
        source = snapshot["source"]
        ctx = await self.work_items.snapshot(source["project_id"])
        project, library, _ = ctx
        if (
            project.id,
            project.library_id,
            library.id,
            library.base_url,
            project.collection,
            project.project,
        ) != (
            source["project_id"],
            source["library_id"],
            source["library_id"],
            source["base_url"],
            source["collection"],
            source["project"],
        ):
            raise SettingsError("plan_changed", "凭据来源已变化；只允许原来源核实")
        return ctx

    async def request(
        self, snapshot, suffix, *, method="GET", version="7.0", params=None, body=None
    ):
        project, library, pat = await self.source(snapshot)
        return await outbound(
            self.http.request_json,
            library,
            pat,
            method,
            [project.collection, project.project, "_apis", *map(str, suffix)],
            {"api-version": version, **(params or {})},
            body,
        )

    async def head(self, snapshot):
        branch = "refs/heads/" + snapshot["git_flow"]["build_branch"]
        rows = values(
            await self.request(
                snapshot,
                ["git", "repositories", snapshot["repo_id"], "refs"],
                params={"filter": branch[5:]},
            )
        )
        rows = [x for x in rows if x.get("name") == branch]
        if len(rows) != 1:
            unsupported("构建分支未精确匹配")
        return commit(rows[0].get("objectId"))

    def identity(self, snapshot, target, build, expected=None):
        # Project is an explicit field in the trusted Build detail, never inferred from an id.
        source = snapshot["source"]
        if any(not isinstance(build.get(k), dict) for k in ("project", "repository", "definition")):
            return False
        if snapshot.get("agent_queue_id") and not isinstance(build.get("queue"), dict):
            return False
        project = build["project"]
        project_matches = source["project"] in (project.get("id"), project.get("name"))
        result = (
            project_matches
            and str(build.get("repository", {}).get("id", "")).lower()
            == str(snapshot["repo_id"]).lower()
            and integer(build.get("definition", {}).get("id")) == target["definition_id"]
            and build.get("sourceBranch") == "refs/heads/" + snapshot["git_flow"]["build_branch"]
            and (
                not snapshot.get("agent_queue_id")
                or integer(build.get("queue", {}).get("id")) == integer(snapshot["agent_queue_id"])
            )
        )
        try:
            actual = commit(build.get("sourceVersion"))
        except SettingsError:
            return False
        return bool(result and (expected is None or expected == actual))

    async def build(self, snapshot, target, ident, expected=None):
        result = await self.request(snapshot, ["build", "builds", number(ident)])
        if integer(result.get("id")) != integer(ident) or not self.identity(
            snapshot, target, result, expected
        ):
            unsupported("构建的项目、仓库、定义、分支、提交或队列身份不符")
        return result

    async def definition(self, snapshot, ident):
        version = "6.0"
        try:
            definition = await self.request(
                snapshot, ["release", "definitions", ident], version=version
            )
        except AdoFailure as exc:
            if not getattr(exc, "version_unsupported", False):
                raise
            version = "7.0"
            definition = await self.request(
                snapshot, ["release", "definitions", ident], version=version
            )
        if integer(definition.get("id")) != ident:
            unsupported("Release 定义身份不符")
        return definition, version

    def artifact(self, snapshot, target, definition):
        artifacts = definition.get("artifacts", [])
        if len(artifacts) != 1 or artifacts[0].get("type") != "Build":
            unsupported("仅支持单个 Build artifact")
        a = artifacts[0]
        refs = a.get("definitionReference", {})
        project = refs.get("project", {})
        if (
            not isinstance(a.get("alias"), str)
            or not a["alias"]
            or len(a["alias"]) > 200
            or integer(refs.get("definition", {}).get("id")) != target["definition_id"]
            or snapshot["source"]["project"] not in {project.get("id"), project.get("name")}
        ):
            unsupported("Release artifact 项目或构建定义绑定不符")
        if any(
            not isinstance(refs[key].get(field), (str, int)) or len(str(refs[key][field])) > 200
            for key in ("project", "definition")
            for field in ("id", "name")
            if refs[key].get(field) is not None
        ):
            unsupported("Release artifact 身份字段无效或超限")
        return {
            "alias": a["alias"],
            "type": "Build",
            "definitionReference": {
                key: {
                    field: str(refs[key][field])
                    for field in ("id", "name")
                    if refs[key].get(field) is not None
                }
                for key in ("project", "definition")
            },
        }

    def stages(self, target, definition):
        envs = definition.get("environments", [])
        if not isinstance(envs, list) or not envs or len(envs) > 500:
            unsupported("Release 环境集合无效")
        ids = [number(e.get("id")) for e in envs]
        names = [e.get("name") for e in envs]
        if (
            len(ids) != len(set(ids))
            or any(not isinstance(n, str) or not n for n in names)
            or len(names) != len(set(names))
        ):
            unsupported("Release 环境身份或名称不唯一，无法全部转为手动")
        requested = target.get("release_stage_ids", [])
        if requested:
            chosen = [number(x) for x in requested]
        else:
            chosen = []
            for name in target.get("release_stage_names", []):
                if names.count(name) != 1:
                    unsupported("所选环境名称未唯一匹配")
                chosen.append(ids[names.index(name)])
        if not chosen or len(set(chosen)) != len(chosen) or not set(chosen).issubset(ids):
            unsupported("所选环境必须全部存在且唯一")
        return chosen, names

    def release_envs(self, target, release):
        if (
            integer(release.get("releaseDefinition", {}).get("id"))
            != target["release_definition_id"]
        ):
            unsupported("Release 归属不符")
        envs = release.get("environments", [])
        selected = []
        for ident in target["stage_ids"]:
            matching = [e for e in envs if integer(e.get("definitionEnvironmentId")) == ident]
            if len(matching) != 1:
                unsupported("Release 未完整匹配所选环境")
            number(matching[0].get("id"))
            selected.append(matching[0])
        return selected

    async def prepare(self, snapshot, operation, rollback_offset):
        try:
            return await self._prepare(snapshot, operation, rollback_offset)
        except AttributeError, KeyError, TypeError, ValueError, IndexError:
            # Remote nested containers are untrusted. Never echo them or expose HTTP 500.
            raise AdoFailure("bad_response", "远端任务定义或身份响应格式无效") from None

    async def _prepare(self, snapshot, operation, rollback_offset):
        flow = snapshot["git_flow"]
        if not snapshot.get("repo_id"):
            unsupported("任务缺少仓库身份")
        await self.source(snapshot)
        if (
            operation == "sync_build_release"
            and not snapshot["local_repo_path"]
            and any(flow[k] for k in ("update_branches", "merges", "push_branches"))
        ):
            unsupported("无本地路径的 Git 规则及远程 PR 写暂不支持")
        prepared = PreparedExecution(frozen={"targets": []}, budget_seconds=300)
        if operation == "sync_build_release" and snapshot["local_repo_path"]:
            await self.git.preflight(snapshot["local_repo_path"])
            prepared.steps.append({"kind": "git", "target_index": None})
            prepared.budget_seconds += 900
        elif operation == "sync_build_release":
            prepared.frozen["commit"] = await self.head(snapshot)
        for index, raw in enumerate(snapshot["targets"]):
            if not raw["enabled"]:
                continue
            target = {
                "target_index": index,
                "name": raw["name"],
                "definition_id": number(raw["build_id"]),
                "api_kind": "build" if snapshot.get("agent_queue_id") else raw["build_kind"],
                "release_definition_id": number(raw["release_id"]),
                **{k: raw[k] for k in ("release_stage_ids", "release_stage_names")},
            }
            if target["api_kind"] not in {"pipeline", "build"}:
                unsupported("构建种类未配置")
            # Validate the build definition before the first write, including its repository.
            definition = await self.request(
                snapshot, ["build", "definitions", target["definition_id"]]
            )
            if (
                integer(definition.get("id")) != target["definition_id"]
                or str(definition.get("repository", {}).get("id", "")).lower()
                != str(snapshot["repo_id"]).lower()
            ):
                unsupported("构建定义仓库绑定不符")
            release, version = await self.definition(snapshot, target["release_definition_id"])
            target["api_version"] = version
            target["artifact"] = self.artifact(snapshot, target, release)
            target["stage_ids"], target["manual_environments"] = self.stages(raw, release)
            if operation == "deploy_only":
                rows = values(
                    await self.request(
                        snapshot,
                        ["build", "builds"],
                        params={
                            "definitions": target["definition_id"],
                            "branchName": "refs/heads/" + flow["build_branch"],
                            "$top": 1,
                            "queryOrder": "finishTimeDescending",
                            "statusFilter": "completed",
                            "resultFilter": "succeeded",
                        },
                    )
                )
                if not rows:
                    unsupported("无可发布的成功构建")
                build = await self.build(snapshot, target, rows[0].get("id"))
                if build.get("status") != "completed" or build.get("result") not in {
                    "succeeded",
                    "success",
                }:
                    unsupported("所选制品不是完全成功的构建")
                target.update(build_id=number(build["id"]), commit=commit(build["sourceVersion"]))
            elif operation == "rollback":
                if rollback_offset is None:
                    unsupported("回滚需要 1..5 的历史偏移")
                rows = values(
                    await self.request(
                        snapshot,
                        ["release", "releases"],
                        version=version,
                        params={
                            "definitionId": target["release_definition_id"],
                            "$top": 6,
                            "queryOrder": "descending",
                        },
                    )
                )
                if len(rows) <= rollback_offset:
                    unsupported("历史 Release 数量不足")
                historic = await self.request(
                    snapshot,
                    ["release", "releases", number(rows[rollback_offset].get("id"))],
                    version=version,
                )
                historic_envs = self.release_envs(target, historic)
                target["environment_ids"] = [number(e["id"]) for e in historic_envs]
                target["deployment_attempts"] = {
                    str(number(e["id"])): attempt(e) for e in historic_envs
                }
                arts = historic.get("artifacts", [])
                if (
                    len(arts) != 1
                    or self.artifact(snapshot, target, historic) != target["artifact"]
                ):
                    unsupported("历史 Release 制品绑定已变化")
                build = await self.build(
                    snapshot, target, arts[0].get("instanceReference", {}).get("id")
                )
                target.update(
                    release_id=number(historic["id"]),
                    build_id=number(build["id"]),
                    commit=commit(build["sourceVersion"]),
                    created_at=historic.get("createdOn"),
                    history_ids=[number(x.get("id")) for x in rows],
                )
            else:
                prepared.steps.append({"kind": "build", "target_index": index})
                prepared.budget_seconds += 1800
            prepared.steps.append(
                {
                    "kind": "rollback" if operation == "rollback" else "release",
                    "target_index": index,
                }
            )
            prepared.budget_seconds += 3600
            prepared.frozen["targets"].append(target)
            prepared.targets.append(
                {
                    k: target.get(k)
                    for k in (
                        "target_index",
                        "name",
                        "definition_id",
                        "release_definition_id",
                        "stage_ids",
                        "build_id",
                        "commit",
                        "release_id",
                        "created_at",
                    )
                }
            )
        if not prepared.frozen["targets"]:
            unsupported("没有启用的发布目标")
        return prepared

    async def write(self, context, kind, intent, suffix, body, *, version="7.0", method="POST"):
        effect = await context.intent(kind, intent)
        # No catch/retry: the durable intent survives transport or receipt commit failures.
        response = await self.request(
            context.snapshot, suffix, method=method, version=version, body=body
        )
        ident = number(response.get("id"))
        await context.receipt(
            effect, "confirmed", remote_id=ident, owned=kind in {"build_create", "release_create"}
        )
        return response

    async def pause(self, context, seconds):
        if context.cancelled.is_set():
            # Cancellation confirmation still polls at a bounded rate.
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(context.cancelled.wait(), seconds)
        except TimeoutError:
            pass

    async def pipeline_build(self, snapshot, target, pipeline, expected):
        # Only a same-source explicit Build API link counts; never treat run.id as build.id.
        ctx = await self.source(snapshot)
        href = pipeline.get("_links", {}).get("build", {}).get("href", "")
        if not isinstance(href, str) or not within(ctx[1], href):
            unsupported("Pipeline 未提供可核实的 Build 关联")
        match = re.fullmatch(r"(.*/_apis/build/builds/)([1-9][0-9]*)", urlsplit(href).path)
        if not match:
            unsupported("Pipeline 的 Build 关联无效")
        ident = number(match[2])
        trusted = build_url(
            ctx[1], [ctx[0].collection, ctx[0].project, "_apis", "build", "builds", str(ident)]
        )
        if urlsplit(trusted).path != urlsplit(href).path or urlsplit(href).query:
            unsupported("Pipeline 的 Build 关联不属于冻结项目")
        return await self.build(snapshot, target, ident, expected)

    async def acquire_build(self, context, target, expected):
        s = context.snapshot
        candidates = values(
            await self.request(
                s,
                ["build", "builds"],
                params={
                    "definitions": target["definition_id"],
                    "branchName": "refs/heads/" + s["git_flow"]["build_branch"],
                    "$top": 20,
                    "queryOrder": "queueTimeDescending",
                },
            )
        )
        for candidate in candidates[:20]:
            try:
                b = await self.build(s, target, candidate.get("id"), expected)
            except SettingsError, AdoFailure:
                continue
            if b.get("status") in {"notStarted", "inProgress", "postponed"}:
                await context.checkpoint(
                    "build",
                    {
                        "target_index": target["target_index"],
                        "build_id": number(b["id"]),
                        "commit": expected,
                        "owned": False,
                    },
                )
                return b, False
        await context.checkpoint(
            "build", {"target_index": target["target_index"], "commit": expected}
        )
        intent = {
            "api_kind": target["api_kind"],
            "definition_id": target["definition_id"],
            "commit": expected,
            "repo_id": s["repo_id"],
            "branch": s["git_flow"]["build_branch"],
        }
        ref = "refs/heads/" + s["git_flow"]["build_branch"]
        if target["api_kind"] == "pipeline":
            p = await self.write(
                context,
                "build_create",
                intent,
                ["pipelines", target["definition_id"], "runs"],
                {"resources": {"repositories": {"self": {"refName": ref, "version": expected}}}},
            )
            await context.checkpoint(
                "build",
                {
                    "target_index": target["target_index"],
                    "pipeline_run_id": number(p["id"]),
                    "commit": expected,
                    "owned": True,
                },
            )
            b = await self.pipeline_build(s, target, p, expected)
        else:
            body = {
                "definition": {"id": target["definition_id"]},
                "sourceBranch": ref,
                "sourceVersion": expected,
            }
            if s.get("agent_queue_id"):
                body["queue"] = {"id": number(s["agent_queue_id"])}
            response = await self.write(context, "build_create", intent, ["build", "builds"], body)
            b = await self.build(s, target, response["id"], expected)
        await context.checkpoint(
            "build",
            {
                "target_index": target["target_index"],
                "build_id": number(b["id"]),
                "commit": expected,
                "owned": True,
            },
        )
        return b, True

    async def wait_build(self, context, target, build, owned, expected):
        deadline = time.monotonic() + 1800
        cancelling = False
        while True:
            if build.get("status") == "completed":
                if context.cancelled.is_set() and build.get("result") in {"canceled", "cancelled"}:
                    return "cancelled"
                return build.get("result") in {"succeeded", "success"}
            if context.cancelled.is_set():
                if not owned:
                    return None
                if not cancelling:
                    current = await context.current()
                    if current["status"] != "cancelling":
                        await context.request_stop()
                    await self.write(
                        context,
                        "build_cancel",
                        {"api_kind": "build", "build_id": number(build["id"])},
                        ["build", "builds", build["id"]],
                        {"status": "cancelling"},
                        method="PATCH",
                    )
                    cancelling = True
                    deadline = min(deadline, time.monotonic() + 60)
            if time.monotonic() >= deadline:
                await context.request_stop("timeout")
                return None
            await self.pause(
                context, self.build_interval if not cancelling else min(1, self.build_interval)
            )
            build = await self.build(context.snapshot, target, build["id"], expected)

    async def deploy(self, context, target, build_id, release_id=None):
        s, version = context.snapshot, target["api_version"]
        if release_id is None:
            # Revalidate immutable definition binding and manual-environment set before creation.
            definition = await self.request(
                s, ["release", "definitions", target["release_definition_id"]], version=version
            )
            if self.artifact(s, target, definition) != target["artifact"] or self.stages(
                target, definition
            ) != (target["stage_ids"], target["manual_environments"]):
                unsupported("Release 定义在确认后变化")
            await context.checkpoint(
                "release", {"target_index": target["target_index"], "build_id": build_id}
            )
            # Effect UUID is allocated by the journal; description uses it after intent commit.
            intent = {
                "release_definition_id": target["release_definition_id"],
                "build_id": build_id,
                "api_version": version,
                "manual_environments": target["manual_environments"],
            }
            effect = await context.intent("release_create", intent)
            description = f"toolbox-next run={context.run_id} effect={effect}"
            art = {
                **target["artifact"],
                "instanceReference": {"id": str(build_id), "name": str(build_id)},
            }
            r = await self.request(
                s,
                ["release", "releases"],
                method="POST",
                version=version,
                body={
                    "definitionId": target["release_definition_id"],
                    "description": description,
                    "artifacts": [art],
                    "manualEnvironments": target["manual_environments"],
                    "isDraft": False,
                },
            )
            release_id = number(r.get("id"))
            await context.receipt(effect, "confirmed", remote_id=release_id, owned=True)
        r = await self.request(s, ["release", "releases", release_id], version=version)
        selected = self.release_envs(target, r)
        if self.artifact(s, target, r) != target["artifact"]:
            unsupported("Release 制品绑定已变化")
        if context.operation == "rollback" and (
            [number(e["id"]) for e in selected] != target["environment_ids"]
            or {str(number(e["id"])): attempt(e) for e in selected} != target["deployment_attempts"]
        ):
            raise SettingsError("plan_changed", "历史环境身份或部署尝试已变化")
        arts = r.get("artifacts", [])
        if len(arts) != 1 or integer(arts[0].get("instanceReference", {}).get("id")) != build_id:
            unsupported("Release 具体制品不符")
        if context.operation != "rollback":
            for env in r.get("environments", []):
                conditions = env.get("conditions")
                if (
                    not isinstance(conditions, list)
                    or not conditions
                    or any(c.get("conditionType") != "manual" for c in conditions)
                    or env.get("status") != "notStarted"
                ):
                    unsupported("服务器未保证所有环境为手动且未自动部署")
        baselines = {str(number(e["id"])): attempt(e) for e in selected}
        kind = "rollback" if context.operation == "rollback" else "release"
        await context.checkpoint(
            kind,
            {
                "target_index": target["target_index"],
                "release_id": release_id,
                "build_id": build_id,
                "stage_ids": target["stage_ids"],
                "deployment_attempts": baselines,
            },
        )
        for env in selected:
            if context.cancelled.is_set():
                return None
            ident = number(env["id"])
            await self.write(
                context,
                "env_deploy",
                {
                    "release_id": release_id,
                    "environment_id": ident,
                    "baseline_attempt": baselines[str(ident)],
                    "api_version": version,
                },
                ["release", "releases", release_id, "environments", ident],
                {"status": "inProgress", "comment": "toolbox-next run=" + context.run_id},
                version=version,
                method="PATCH",
            )
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            r = await self.request(s, ["release", "releases", release_id], version=version)
            selected = self.release_envs(target, r)
            if context.operation != "rollback" and any(
                integer(e.get("definitionEnvironmentId")) not in target["stage_ids"]
                and e.get("status") != "notStarted"
                for e in r.get("environments", [])
            ):
                return None
            fresh = all(attempt(e) > baselines[str(number(e["id"]))] for e in selected)
            if fresh and all(e.get("status") == "succeeded" for e in selected):
                return True
            if fresh and all(
                e.get("status") in {"succeeded", "rejected", "canceled", "partiallySucceeded"}
                for e in selected
            ):
                return False
            if context.cancelled.is_set():
                return None
            await self.pause(context, self.release_interval)
        await context.request_stop("timeout")
        return None

    async def execute(self, context):
        s = context.snapshot
        expected = s["prepared"].get("commit")
        if context.operation == "sync_build_release":
            if s["local_repo_path"]:
                expected = await self.git.execute(s, context)
                await context.complete_step()
                context.step_no += 1
            elif await self.head(s) != expected:
                return ExecutionOutcome("failed", "plan_changed")
        for target in s["prepared"]["targets"]:
            if context.cancelled.is_set():
                current = await context.current()
                remote = bool(current["effects"]) or any(
                    any(
                        step["checkpoint"].get(k) is not None
                        for k in ("build_id", "pipeline_run_id", "release_id")
                    )
                    for step in current["steps"]
                )
                if not remote:
                    await context.request_stop()
                return ExecutionOutcome("unknown" if remote else "cancelled", "interrupted")
            if context.operation == "sync_build_release":
                if await self.head(s) != expected:
                    return ExecutionOutcome("failed", "plan_changed")
                b, owned = await self.acquire_build(context, target, expected)
                ready = await self.wait_build(context, target, b, owned, expected)
                if ready == "cancelled":
                    await context.complete_step("failed")
                    return ExecutionOutcome(
                        "cancelled", "cancelled", "本 run 构建已确认停止，未继续发布"
                    )
                if ready is not True:
                    await context.complete_step("unknown" if ready is None else "failed")
                    return ExecutionOutcome(
                        "unknown" if ready is None else "failed",
                        "remote_running" if ready is None else "build_failed",
                    )
                await context.complete_step()
                context.step_no += 1
                build_id = number(b["id"])
            else:
                build_id = target["build_id"]
                b = await self.build(s, target, build_id, target["commit"])
                if context.operation == "deploy_only" and (
                    b.get("status") != "completed"
                    or b.get("result") not in {"succeeded", "success"}
                ):
                    return ExecutionOutcome("failed", "plan_changed")
            if context.operation == "rollback":
                rows = values(
                    await self.request(
                        s,
                        ["release", "releases"],
                        version=target["api_version"],
                        params={
                            "definitionId": target["release_definition_id"],
                            "$top": 6,
                            "queryOrder": "descending",
                        },
                    )
                )
                if [number(x.get("id")) for x in rows] != target["history_ids"]:
                    return ExecutionOutcome("failed", "plan_changed")
            deployed = await self.deploy(context, target, build_id, target.get("release_id"))
            if deployed is not True:
                await context.complete_step("unknown" if deployed is None else "failed")
                return ExecutionOutcome(
                    "unknown" if deployed is None else "failed",
                    "remote_running" if deployed is None else "release_failed",
                )
            await context.complete_step()
            context.step_no += 1
        return ExecutionOutcome("succeeded")

    async def reconcile(self, context):
        run = await context.current()
        s = context.snapshot
        targets = {t["target_index"]: t for t in s["prepared"]["targets"]}
        uncertain, failed, observed = False, False, False
        cancelled_build = False
        other_failure = False
        completed_steps = set()
        effects_by_step = {}
        for effect in run["effects"]:
            effects_by_step.setdefault(effect["step_no"], []).append(effect)
        for step in run["steps"]:
            context.step_no = step["step_no"]
            cp = step["checkpoint"]
            target = targets.get(step["target_index"])
            effects = effects_by_step.get(step["step_no"], [])
            if step["kind"] == "git":
                for effect in effects:
                    if effect["state"] in {"intent", "unknown"}:
                        info = await self.git.inspect(s["local_repo_path"])
                        async with self.git.locked(info, asyncio.Event()) as fd:
                            await self.git.check(info["root"], fd)
                            intent = effect["intent"]
                            ref = "refs/heads/" + intent["branch"]
                            remote = await self.git.command(
                                info["root"], ["ls-remote", "--refs", "origin", ref], lock_fd=fd
                            )
                        if remote.split() == [intent["commit"], ref]:
                            await context.receipt(effect["effect_id"], "confirmed")
                        else:
                            uncertain = True
                # Git recovery never repeats local merges or pushes.
                continue
            if step["kind"] == "build":
                ident, expected = cp.get("build_id"), cp.get("commit")
                for effect in effects:
                    intent = effect["intent"]
                    if effect["kind"] == "build_create":
                        expected = expected or intent["commit"]
                        if effect["remote_id"]:
                            if intent["api_kind"] == "pipeline":
                                pipeline = await self.request(
                                    s,
                                    [
                                        "pipelines",
                                        target["definition_id"],
                                        "runs",
                                        effect["remote_id"],
                                    ],
                                )
                                b = await self.pipeline_build(s, target, pipeline, expected)
                                ident = b["id"]
                            else:
                                ident = number(effect["remote_id"])
                        else:
                            # Builds lack a documented unique correlation marker here.
                            # Read bounded candidates, but identity alone proves no ownership.
                            await self.request(
                                s,
                                ["build", "builds"],
                                params={
                                    "definitions": target["definition_id"],
                                    "$top": 20,
                                    "queryOrder": "queueTimeDescending",
                                },
                            )
                            uncertain = True
                if ident:
                    observed = True
                    b = await self.build(s, target, ident, expected)
                    if b.get("status") != "completed":
                        uncertain = True
                    else:
                        build_failed = b.get("result") not in {"succeeded", "success"}
                        cancelled_build |= b.get("result") in {"canceled", "cancelled"}
                        other_failure |= build_failed and b.get("result") not in {
                            "canceled",
                            "cancelled",
                        }
                        failed |= build_failed
                        completed_steps.add(step["step_no"])
                        for effect in effects:
                            if effect["kind"] == "build_cancel" and effect["state"] in {
                                "intent",
                                "unknown",
                            }:
                                await context.receipt(
                                    effect["effect_id"], "confirmed", remote_id=ident
                                )
                continue
            release_id = cp.get("release_id")
            for effect in effects:
                if effect["kind"] == "release_create":
                    release_id = release_id or effect["remote_id"]
                    if not release_id:
                        rows = values(
                            await self.request(
                                s,
                                ["release", "releases"],
                                version=target["api_version"],
                                params={
                                    "definitionId": target["release_definition_id"],
                                    "$top": 20,
                                    "queryOrder": "descending",
                                },
                            )
                        )
                        marker = f"toolbox-next run={context.run_id} effect={effect['effect_id']}"
                        matches = [r for r in rows if r.get("description") == marker]
                        if len(matches) == 1:
                            release_id = number(matches[0].get("id"))
                    if release_id and effect["state"] in {"intent", "unknown"}:
                        r = await self.request(
                            s, ["release", "releases", release_id], version=target["api_version"]
                        )
                        self.release_envs(target, r)
                        if self.artifact(s, target, r) != target["artifact"]:
                            unsupported("核实的 Release artifact 绑定不符")
                        arts = r.get("artifacts", [])
                        if (
                            len(arts) != 1
                            or integer(arts[0].get("instanceReference", {}).get("id"))
                            != effect["intent"]["build_id"]
                        ):
                            unsupported("核实的 Release 制品不符")
                        await context.receipt(
                            effect["effect_id"], "confirmed", remote_id=release_id, owned=True
                        )
                    if not release_id:
                        uncertain = True
            if release_id:
                observed = True
                r = await self.request(
                    s, ["release", "releases", release_id], version=target["api_version"]
                )
                envs = self.release_envs(target, r)
                deployments = [e for e in effects if e["kind"] == "env_deploy"]
                all_done = len(deployments) == len(envs)
                for effect in deployments:
                    intent = effect["intent"]
                    matches = [e for e in envs if integer(e.get("id")) == intent["environment_id"]]
                    if len(matches) != 1:
                        uncertain = True
                        all_done = False
                        continue
                    env = matches[0]
                    if attempt(env) <= intent["baseline_attempt"]:
                        uncertain = True
                        all_done = False
                        continue
                    if effect["state"] in {"intent", "unknown"}:
                        await context.receipt(effect["effect_id"], "confirmed", remote_id=env["id"])
                    if env.get("status") not in {
                        "succeeded",
                        "rejected",
                        "canceled",
                        "partiallySucceeded",
                    }:
                        uncertain = True
                        all_done = False
                    else:
                        failed |= env.get("status") != "succeeded"
                        other_failure |= env.get("status") != "succeeded"
                # Unexpected auto-deployment is also an observed remote operation.
                selected_ids = {e["id"] for e in envs}
                for env in r.get("environments", []):
                    if (
                        context.operation != "rollback"
                        and env.get("id") not in selected_ids
                        and env.get("status") != "notStarted"
                    ):
                        failed = True
                        other_failure = True
                    if env.get("id") not in selected_ids and env.get("status") not in {
                        "notStarted",
                        "succeeded",
                        "rejected",
                        "canceled",
                        "partiallySucceeded",
                    }:
                        uncertain = True
                if all_done:
                    completed_steps.add(step["step_no"])
            elif effects:
                uncertain = True
        if uncertain:
            return ExecutionOutcome("unknown", "remote_unknown", "远端结果尚未核实，预约保留")
        if failed:
            if cancelled_build and not other_failure and run["cancel_requested_at"]:
                return ExecutionOutcome("cancelled", "cancelled")
            return ExecutionOutcome("failed", "remote_failed")
        if all(
            step["status"] == "succeeded" or step["step_no"] in completed_steps
            for step in run["steps"]
        ):
            for step in run["steps"]:
                if step["status"] != "succeeded":
                    context.step_no = step["step_no"]
                    await context.complete_step()
            return ExecutionOutcome("succeeded")
        if observed or run["effects"]:
            return ExecutionOutcome(
                "failed", "interrupted", "已观察操作已结束；剩余步骤未执行，请重新确认计划"
            )
        return ExecutionOutcome("failed", "interrupted", "中断前未观察远端操作；未恢复写入")
