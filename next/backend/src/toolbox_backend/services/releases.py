"""发布配置是唯一编辑来源，运行时展开为既有任务快照。"""

import asyncio
import uuid

from pydantic import ValidationError

from toolbox_backend.api.release_schemas import CommandFields, ReleaseFields, ReleaseTargetInput
from toolbox_backend.api.settings_schemas import MutationResponse
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import ReleaseConfig, RunCommand
from toolbox_backend.services.tasks import invalid, normalize_flow, validate_fields


def checked(model, value):
    try:
        return model.model_validate(value)
    except ValidationError:
        raise invalid() from None


def find_release(config, ident):
    item = next((c for c in config.tasks.release_configs if c.id == ident), None)
    if item is None:
        raise SettingsError("not_found", "发布配置不存在", 404)
    return item


def find_command(config, cid, mid):
    item = next((m for m in find_release(config, cid).commands if m.id == mid), None)
    if item is None:
        raise SettingsError("not_found", "运行命令不存在", 404)
    return item


def detach_commands(config, ids, detach_acl):
    from toolbox_backend.domain.telegram import as_dict

    groups = [as_dict(g) for g in config.telegram.acl_groups]
    referenced = [
        g.get("name", "")
        for g in groups
        if isinstance(g, dict)
        and isinstance(g.get("task_ids"), list)
        and ids.intersection(g["task_ids"])
    ]
    if referenced and not detach_acl:
        raise SettingsError("task_referenced", "运行命令被 ACL 引用", groups=referenced)
    if detach_acl:
        for group in config.telegram.acl_groups:
            raw = as_dict(group)
            if isinstance(raw, dict) and isinstance(raw.get("task_ids"), list):
                remaining = [tid for tid in raw["task_ids"] if tid not in ids]
                if isinstance(group, dict):
                    group["task_ids"] = remaining
                else:
                    group.task_ids = remaining


