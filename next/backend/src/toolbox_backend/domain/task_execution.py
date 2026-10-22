"""The S3-B adapter boundary. No HTTP-switchable fake or second execution model."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class JournalCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(git|git_cleanup|build|release|rollback)$")
    root: str | None = None
    common_dir: str | None = None
    lock_keys: list[str] | None = None
    original_head: str | None = None
    original_branch: str | None = None
    original_refs: dict[str, str | None] | None = None
    new_refs: dict[str, str] | None = None
    expected_commit: str | None = None
    repo_needs_attention: bool | None = None
    target_index: int | None = Field(default=None, ge=0, le=19)
    definition_id: int | None = Field(default=None, ge=1, le=2147483647)
    queue_id: int | None = Field(default=None, ge=1, le=2147483647)
    repo_id: str | None = None
    branch: str | None = None
    commit: str | None = None
    api_version: str | None = None
    deadline_at: str | None = None
    build_id: int | None = None
    pipeline_run_id: int | None = None
    release_definition_id: int | None = None
    release_id: int | None = None
    stage_ids: list[int] | None = Field(default=None, max_length=50)
    deployment_attempts: dict[str, int] | None = None
    owned: bool | None = None
    result: str | None = Field(default=None, max_length=100)


class EffectIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(git_push|build_create|build_cancel|release_create|env_deploy)$")
    api_kind: Literal["pipeline", "build", "release", "git"] | None = None
    branch: str | None = None
    commit: str | None = None
    previous_remote_commit: str | None = None
    definition_id: int | None = Field(default=None, ge=1, le=2147483647)
    queue_id: int | None = Field(default=None, ge=1, le=2147483647)
    repo_id: str | None = None
    ref_name: str | None = None
    source_version: str | None = None
    build_id: int | None = None
    pipeline_run_id: int | None = None
    release_definition_id: int | None = None
    release_id: int | None = None
    environment_id: int | None = None
    baseline_attempt: int | None = None
    api_version: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    manual_environments: list[str] | None = Field(default=None, max_length=500)


@dataclass
class PreparedExecution:
    steps: list[dict] = field(default_factory=list)
    targets: list[dict] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    frozen: dict = field(default_factory=dict)
    budget_seconds: int = 300


@dataclass
class ExecutionOutcome:
    status: str
    reason_code: str | None = None
    summary: str = ""


class TaskExecutor(Protocol):
    async def prepare(
        self, snapshot: dict, operation: str, rollback_offset: int | None
    ) -> PreparedExecution: ...

    async def execute(self, context) -> ExecutionOutcome: ...

    async def reconcile(self, context) -> ExecutionOutcome:
        """Read only. Never create/cancel/deploy/push, including repeated calls."""
        ...
