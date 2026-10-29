"""Single config writer, editor validation and active-resource coordination."""

import asyncio
import json
import re
import uuid

from pydantic import ValidationError

from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.task_schemas import FlowInput, MergeInput, TargetInput, TaskFields
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import (
    DynamicTask,
    GitFlow,
    ReleaseBranch,
    ReleaseTarget,
    group_tasks,
    repo_path,
    segment,
)


def invalid(message="任务配置无效"):
    return SettingsError("validation_error", message, 422)


def normalize_flow(flow):
    """仅供写入路径使用；局部更新中未提供的字段保持缺省。"""
    if "build_branch" in flow:
        flow["build_branch"] = flow["build_branch"].strip()
    for key in ("update_branches", "push_branches"):
        if key in flow:
            flow[key] = [value.strip() for value in flow[key] if value.strip()]
    for rule in flow.get("merges", []):
        for key in ("source", "target"):
            rule[key] = rule[key].strip()
    return flow


def branch(value):
    if (
        not value
        or len(value) > 255
        or value.startswith(("-", "/", "."))
        or value.endswith(("/", ".", ".lock"))
        or value == "@"
        or any(x in value for x in ("..", "@{", "//", "\\"))
        or any(ord(x) < 33 or ord(x) == 127 or x in "~^:?*[" for x in value)
        or any(x.startswith(".") or x.endswith(".lock") for x in value.split("/"))
    ):
        raise invalid("分支名无效")
    return value


def numeric(value):
    if value is not None and (
        not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > 2147483647
    ):
        raise invalid("ADO 数字标识无效")


def validate_fields(fields):
    try:
        for key in ("project_id", "repo_id"):
            if fields.get(key):
                segment(fields[key])
        numeric(fields.get("agent_queue_id"))
        if fields.get("local_repo_path"):
            repo_path(fields["local_repo_path"])
        if flow := fields.get("git_flow"):
            if flow.get("build_branch"):
                branch(flow["build_branch"])
            for key in ("update_branches", "push_branches"):
                for value in flow.get(key, []):
                    branch(value)
            for rule in flow.get("merges", []):
                branch(rule["source"])
                branch(rule["target"])
        for target in fields.get("targets") or []:
            numeric(target.get("build_id"))
            numeric(target.get("release_id"))
            for value in target.get("release_stage_ids", []):
                numeric(value)
    except ValueError, TypeError:
        raise invalid() from None


def find_task(config, tid):
    task = next((t for t in config.tasks.items if t.id == tid), None)
    if task is None:
        raise SettingsError("not_found", "任务不存在", 404)
    return task


def execution_fields(task):
    fields = {k: v for k, v in task.model_dump().items() if k in TaskFields.model_fields}
    fields["git_flow"] = {
        k: v for k, v in fields["git_flow"].items() if k in FlowInput.model_fields
    }
    fields["git_flow"]["merges"] = [
        {k: v for k, v in rule.items() if k in MergeInput.model_fields}
        for rule in fields["git_flow"]["merges"]
    ]
    fields["targets"] = [
        {k: v for k, v in target.items() if k in TargetInput.model_fields}
        for target in fields["targets"]
    ]
    return fields