class ReleasesService:
    def __init__(self, tasks):
        self.tasks = tasks
        self.store = tasks.store

    def _view(self, config, item, summaries):
        active, latest, unavailable = summaries
        value = item.model_dump()
        value["commands"] = [
            {**m.model_dump(), "last_run": latest.get(m.id), "active_run_id": active.get(m.id)}
            for m in sorted(item.commands, key=lambda m: (m.sort_order, m.id))
        ]
        value["warnings"] = ["运行库不可用，活动状态未知"] if unavailable else []
        return value

    async def get(self, cid=None):
        config = await self.store.read()
        summaries = await asyncio.to_thread(self.tasks._run_summaries)
        if cid:
            return dict(
                revision=config.revision,
                item=self._view(config, find_release(config, cid), summaries),
            )
        return dict(
            revision=config.revision,
            items=[
                self._view(config, c, summaries)
                for c in sorted(config.tasks.release_configs, key=lambda c: (c.sort_order, c.id))
            ],
        )

    async def commands(self, cid, mid=None):
        result = await self.get(cid)
        if mid:
            item = next((m for m in result["item"]["commands"] if m["id"] == mid), None)
            if item is None:
                raise SettingsError("not_found", "运行命令不存在", 404)
            return dict(revision=result["revision"], item=item)
        return dict(revision=result["revision"], items=result["item"]["commands"])

    async def save(self, body, cid=None):
        fields = body.model_dump(exclude={"revision"}, exclude_unset=bool(cid))
        validate_fields(fields)
        if fields.get("local_repo_path"):
            await self.tasks.git.inspect(fields["local_repo_path"])
        ident = cid or "release:" + str(uuid.uuid4())

        def mutate(c):
            old = find_release(c, cid) if cid else None
            merged = {**(old.model_dump() if old else {}), **fields}
            # 缺省 id 由服务端生成；已有目标扩展字段按稳定 id 保留。
            if "targets" in fields:
                if fields["targets"] is None:
                    raise invalid()
                previous = {t.id: t.model_dump() for t in old.targets} if old else {}
                targets = []
                for t in fields["targets"] or []:
                    tid = t.get("id") or "target:" + str(uuid.uuid4())
                    if t.get("id") and tid not in previous:
                        raise invalid("新增目标请省略 id；已有目标必须属于本配置")
                    targets.append({**previous.get(tid, {}), **t, "id": tid})
                merged["targets"] = targets
            if "branches" in fields:
                if fields["branches"] is None:
                    raise invalid()
                previous = {b.id: b.model_dump() for b in old.branches} if old else {}
                branches = []
                for branch in fields["branches"]:
                    bid = branch.get("id") or "branch:" + str(uuid.uuid4())
                    if branch.get("id") and bid not in previous:
                        raise invalid("新增分支请省略 id；已有分支必须属于本配置")
                    value = normalize_flow(
                        {"build_branch": "", **previous.get(bid, {}), **branch, "id": bid}
                    )
                    if not value["build_branch"]:
                        raise invalid("构建分支名不能为空")
                    validate_fields({"git_flow": value})
                    branches.append(value)
                merged["branches"] = branches
            known = {k: v for k, v in merged.items() if k in ReleaseFields.model_fields}
            if known.get("targets") is not None:
                known["targets"] = [
                    {k: v for k, v in t.items() if k in ReleaseTargetInput.model_fields}
                    for t in known["targets"]
                ]
            checked(ReleaseFields, known)
            if merged.get("project_id") and merged["project_id"] not in {
                p.id for p in c.ado.projects
            }:
                raise invalid("项目不存在")
            item = checked(ReleaseConfig, {**merged, "id": ident})
            target_ids = {t.id for t in item.targets}
            if any(not set(m.target_ids) <= target_ids for m in item.commands):
                raise SettingsError("target_in_use", "目标仍被运行命令引用", 422)
            branch_ids = [b.id for b in item.branches]
            names = [b.build_branch for b in item.branches]
            if len(branch_ids) != len(set(branch_ids)) or len(names) != len(set(names)):
                raise invalid("构建分支名或分支标识不能重复")
            if any(m.branch_id not in branch_ids for m in item.commands):
                raise SettingsError("branch_in_use", "分支仍被运行命令引用", 422)
            if old:
                c.tasks.release_configs[c.tasks.release_configs.index(old)] = item
            else:
                c.tasks.release_configs.append(item)

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision, id=ident)

    async def save_command(self, cid, body, mid=None):
        fields = body.model_dump(exclude={"revision"}, exclude_unset=bool(mid))
        ident = mid or "task:" + str(uuid.uuid4())

        def mutate(c):
            parent = find_release(c, cid)
            old = find_command(c, cid, mid) if mid else None
            merged = {**(old.model_dump() if old else {}), **fields}
            checked(
                CommandFields, {k: v for k, v in merged.items() if k in CommandFields.model_fields}
            )
            if merged["branch_id"] not in {b.id for b in parent.branches}:
                raise invalid("所选分支必须属于本配置")
            selected = merged["target_ids"]
            if len(selected) != len(set(selected)) or not set(selected) <= {
                t.id for t in parent.targets
            }:
                raise invalid("所选目标必须属于本配置且不能重复")
            command = merged["tg_command"]
            if command and any(t.id != ident and t.tg_command == command for t in c.tasks.items):
                raise invalid("TG 指令已存在")
            flow = normalize_flow(
                {
                    k: merged[k]
                    for k in ("update_branches", "merges", "push_branches")
                    if merged.get(k) is not None
                }
            )
            for key in ("update_branches", "push_branches", "merges"):
                if key in flow:
                    merged[key] = flow[key]
            validate_fields(
                {
                    "git_flow": flow,
                    "local_repo_path": merged.get("local_repo_path"),
                    "agent_queue_id": merged.get("agent_queue_id"),
                }
            )
            item = checked(RunCommand, {**merged, "id": ident})
            if any(
                getattr(item, k) is not None
                for k in ("update_branches", "merges", "push_branches", "local_repo_path")
            ):
                task = parent.expand(item)
                flow = task.git_flow
                if (
                    flow.update_branches or flow.merges or flow.push_branches
                ) and not task.local_repo_path.strip():
                    raise invalid("没有本地仓库路径时不支持更新、合并、推送规则")
            if old:
                parent.commands[parent.commands.index(old)] = item
            else:
                parent.commands.append(item)

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision, id=ident)

    async def delete(self, cid, revision, detach_acl=False, mid=None):
        def mutate(c):
            item = find_release(c, cid)
            ids = {find_command(c, cid, mid).id} if mid else {m.id for m in item.commands}
            # 即使命令未选目标，也必须检查命令 id 上的活动预约。
            if any(r["task_id"] in ids for r in self.tasks.runs.active_snapshots()):
                raise SettingsError("task_active", "运行命令存在活动运行")
            detach_commands(c, ids, detach_acl)
            if mid:
                item.commands = [m for m in item.commands if m.id != mid]
            else:
                c.tasks.release_configs.remove(item)

        config = await self.store.update(revision, mutate)
        return MutationResponse(revision=config.revision)

    async def order(self, body, cid=None):
        def mutate(c):
            items = find_release(c, cid).commands if cid else c.tasks.release_configs
            if len(body.ids) != len(set(body.ids)) or set(body.ids) != {x.id for x in items}:
                raise invalid("排序必须恰好包含全部条目一次")
            for index, ident in enumerate(body.ids):
                next(x for x in items if x.id == ident).sort_order = index

        config = await self.store.update(body.revision, mutate)
        return MutationResponse(revision=config.revision)
