"""S1 persistent schema. Credentials contain metadata only."""

import copy
import json
import os
import re
import unicodedata
import uuid
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    model_validator,
)

from toolbox_backend.domain.ai import AIConfig
from toolbox_backend.domain.mcp import McpConfig
from toolbox_backend.domain.services import ServicesConfig
from toolbox_backend.domain.telegram import TelegramConfig
from toolbox_backend.domain.vpn import VpnConfig


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9:_.\-]{1,128}", value):
        raise ValueError("invalid identifier")
    return value


def name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise ValueError("invalid name")
    return value


def segment(value: str) -> str:
    if (
        value in {".", ".."}
        or not 1 <= len(value) <= 256
        or any(c in "/\\" or unicodedata.category(c).startswith("C") for c in value)
    ):
        raise ValueError("invalid path segment")
    return value


def repo_path(value: str) -> str:
    if (
        len(value) > 1024
        or not os.path.isabs(value)
        or any(unicodedata.category(c).startswith("C") for c in value)
        or ".." in value.split("/")
    ):
        raise ValueError("invalid repository path")
    return os.path.normpath(value)


def base_url(value: str) -> str:
    try:
        url = urlsplit(value)
        port = url.port
        if (
            len(value) > 2048
            or url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or "?" in value
            or "#" in value
            or any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)
            or "\\" in value
            or port == 0
        ):
            raise ValueError
    except ValueError:
        raise ValueError("invalid base URL") from None
    return value.rstrip("/")


def origin(value: str) -> str:
    url = urlsplit(value)
    host = url.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = url.port or (443 if url.scheme == "https" else 80)
    return f"{url.scheme.lower()}://{host.lower()}:{port}"


def pat_value(value: SecretStr) -> SecretStr:
    raw = value.get_secret_value()
    if not 8 <= len(raw) <= 1024 or any(
        c.isspace() or unicodedata.category(c).startswith("C") for c in raw
    ):
        raise ValueError("invalid credential")
    return value


