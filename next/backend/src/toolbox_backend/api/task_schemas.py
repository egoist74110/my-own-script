"""Task editor input is closed; persisted legacy tasks remain permissive."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, field_validator

from toolbox_backend.domain.models import RunEventData
from toolbox_backend.domain.settings import DynamicTask, StrictModel

Operation = Literal["sync_build_release", "deploy_only", "rollback"]
RunStatus = Literal[
    "queued", "running", "cancelling", "cancelled", "succeeded", "failed", "unknown"
]


class TargetInput(StrictModel):
    name: str = Field(default="目标1", max_length=200)
    enabled: bool = True
    build_kind: Literal["pipeline", "build"] | None = None
    build_id: str | None = None
    build_name: str | None = Field(default=None, max_length=200)
    release_id: str | None = None
    release_name: str | None = Field(default=None, max_length=200)
    release_stage_ids: list[str] = Field(default_factory=list, max_length=50)
    release_stage_names: list[str] = Field(default_factory=list, max_length=50)


class MergeInput(StrictModel):
    source: str
    target: str


class FlowInput(StrictModel):
    build_branch: str = ""
    update_branches: list[str] = Field(default_factory=list, max_length=50)
    merges: list[MergeInput] = Field(default_factory=list, max_length=50)
    push_branches: list[str] = Field(default_factory=list, max_length=50)


class TaskFields(StrictModel):
    enabled: bool = True
    sort_order: int = 0
    tg_command: str = Field(default="", max_length=32, pattern=r"^[a-z0-9_]*$")
    tg_desc: str = Field(default="", max_length=2000)
    name: str = Field(default="", max_length=200)
    project_id: str | None = None
    local_repo_path: str = ""
    repo_id: str | None = None
    repo_name: str | None = Field(default=None, max_length=200)
    git_flow: FlowInput = Field(default_factory=FlowInput)
    agent_queue_id: str | None = None
    agent_queue_name: str | None = Field(default=None, max_length=200)
    targets: list[TargetInput] = Field(default_factory=list, max_length=20)


class TaskCreate(TaskFields):
    revision: int = Field(ge=0)


class TaskPatch(StrictModel):
    revision: int = Field(ge=0)
    enabled: bool | None = None
    sort_order: int | None = None
    tg_command: str | None = Field(default=None, max_length=32, pattern=r"^[a-z0-9_]*$")
    tg_desc: str | None = Field(default=None, max_length=2000)
    name: str | None = Field(default=None, max_length=200)
    project_id: str | None = None
    local_repo_path: str | None = None
    repo_id: str | None = None
    repo_name: str | None = Field(default=None, max_length=200)
    git_flow: FlowInput | None = None
    agent_queue_id: str | None = None
    agent_queue_name: str | None = Field(default=None, max_length=200)
    targets: list[TargetInput] | None = Field(default=None, max_length=20)


class TaskOrder(StrictModel):
    revision: int = Field(ge=0)
    ids: list[str] = Field(max_length=10000)


class PreflightRequest(StrictModel):
    revision: int = Field(ge=0)
    operation: Operation
    rollback_offset: int | None = Field(default=None, ge=1, le=5)


class StartRequest(StrictModel):
    plan_id: UUID
    request_id: UUID
    ack_old_app_idle: Literal[True]

    @field_validator("ack_old_app_idle", mode="before")
    @classmethod
    def explicit_idle_ack(cls, value):
        if value is not True:
            raise ValueError("explicit boolean acknowledgement required")
        return value


class TaskValidation(BaseModel):
    valid: bool


class TaskView(DynamicTask):
    warnings: list[str]
    validation: TaskValidation
    active_run_id: str | None


class TaskListResponse(BaseModel):
    revision: int
    items: list[TaskView]


class TaskResponse(BaseModel):
    revision: int
    item: TaskView


class PlanResponse(BaseModel):
    plan_id: UUID
    expires_at: str
    revision: int
    task_summary: dict[str, JsonValue]
    steps: list[dict[str, JsonValue]]
    targets: list[dict[str, JsonValue]]
    warnings: list[str]


class StartResponse(BaseModel):
    run_id: UUID


class StepView(BaseModel):
    run_id: str
    step_no: int
    kind: str
    target_index: int | None
    status: Literal["pending", "running", "succeeded", "failed", "skipped", "unknown"]
    started_at: str | None
    finished_at: str | None
    checkpoint: dict[str, JsonValue]


class EffectView(BaseModel):
    effect_id: str
    run_id: str
    step_no: int
    kind: Literal["git_push", "build_create", "build_cancel", "release_create", "env_deploy"]
    intent_key: str
    intent: dict[str, JsonValue]
    state: Literal["intent", "confirmed", "rejected", "unknown"]
    remote_id: str | None
    owned: bool
    intent_at: str
    confirmed_at: str | None
    error_category: str | None


class RunResponse(BaseModel):
    store_error: str | None = None
    run_id: str
    task_id: str
    operation: Operation
    status: RunStatus
    phase: str
    reason_code: str | None
    created_at: str
    started_at: str | None
    updated_at: str
    finished_at: str | None
    config_revision: int
    task_snapshot: dict[str, JsonValue]
    request_id: str
    request_hash: str
    cancel_requested_at: str | None
    stop_reason: Literal["user", "timeout", "shutdown"] | None
    deadline_at: str
    last_seq: int
    log_bytes: int
    state_version: int
    recovery_state: Literal["none", "pending", "reconciled", "manual_required"]
    summary: str
    steps: list[StepView]
    effects: list[EffectView]


class RunListResponse(BaseModel):
    items: list[RunResponse]
    cursor: str | None


class RunEventsResponse(BaseModel):
    items: list[RunEventData]
    next_seq: int
    has_more: bool
