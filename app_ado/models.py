from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class LibraryEntry(BaseModel):
    id: str
    name: str
    base_url: str


class ProjectEntry(BaseModel):
    id: str
    library_id: str
    collection: str
    project: str


class DeployTarget(BaseModel):
    """One deployment unit: build + release + stages."""

    name: str = "目标1"
    enabled: bool = True

    build_kind: Optional[str] = None
    build_id: Optional[str] = None
    build_name: Optional[str] = None

    release_id: Optional[str] = None
    release_name: Optional[str] = None

    release_stage_ids: list[str] = Field(default_factory=list)
    release_stage_names: list[str] = Field(default_factory=list)


class FlowTaskConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = "sync_merge_build_release"  # or sync_build_release
    enabled: bool = True

    project_id: Optional[str] = None

    # local repo folder to run git commands
    local_repo_path: str = ""

    repo_id: Optional[str] = None
    repo_name: Optional[str] = None
    source_branch: str = ""
    target_branch: str = ""

    # New: multiple deploy targets (build+release+stages)
    targets: list[DeployTarget] = Field(default_factory=list)

    # Back-compat (single target) fields (will be migrated into targets)
    build_kind: Optional[str] = None
    build_id: Optional[str] = None
    build_name: Optional[str] = None

    release_id: Optional[str] = None
    release_name: Optional[str] = None

    release_stage_ids: list[str] = Field(default_factory=list)
    release_stage_names: list[str] = Field(default_factory=list)


class UiSettings(BaseModel):
    libraries: list[LibraryEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    active_library_id: Optional[str] = None
    active_project_id: Optional[str] = None

    telegram_chat_id: str = ""
    telegram_whitelist: list[str] = Field(default_factory=list)
    telegram_control_enabled: bool = False

    # Telegram notification privacy
    telegram_notify_include_details: bool = False

    # ACL groups/members for Telegram control
    telegram_acl_groups: list[dict] = Field(default_factory=list)
    telegram_acl_members: list[dict] = Field(default_factory=list)


class GitMergeRule(BaseModel):
    source: str
    target: str


class GitFlow(BaseModel):
    """Configurable git branch flow."""

    # Branch used for build/release triggering.
    # If empty, will fall back to last merge target, else last update branch.
    build_branch: str = ""

    update_branches: list[str] = Field(default_factory=list)
    merges: list[GitMergeRule] = Field(default_factory=list)
    push_branches: list[str] = Field(default_factory=list)


class DynamicTaskConfig(BaseModel):
    """Dynamic task definition (CRUD) with configurable git flow."""

    model_config = ConfigDict(extra="allow")

    id: str
    enabled: bool = True

    # sort order for UI + Telegram /help list
    sort_order: int = 0

    # Use tg_command as the only "name" for identity; tg_desc is human-friendly label.
    tg_command: str = ""  # a-z0-9_
    tg_desc: str = ""

    # Legacy/optional display name (deprecated; kept for backward compatibility)
    name: str = ""

    project_id: Optional[str] = None

    # local repo folder to run git commands
    local_repo_path: str = ""

    repo_id: Optional[str] = None
    repo_name: Optional[str] = None

    git_flow: GitFlow = Field(default_factory=GitFlow)

    # deploy targets (build+release+stages)
    targets: list[DeployTarget] = Field(default_factory=list)


class TaskSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    # New dynamic tasks
    tasks: list[DynamicTaskConfig] = Field(default_factory=list)

    # Legacy fixed tasks (kept for back-compat; will be migrated into tasks)
    flows: list[FlowTaskConfig] = Field(default_factory=list)