Id = Annotated[str, AfterValidator(identifier)]
Name = Annotated[str, AfterValidator(name)]
Segment = Annotated[str, AfterValidator(segment)]
BaseURL = Annotated[str, AfterValidator(base_url)]
Pat = Annotated[SecretStr, AfterValidator(pat_value)]
RepoPath = Annotated[str, AfterValidator(repo_path)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Library(StrictModel):
    id: Id
    name: Name
    base_url: BaseURL


class Project(StrictModel):
    id: Id
    library_id: Id
    collection: Segment
    project: Segment


class LocalRepo(StrictModel):
    id: Id
    name: Name
    path: str


class Ado(StrictModel):
    libraries: list[Library] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    local_repos: list[LocalRepo] = Field(default_factory=list)
    active_library_id: Id | None = None
    active_project_id: Id | None = None

    @model_validator(mode="after")
    def references(self):
        libs = {x.id for x in self.libraries}
        projects = {x.id for x in self.projects}
        if (
            len(libs) != len(self.libraries)
            or len(projects) != len(self.projects)
            or len({x.id for x in self.local_repos}) != len(self.local_repos)
            or len({x.name for x in self.libraries}) != len(self.libraries)
            or len({(x.library_id, x.collection, x.project) for x in self.projects})
            != len(self.projects)
            or any(x.library_id not in libs for x in self.projects)
            or (self.active_library_id is not None and self.active_library_id not in libs)
            or (self.active_project_id is not None and self.active_project_id not in projects)
        ):
            raise ValueError("invalid or duplicate ADO reference")
        return self


class DeployTarget(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = "目标1"
    enabled: bool = True
    build_kind: str | None = None
    build_id: str | None = None
    build_name: str | None = None
    release_id: str | None = None
    release_name: str | None = None
    release_stage_ids: list[str] = Field(default_factory=list)
    release_stage_names: list[str] = Field(default_factory=list)


class GitMergeRule(BaseModel):
    model_config = ConfigDict(extra="allow")
    source: str
    target: str


class GitFlow(BaseModel):
    model_config = ConfigDict(extra="allow")
    build_branch: str = ""
    update_branches: list[str] = Field(default_factory=list)
    merges: list[GitMergeRule] = Field(default_factory=list)
    push_branches: list[str] = Field(default_factory=list)


class DynamicTask(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Id
    enabled: bool = True
    sort_order: int = 0
    tg_command: str = ""
    tg_desc: str = ""
    name: str = ""
    project_id: Id | None = None
    local_repo_path: str = ""
    repo_id: str | None = None
    repo_name: str | None = None
    git_flow: GitFlow = Field(default_factory=GitFlow)
    agent_queue_id: str | None = None
    agent_queue_name: str | None = None
    targets: list[DeployTarget] = Field(default_factory=list)


class ReleaseTarget(DeployTarget):
    id: Id


class ReleaseBranch(GitFlow):
    id: Id


class RunCommand(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Id
    name: str = ""
    tg_command: str = ""
    tg_desc: str = ""
    enabled: bool = True
    sort_order: int = 0
    branch_id: Id
    target_ids: list[Id] = Field(default_factory=list)


class ReleaseConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Id
    name: str
    sort_order: int = 0
    project_id: Id | None = None
    repo_id: str | None = None
    repo_name: str | None = None
    local_repo_path: str = ""
    branches: list[ReleaseBranch] = Field(default_factory=list)
    agent_queue_id: str | None = None
    agent_queue_name: str | None = None
    targets: list[ReleaseTarget] = Field(default_factory=list)
    commands: list[RunCommand] = Field(default_factory=list)

    def expand(self, command):
        fields = self.model_dump(
            exclude={"id", "name", "sort_order", "targets", "commands", "branches"}
        )
        selected = {t.id: t for t in self.targets}
        targets = [
            {**selected[tid].model_dump(exclude={"id"}), "enabled": True}
            for tid in command.target_ids
        ]
        extra = command.model_dump(exclude={"target_ids", "branch_id", "name"})
        flow = next(b for b in self.branches if b.id == command.branch_id)
        return DynamicTask(
            **{
                **fields,
                **extra,
                "name": self.name,
                "targets": targets,
                "git_flow": flow.model_dump(exclude={"id"}),
            }
        )


def _group_tasks_v7(items):
    """按完整执行来源分组；确定性标识保证重复迁移得到同样结果。"""
    groups = {}
    common = ("project_id", "repo_id", "local_repo_path", "git_flow", "agent_queue_id")
    for item in items:
        task = DynamicTask.model_validate(item).model_dump()
        key = json.dumps({k: task[k] for k in common}, sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, []).append(task)
    configs = []
    for key, tasks in groups.items():
        first = tasks[0]
        ident = "release:" + str(uuid.uuid5(uuid.NAMESPACE_URL, key))
        fields = {
            k: first[k]
            for k in (
                *common,
                "repo_name",
                "agent_queue_name",
            )
        }
        targets, commands, seen = [], [], {}
        for task in tasks:
            selected = []
            for target in task["targets"]:
                target_key = json.dumps(
                    {
                        k: target[k]
                        for k in (
                            "build_kind",
                            "build_id",
                            "release_id",
                            "release_stage_ids",
                        )
                    },
                    sort_keys=True,
                )
                if target_key not in seen:
                    tid = "target:" + str(uuid.uuid5(uuid.NAMESPACE_URL, ident + target_key))
                    seen[target_key] = tid
                    targets.append({**target, "id": tid, "enabled": True})
                if target["enabled"] and seen[target_key] not in selected:
                    selected.append(seen[target_key])
            # 空选择的历史命令保留，执行入口拒绝；迁移不擅自启用目标。
            extra = {k: v for k, v in task.items() if k not in DynamicTask.model_fields}
            commands.append(
                {
                    **extra,
                    **{
                        k: task[k]
                        for k in (
                            "id",
                            "tg_command",
                            "tg_desc",
                            "enabled",
                            "sort_order",
                        )
                    },
                    "name": task["tg_desc"] or task["tg_command"],
                    "target_ids": selected,
                }
            )
        configs.append(
            dict(
                id=ident,
                name=first["repo_name"] or first["repo_id"] or "发布配置",
                sort_order=min(t["sort_order"] for t in tasks),
                targets=targets,
                commands=commands,
                **fields,
            )
        )
    for config in configs:
        same_repo = [
            c
            for c in configs
            if (
                c["repo_id"] == config["repo_id"]
                if config["repo_id"]
                else c["repo_name"] == config["repo_name"]
            )
        ]
        if len(same_repo) > 1:
            config["name"] += f"（{config['git_flow']['build_branch']}）"
    return configs


class _TaskView(list):
    """兼容旧导入器与开发种子的追加操作，不作为持久化来源。"""

    def __init__(self, owner, values):
        super().__init__(values)
        self.owner = owner

    def append(self, value):
        item = group_tasks([value])[0]
        if any(c.id == item.id for c in self.owner.release_configs):
            item.id = "release:" + str(uuid.uuid4())
        if value.name:
            item.name = value.name
        self.owner.release_configs.append(item)
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)

    def clear(self):
        self.owner.release_configs.clear()
        super().clear()


class Tasks(StrictModel):
    release_configs: list[ReleaseConfig] = Field(default_factory=list)
    legacy_flows: list[dict[str, JsonValue]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def legacy_items(cls, value):
        if isinstance(value, dict) and "items" in value:
            value = dict(value)
            items = value.pop("items")
            if items and value.get("release_configs"):
                raise ValueError("任务与发布配置不能同时作为写入来源")
            if items:
                value["release_configs"] = group_tasks(items)
        return value

    @model_validator(mode="after")
    def references(self):
        ids = [c.id for c in self.release_configs]
        commands = [m.id for c in self.release_configs for m in c.commands]
        if len(ids) != len(set(ids)) or len(commands) != len(set(commands)):
            raise ValueError("发布配置或运行命令标识重复")
        for config in self.release_configs:
            branches = [b.id for b in config.branches]
            names = [b.build_branch for b in config.branches]
            if (
                len(branches) != len(set(branches))
                or len(names) != len(set(names))
                or any(m.branch_id not in branches for m in config.commands)
            ):
                raise ValueError("发布分支引用无效或构建分支名重复")
            targets = [t.id for t in config.targets]
            if len(targets) != len(set(targets)) or any(
                len(m.target_ids) != len(set(m.target_ids)) or not set(m.target_ids) <= set(targets)
                for m in config.commands
            ):
                raise ValueError("发布目标引用无效")
        return self

    @property
    def items(self):
        return _TaskView(self, [c.expand(m) for c in self.release_configs for m in c.commands])

    @items.setter
    def items(self, values):
        self.release_configs = group_tasks(values)
        names = {v.id: v.name for v in values if v.name}
        for config in self.release_configs:
            if config.commands and config.commands[0].id in names:
                config.name = names[config.commands[0].id]


def config_v6_to_v7(raw):
    result = copy.deepcopy(raw)
    if result.get("schema_version") == 7:
        return result
    if result.get("schema_version") != 6:
        raise ValueError("仅支持 v6 发布配置迁移")
    tasks = result.setdefault("tasks", {})
    items = tasks.pop("items", None)
    if items is not None:
        if items and tasks.get("release_configs"):
            raise ValueError("迁移发现两份任务来源")
        if items or "release_configs" not in tasks:
            tasks["release_configs"] = _group_tasks_v7(items)
    tasks.setdefault("release_configs", [])
    result["schema_version"] = 7
    return result


def config_v7_to_v8(raw):
    """按共享来源合并目录；保留命令标识，完整 GitFlow 参与分支去重。"""
    result = copy.deepcopy(raw)
    if result.get("schema_version") == 8:
        return result
    if result.get("schema_version") != 7:
        raise ValueError("仅支持 v7 分支目录迁移")
    groups = {}
    common = ("project_id", "repo_id", "local_repo_path", "agent_queue_id")
    for config in result.setdefault("tasks", {}).get("release_configs", []):
        key = json.dumps({k: config.get(k) for k in common}, sort_keys=True)
        groups.setdefault(key, []).append(config)
    merged = []
    for configs in groups.values():
        configs.sort(key=lambda c: (c.get("sort_order", 0), c["id"]))
        first = configs[0]
        item = copy.deepcopy(first)
        item.pop("git_flow", None)
        item["branches"], item["targets"], item["commands"] = [], [], []
        repo = first.get("repo_name") or first.get("repo_id") or "发布配置"
        automatic_names = []
        for config in configs:
            title = config.get("repo_name") or config.get("repo_id") or "发布配置"
            automatic_names.append(
                config["name"]
                in {
                    title,
                    f"{title}（{config.get('git_flow', {}).get('build_branch', '')}）",
                }
            )
        if all(automatic_names):
            item["name"] = repo
        flows, targets = {}, {}
        for config in configs:
            flow = GitFlow.model_validate(config.get("git_flow", {})).model_dump()
            key = json.dumps(flow, sort_keys=True, ensure_ascii=False)
            if key not in flows:
                bid = "branch:" + str(uuid.uuid5(uuid.NAMESPACE_URL, item["id"] + key))
                flows[key] = bid
                item["branches"].append({**flow, "id": bid})
            bid = flows[key]
            mapping = {}
            for target in config.get("targets", []):
                key = json.dumps(
                    {
                        k: target.get(k)
                        for k in ("build_kind", "build_id", "release_id", "release_stage_ids")
                    },
                    sort_keys=True,
                )
                if key not in targets:
                    targets[key] = target["id"]
                    item["targets"].append(copy.deepcopy(target))
                mapping[target["id"]] = targets[key]
            for command in config.get("commands", []):
                item["commands"].append(
                    {
                        **command,
                        "branch_id": bid,
                        "target_ids": list(
                            dict.fromkeys(mapping[tid] for tid in command["target_ids"])
                        ),
                    }
                )
        merged.append(item)
    result["tasks"]["release_configs"] = merged
    result["schema_version"] = 8
    return result


def group_tasks(items):
    raw = {"schema_version": 7, "tasks": {"release_configs": _group_tasks_v7(items)}}
    return [
        ReleaseConfig.model_validate(c) for c in config_v7_to_v8(raw)["tasks"]["release_configs"]
    ]


def task_label(config, tid, fallback="历史任务"):
    for release in config.tasks.release_configs:
        for command in release.commands:
            if command.id == tid:
                return f"{release.name}：{command.name or command.tg_desc or command.tg_command}"
    return fallback


class Imported(StrictModel):
    work_items: dict[str, JsonValue] = Field(default_factory=dict)
    ai: dict[str, JsonValue] = Field(default_factory=dict)
    lark: dict[str, JsonValue] = Field(default_factory=dict)
    figma: dict[str, JsonValue] = Field(default_factory=dict)
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class ImportState(StrictModel):
    state: Literal["none", "in_progress", "completed", "declined", "failed"] = "none"
    source_dir: str | None = None
    fingerprint: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    summary: dict[str, JsonValue] = Field(default_factory=dict)
    error: str | None = None
    written_credentials: list[str] = Field(default_factory=list)


class CredentialMeta(StrictModel):
    kind: Literal[
        "ado_pat", "telegram_bot", "telegram_ai_bot", "lark_app_secret", "figma_token"
    ] = "ado_pat"
    ref: Id
    source: Literal["imported", "manual"]
    updated_at: str
    state: Literal["active", "pending_delete"] = "active"


class Config(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: Literal[8] = 8
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    vpn: VpnConfig = Field(default_factory=VpnConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    revision: int = Field(default=0, ge=0)
    updated_at: str | None = None
    ado: Ado = Field(default_factory=Ado)
    tasks: Tasks = Field(default_factory=Tasks)
    imported: Imported = Field(default_factory=Imported)
    import_: ImportState = Field(default_factory=ImportState, alias="import")
    credentials: dict[str, CredentialMeta] = Field(default_factory=dict)

    @model_validator(mode="after")
    def credential_accounts(self):
        if any(
            key
            != {
                "telegram_bot": "telegram_bot_token",
                "lark_app_secret": f"lark_app_secret:{meta.ref}",
                "figma_token": "figma_token",
                "telegram_ai_bot": f"ai_bot_token:{meta.ref}",
            }.get(meta.kind, f"ado_pat:{meta.ref}")
            for key, meta in self.credentials.items()
        ):
            raise ValueError("invalid credential account")
        return self
