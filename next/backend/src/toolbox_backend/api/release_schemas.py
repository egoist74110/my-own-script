"""发布配置与固定运行命令的编辑契约。"""

from pydantic import BaseModel, ConfigDict, Field

from toolbox_backend.api.task_schemas import FlowInput, LastRunSummary, MergeInput, TargetInput
from toolbox_backend.domain.settings import GitMergeRule, ReleaseConfig, RunCommand, StrictModel


class ReleaseTargetInput(TargetInput):
    id: str | None = None


class ReleaseBranchInput(FlowInput):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    merges: list[GitMergeRule] = Field(default_factory=list, max_length=50)


class ReleaseFields(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    project_id: str | None = None
    repo_id: str | None = None
    repo_name: str | None = Field(default=None, max_length=200)
    local_repo_path: str = ""
    branches: list[ReleaseBranchInput] = Field(default_factory=list, max_length=100)
    agent_queue_id: str | None = None
    agent_queue_name: str | None = Field(default=None, max_length=200)
    targets: list[ReleaseTargetInput] = Field(default_factory=list, max_length=100)


class ReleaseCreate(ReleaseFields):
    revision: int = Field(ge=0)


class ReleasePatch(StrictModel):
    revision: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None
    project_id: str | None = None
    repo_id: str | None = None
    repo_name: str | None = Field(default=None, max_length=200)
    local_repo_path: str | None = None
    branches: list[ReleaseBranchInput] | None = Field(default=None, max_length=100)
    agent_queue_id: str | None = None
    agent_queue_name: str | None = Field(default=None, max_length=200)
    targets: list[ReleaseTargetInput] | None = Field(default=None, max_length=100)


class CommandFields(StrictModel):
    name: str = Field(min_length=1, max_length=2000)
    tg_command: str = Field(default="", max_length=32, pattern=r"^[a-z0-9_]*$")
    tg_desc: str = Field(default="", max_length=2000)
    enabled: bool = True
    sort_order: int = 0
    branch_id: str
    target_ids: list[str] = Field(min_length=1, max_length=20)
    update_branches: list[str] | None = Field(default=None, max_length=50)
    merges: list[MergeInput] | None = Field(default=None, max_length=50)
    push_branches: list[str] | None = Field(default=None, max_length=50)
    local_repo_path: str | None = None
    agent_queue_id: str | None = None
    agent_queue_name: str | None = Field(default=None, max_length=200)


class CommandCreate(CommandFields):
    revision: int = Field(ge=0)


class CommandPatch(StrictModel):
    revision: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=2000)
    tg_command: str | None = Field(default=None, max_length=32, pattern=r"^[a-z0-9_]*$")
    tg_desc: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    sort_order: int | None = None
    branch_id: str | None = None
    target_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    update_branches: list[str] | None = Field(default=None, max_length=50)
    merges: list[MergeInput] | None = Field(default=None, max_length=50)
    push_branches: list[str] | None = Field(default=None, max_length=50)
    local_repo_path: str | None = None
    agent_queue_id: str | None = None
    agent_queue_name: str | None = Field(default=None, max_length=200)


class CommandView(RunCommand):
    last_run: LastRunSummary | None
    active_run_id: str | None


class ReleaseView(ReleaseConfig):
    commands: list[CommandView]
    warnings: list[str]


class ReleaseResponse(BaseModel):
    revision: int
    item: ReleaseView


class ReleaseListResponse(BaseModel):
    revision: int
    items: list[ReleaseView]


class CommandResponse(BaseModel):
    revision: int
    item: CommandView


class CommandListResponse(BaseModel):
    revision: int
    items: list[CommandView]
