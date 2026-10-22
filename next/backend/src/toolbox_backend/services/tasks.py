"""Single config writer, editor validation and active-resource coordination."""

import asyncio
import re
import uuid

from pydantic import ValidationError

from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.api.task_schemas import FlowInput, MergeInput, TargetInput, TaskFields
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import DynamicTask, repo_path, segment


def invalid(message="任务配置无效"):
    return SettingsError("validation_error", message, 422)


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

    def dto(self, task, config):
        fields = task.model_dump()
        warnings = []
        try:
            known = execution_fields(task)
            TaskFields.model_validate(known)
            validate_fields(known)
            if task.project_id not in {p.id for p in config.ado.projects}:
                warnings.append("任务项目不存在")
            if not task.git_flow.build_branch:
                warnings.append("未设置构建分支")
        except ValidationError, SettingsError:
            warnings.append("存量任务字段无效；执行前须修正")
        try:
            active = self.runs.active_snapshots()
        except SettingsError:
            active = []
            warnings.append("运行库不可用，活动状态未知；暂不可修改任务或来源")
        fields["warnings"] = warnings
        fields["validation"] = {"valid": not warnings}
        fields["active_run_id"] = next(
            (r["run_id"] for r in active if r["task_id"] == task.id), None
        )
        return fields

    async def get(self, tid=None):
        config = await self.store.read()
        return await asyncio.to_thread(self._get, config, tid)

    def _get(self, config, tid):
        if tid:
            return dict(revision=config.revision, item=self.dto(find_task(config, tid), config))
        return dict(
            revision=config.revision,
            items=[
                self.dto(t, config)
                for t in sorted(config.tasks.items, key=lambda t: (t.sort_order, t.id))
            ],
        )

    async def save(self, body, tid=None):
        fields = body.model_dump(exclude={"revision"}, exclude_unset=bool(tid))
        if not tid:
            fields = TaskFields.model_validate(fields).model_dump()
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
                        value = {**task.git_flow.model_dump(), **value}
                    if key == "targets" and value is not None:
                        value = [
                            {
                                **(task.targets[i].model_dump() if i < len(task.targets) else {}),
                                **target,
                            }
                            for i, target in enumerate(value)
                        ]
                    setattr(task, key, value)
            else:
                c.tasks.items.append(DynamicTask(id=ident, **fields))

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision, id=ident)

    async def delete(self, tid, revision):
        def mutate(c):
            find_task(c, tid)
            groups = c.imported.telegram.get("acl_groups", [])
            referenced = [
                g.get("name", "")
                for g in groups
                if isinstance(g, dict) and tid in g.get("task_ids", [])
            ]
            if referenced:
                raise SettingsError("task_referenced", "任务被 ACL 引用", groups=referenced)
            c.tasks.items = [t for t in c.tasks.items if t.id != tid]

        config = await self.store.update(revision, mutate)
        return MutationResponse(revision=config.revision)

    async def order(self, body):
        def mutate(c):
            if len(body.ids) != len(set(body.ids)) or set(body.ids) != {
                t.id for t in c.tasks.items
            }:
                raise invalid("排序必须恰好包含全部任务一次")
            positions = {tid: i for i, tid in enumerate(body.ids)}
            for task in c.tasks.items:
                task.sort_order = positions[task.id]

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision)
