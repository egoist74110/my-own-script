from __future__ import annotations

from typing import Any, Optional

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


class LocalRepoEntry(BaseModel):
    id: str
    name: str
    path: str


class AiPolicyConfig(BaseModel):
    default_decision: str = ""

    allowed_work_item_types: list[str] = Field(default_factory=list)
    review_work_item_types: list[str] = Field(default_factory=list)
    deny_work_item_types: list[str] = Field(default_factory=list)

    deny_keywords: list[str] = Field(default_factory=list)
    review_keywords: list[str] = Field(default_factory=list)

    forbidden_paths: list[str] = Field(default_factory=list)
    review_paths: list[str] = Field(default_factory=list)

    max_target_files_without_review: int = 0
    require_human_review_if_no_target_paths: Optional[bool] = None


class AiTargetConfig(BaseModel):
    id: str
    name: str = ""
    enabled: bool = True
    target_type: str = "prompt_copy"  # prompt_copy | command | url
    command: str = ""
    cwd: str = ""
    url: str = ""
    prompt_template: str = ""


class AiToolSettings(BaseModel):
    selected_profile_id: str = "codex"
    profiles: list["AiCliProfile"] = Field(default_factory=list)
    prompt_template: str = ""


class AiCliProfile(BaseModel):
    id: str
    name: str
    command: str = ""
    # 升级命令：点「升级」按钮时跑这条（如 `npm install -g @openai/codex@latest`、`claude update`）。
    upgrade_command: str = ""
    builtin: bool = False


class AiBotBinding(BaseModel):
    """把某个 AI（对应 AiCliProfile.id）绑定到一个专属 Telegram 机器人。

    Bot Token 是密钥，存系统钥匙串（keyring，key=ai_bot_token:<ai_id>），不落本文件；
    这里只存非密信息：@用户名（可选，用于显示与生成跳转提示）。
    """
    ai_id: str
    username: str = ""


class ProjectAiSettings(BaseModel):
    enabled: bool = True
    show_quick_action_buttons: bool = True
    use_default_policy: bool = True
    target_id: str = ""
    policy: AiPolicyConfig = Field(default_factory=AiPolicyConfig)


class AiSettings(BaseModel):
    enabled: bool = True
    require_policy_check_before_code_change: bool = True
    allow_direct_code_change: bool = False
    tool: AiToolSettings = Field(default_factory=AiToolSettings)
    # 每个 AI 的专属 Telegram 机器人绑定（AI 对话走各自机器人，不和任务通知混在一起）
    bots: list[AiBotBinding] = Field(default_factory=list)
    default_target_id: str = ""
    targets: list[AiTargetConfig] = Field(default_factory=list)
    default_policy: AiPolicyConfig = Field(default_factory=AiPolicyConfig)
    project_overrides: dict[str, ProjectAiSettings] = Field(default_factory=dict)


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
    local_repos: list[LocalRepoEntry] = Field(default_factory=list)
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

    work_items_team: str = ""
    work_items_board: str = ""
    work_items_project_id: str = ""
    work_items_local_repo_id: str = ""

    ai: AiSettings = Field(default_factory=AiSettings)


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

    # Agent pool (ADO Agent Queue) override for classic Build triggers.
    # None => use the pipeline definition's default pool (Default).
    agent_queue_id: Optional[str] = None
    agent_queue_name: Optional[str] = None  # display-only echo

    # deploy targets (build+release+stages)
    targets: list[DeployTarget] = Field(default_factory=list)


class TaskSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    # New dynamic tasks
    tasks: list[DynamicTaskConfig] = Field(default_factory=list)

    # Legacy fixed tasks (kept for back-compat; will be migrated into tasks)
    flows: list[FlowTaskConfig] = Field(default_factory=list)


def _project_value(project: Any, *keys: str) -> str:
    if project is None:
        return ""
    for key in keys:
        value = getattr(project, key, None)
        if value in (None, "") and isinstance(project, dict):
            value = project.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def project_entry_id(project: Any) -> str:
    return _project_value(project, "id", "project_id")


def project_entry_library_id(project: Any) -> str:
    return _project_value(project, "library_id", "repo_id")


def project_entry_collection(project: Any) -> str:
    return _project_value(project, "collection", "collection_name")


def project_entry_name(project: Any) -> str:
    return _project_value(project, "project", "name", "project_name")