class TasksService:
    def __init__(self, settings_service, runs, git):
        self.settings = settings_service
        self.store = settings_service.store
        self.runs = runs
        self.git = git

    def guard(self, old, candidate):
        """Runs under ConfigStore's serialization lock, including credential writes."""
        if (
            old.tasks == candidate.tasks
            and old.ado.projects == candidate.ado.projects
            and old.ado.libraries == candidate.ado.libraries
        ):
            return
        for run in self.runs.active_snapshots():
            tid = run["task_id"]
            before = next((t for t in old.tasks.items if t.id == tid), None)
            after = next((t for t in candidate.tasks.items if t.id == tid), None)
            if before != after:
                raise SettingsError("task_active", "任务存在活动运行")
            source = run["task_snapshot"].get("source", {})
            pid, lid = source.get("project_id"), source.get("library_id")
            for items, updated, ident in (
                (old.ado.projects, candidate.ado.projects, pid),
                (old.ado.libraries, candidate.ado.libraries, lid),
            ):
                if ident and (
                    next((x for x in items if x.id == ident), None)
                    != next((x for x in updated if x.id == ident), None)
                ):
                    raise SettingsError("resource_active", "项目或库存在活动运行")

    def guard_resource(self, kind, ident):
        for run in self.runs.active_snapshots():
            source = run["task_snapshot"].get("source", {})
            if source.get(kind + "_id") == ident:
                raise SettingsError("resource_active", "项目或库存在活动运行")

    def _run_summaries(self):
        try:
            active, latest = self.runs.task_summaries()
            return active, latest, False
        except SettingsError:
            return {}, {}, True

    def dto(self, task, config, run_summaries=None):
        fields = task.model_dump()
        warnings = []
        try:
            known = execution_fields(task)
            TaskFields.model_validate(known)
            validate_fields(known)
            if task.project_id not in {p.id for p in config.ado.projects}:
                warnings.append("任务项目不存在")
            if not task.targets:
                warnings.append("运行命令未选择发布目标")
            if not task.git_flow.build_branch:
                warnings.append("未设置构建分支")
        except ValidationError, SettingsError:
            warnings.append("存量任务字段无效；执行前须修正")
        active, latest, unavailable = (
            self._run_summaries() if run_summaries is None else run_summaries
        )
        if unavailable:
            warnings.append("运行库不可用，活动状态未知；暂不可修改任务或来源")
        fields["warnings"] = warnings
        fields["validation"] = {"valid": not warnings}
        fields["active_run_id"] = active.get(task.id)
        fields["last_run"] = latest.get(task.id)
        return fields

    async def get(self, tid=None):
        config = await self.store.read()
        return await asyncio.to_thread(self._get, config, tid)

    def _get(self, config, tid):
        if tid:
            task = find_task(config, tid)
            return dict(revision=config.revision, item=self.dto(task, config))
        run_summaries = self._run_summaries()
        return dict(
            revision=config.revision,
            items=[
                self.dto(t, config, run_summaries)
                for t in sorted(config.tasks.items, key=lambda t: (t.sort_order, t.id))
            ],
        )

    async def save(self, body, tid=None):
        fields = body.model_dump(exclude={"revision"}, exclude_unset=bool(tid))
        if not tid:
            fields = TaskFields.model_validate(fields).model_dump()
        if fields.get("git_flow") is not None:
            normalize_flow(fields["git_flow"])
        validate_fields(fields)
        if fields.get("local_repo_path"):
            await self.git.inspect(fields["local_repo_path"])
        ident = tid or "task:" + str(uuid.uuid4())

        def mutate(c):
            if fields.get("project_id") and fields["project_id"] not in {
                p.id for p in c.ado.projects
            }:
                raise invalid("项目不存在")
            command = fields.get("tg_command")
            if command and any(t.id != ident and t.tg_command == command for t in c.tasks.items):
                raise invalid("TG 指令已存在")
            if tid:
                task = find_task(c, tid)
                for key, value in fields.items():
                    if value is None and key not in {
                        "project_id",
                        "repo_id",
                        "repo_name",
                        "agent_queue_id",
                        "agent_queue_name",
                    }:
                        raise invalid()
                    # Nested persisted extensions survive a full form round trip.
                    if key == "git_flow":
                        value = GitFlow.model_validate(
                            normalize_flow({**task.git_flow.model_dump(), **value})
                        )
                    if key == "targets" and value is not None:
                        value = [
                            {
                                **(task.targets[i].model_dump() if i < len(task.targets) else {}),
                                **target,
                            }
                            for i, target in enumerate(value)
                        ]
                    setattr(task, key, value)
                task = DynamicTask.model_validate(task.model_dump())
                parent = next(
                    p for p in c.tasks.release_configs if any(m.id == tid for m in p.commands)
                )
                command = next(m for m in parent.commands if m.id == tid)
                shared = {
                    "name",
                    "project_id",
                    "repo_id",
                    "repo_name",
                    "local_repo_path",
                    "git_flow",
                    "agent_queue_id",
                    "agent_queue_name",
                }
                if len(parent.commands) > 1 and shared.intersection(fields):
                    raise invalid("共享发布配置请使用发布配置接口修改")
                if "git_flow" in fields:
                    if len(parent.branches) != 1:
                        raise invalid("共享发布配置请使用发布配置接口修改")
                    parent.branches[0] = ReleaseBranch(
                        id=command.branch_id, **task.git_flow.model_dump()
                    )
                for key in ("enabled", "sort_order", "tg_command", "tg_desc"):
                    setattr(command, key, getattr(task, key))
                if "tg_desc" in fields:
                    command.name = task.tg_desc or task.tg_command
                for key in (
                    "name",
                    "project_id",
                    "repo_id",
                    "repo_name",
                    "local_repo_path",
                    "agent_queue_id",
                    "agent_queue_name",
                ):
                    if key in fields:
                        setattr(parent, key, getattr(task, key))
                if "targets" in fields:

                    def signature(t):
                        return json.dumps(
                            {
                                k: getattr(t, k)
                                for k in (
                                    "build_kind",
                                    "build_id",
                                    "release_id",
                                    "release_stage_ids",
                                )
                            },
                            sort_keys=True,
                        )

                    catalog = {signature(t): t for t in parent.targets}
                    selected = []
                    for target in task.targets:
                        key = signature(target)
                        if key not in catalog:
                            item = ReleaseTarget(
                                id="target:" + str(uuid.uuid4()), **target.model_dump()
                            )
                            parent.targets.append(item)
                            catalog[key] = item
                        if target.enabled and catalog[key].id not in selected:
                            selected.append(catalog[key].id)
                    command.target_ids = selected
            else:
                item = group_tasks([DynamicTask(id=ident, **fields)])[0]
                # 兼容创建保持旧表单的人类可读名称，每次创建独立配置。
                item.id = "release:" + str(uuid.uuid4())
                item.name = fields.get("name") or item.name
                c.tasks.release_configs.append(item)

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision, id=ident)

    async def delete(self, tid, revision, detach_acl=False):
        def mutate(c):
            from toolbox_backend.services.releases import detach_commands

            find_task(c, tid)
            detach_commands(c, {tid}, detach_acl)
            for parent in c.tasks.release_configs:
                parent.commands = [m for m in parent.commands if m.id != tid]

        config = await self.store.update(revision, mutate)
        return MutationResponse(revision=config.revision)

    async def order(self, body):
        def mutate(c):
            if len(body.ids) != len(set(body.ids)) or set(body.ids) != {
                t.id for t in c.tasks.items
            }:
                raise invalid("排序必须恰好包含全部任务一次")
            positions = {tid: i for i, tid in enumerate(body.ids)}
            for parent in c.tasks.release_configs:
                for command in parent.commands:
                    command.sort_order = positions[command.id]

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision)
