"""S1 persistent schema. Credentials contain metadata only."""

import os
import re
import unicodedata
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


class Tasks(StrictModel):
    items: list[DynamicTask] = Field(default_factory=list)
    legacy_flows: list[dict[str, JsonValue]] = Field(default_factory=list)


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
    schema_version: Literal[5] = 5
    services: ServicesConfig = Field(default_factory=ServicesConfig)
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
