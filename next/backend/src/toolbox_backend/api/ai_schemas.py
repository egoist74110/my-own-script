"""S5-A HTTP and event contracts. No caller can supply filesystem paths or origin."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, JsonValue, model_validator

from toolbox_backend.api.settings_schemas import RevisionRequest
from toolbox_backend.domain.ai import (
    AIAnalysis,
    AIDefaults,
    AIProfile,
    McpToolPrefix,
    ModelPresets,
    validate_model,
)
from toolbox_backend.domain.settings import StrictModel

ModelName = Annotated[str, AfterValidator(validate_model)]
SessionState = Literal[
    "starting", "idle", "busy", "awaiting_approval", "closing", "ended", "failed"
]


class ProfileCreate(RevisionRequest):
    name: str = Field(min_length=1, max_length=64)
    command: str = Field(min_length=1, max_length=512)
    upgrade_command: str = Field(default="", max_length=512)
    cli: Literal["claude", "codex", "agy", "other"] = "other"


class ProfilePatch(RevisionRequest):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    command: str | None = Field(default=None, min_length=1, max_length=512)
    upgrade_command: str | None = Field(default=None, max_length=512)
    cli: Literal["claude", "codex", "agy", "other"] | None = None


class AISettingsPatch(RevisionRequest):
    ack_cli_registered: bool = False
    selected_profile_id: str | None = None
    model_presets: ModelPresets | None = None
    defaults: AIDefaults | None = None
    analysis: AIAnalysis | None = None
    mcp_tool_prefix: McpToolPrefix | None = None

    @model_validator(mode="after")
    def models(self):
        if self.defaults:
            for defaults in (self.defaults.claude, self.defaults.codex, self.defaults.agy):
                validate_model(defaults.model)
        if self.model_presets:
            for model in (
                self.model_presets.claude + self.model_presets.codex + self.model_presets.agy
            ):
                validate_model(model)
        return self


class ResolvedCLI(BaseModel):
    ok: bool
    path_hint: str | None = None
    version: str | None = None


class ProfileView(AIProfile):
    resolved: ResolvedCLI
    warnings: list[str] = Field(default_factory=list)


class AILimits(BaseModel):
    terminal: int = 6
    headless: int = 6
    per_cli: int = 4
    queue: int = 10
    prompt_bytes: int = 32768
    terminal_buffer_bytes: int = 2097152
    terminal_connections: int = 2


class AIView(BaseModel):
    revision: int
    profiles: list[ProfileView | JsonValue]
    selected_profile_id: str
    defaults: AIDefaults
    analysis: AIAnalysis
    mcp_tool_prefix: McpToolPrefix = Field(default_factory=McpToolPrefix)
    model_presets: ModelPresets
    store_state: Literal["ready", "unavailable"]
    limits: AILimits = Field(default_factory=AILimits)
    warnings: list[str] = Field(default_factory=list)


class ResumeRequest(StrictModel):
    external_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")
    session_id: str | None = Field(default=None, pattern=r"^ais_[a-f0-9]{32}$")

    @model_validator(mode="after")
    def exclusive(self):
        if bool(self.external_id) == bool(self.session_id):
            raise ValueError("invalid resume")
        return self


class SessionCreate(StrictModel):
    request_id: UUID
    kind: Literal["terminal", "chat"]
    profile_id: str = Field(min_length=1, max_length=128)
    repo_id: str = Field(min_length=1, max_length=128)
    model: ModelName | None = None
    effort: str | None = Field(default=None, max_length=16)
    permission: str | None = Field(default=None, max_length=32)
    resume: ResumeRequest | None = None
    initial_prompt: str | None = None
    ack_high_risk: bool = False

    @model_validator(mode="after")
    def prompt_limit(self):
        if self.initial_prompt and len(self.initial_prompt.encode()) > 32768:
            raise ValueError("prompt too long")
        return self


class SendMessage(StrictModel):
    request_id: UUID
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def size(self):
        if len(self.text.encode()) > 32768 or not self.text.strip():
            raise ValueError("invalid prompt")
        return self


class SendResult(BaseModel):
    status: Literal["sent", "queued"]
    position: int = Field(ge=0)


class ResumeSession(StrictModel):
    request_id: UUID
    ack_high_risk: bool = False


class ApprovalDecision(StrictModel):
    decision: Literal["allow_once", "allow_session", "deny"]


class ApprovalResult(BaseModel):
    approval_id: str
    state: Literal["allowed", "denied"]


class ResumeCandidate(BaseModel):
    session_id: str
    title: str = Field(max_length=48)
    updated_at: str


class ResumeCandidates(BaseModel):
    items: list[ResumeCandidate]


class AgyModels(BaseModel):
    items: list[str]
    category: str | None = None


class AnalysisRequest(StrictModel):
    request_id: UUID
    project_id: str = Field(min_length=1, max_length=128)
    repo_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(min_length=1, max_length=128)
    ack_high_risk: bool = False


class PromptResponse(BaseModel):
    prompt: str
    warnings: list[str] = Field(default_factory=list)


class RepoView(BaseModel):
    id: str
    name: str


class AIOrigin(BaseModel):
    kind: Literal["ui", "telegram"] = "ui"


class SessionView(BaseModel):
    id: str
    kind: Literal["terminal", "chat"]
    cli: str
    profile: str
    repo: RepoView
    model: str | None = None
    effort: str | None = None
    permission: str | None = None
    purpose: Literal["general", "work_item_analysis"] = "general"
    work_item_ref: dict[str, JsonValue] | None = None
    state: SessionState
    ended_reason: str | None = None
    exit_code: int | None = None
    origin: AIOrigin = Field(default_factory=AIOrigin)
    has_external_id: bool = False
    queue_len: int = 0
    pending_approval: bool = False
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: str
    ended_at: str | None = None
    last_seq: int
    warnings: list[str] = Field(default_factory=list)


class SessionList(BaseModel):
    items: list[SessionView]


class AIEventData(BaseModel):
    session_id: str
    session_seq: int = Field(ge=1)
    ts: str
    kind: Literal[
        "init",
        "assistant",
        "thinking",
        "tool_use",
        "tool_result",
        "turn_started",
        "turn_completed",
        "turn_failed",
        "approval",
        "notice",
        "error",
        "exit",
    ]
    payload: dict[str, JsonValue]


class AIEventsResponse(BaseModel):
    items: list[AIEventData]
    last_seq: int


class CheckResponse(BaseModel):
    ok: bool
    output: str
    exit_code: int | None = None


class JobResponse(BaseModel):
    job_id: str


class AIJobData(BaseModel):
    job_id: str
    state: Literal["running", "succeeded", "failed", "cancelled"]
    output: str = ""
    exit_code: int | None = None


class AISessionData(BaseModel):
    session_id: str
    state: SessionState
    ended_reason: str | None = None
    last_seq: int


class AIEvent(BaseModel):
    seq: int
    ts: datetime
    topic: Literal["ai"] = "ai"
    type: Literal["ai.event"] = "ai.event"
    data: AIEventData


class AISubscribedData(BaseModel):
    session_id: str
    last_seq: int


class AISubscribedEvent(BaseModel):
    seq: int
    ts: datetime
    topic: Literal["ai"] = "ai"
    type: Literal["ai.subscribed"] = "ai.subscribed"
    data: AISubscribedData


class AISessionEvent(BaseModel):
    seq: int
    ts: datetime
    topic: Literal["ai"] = "ai"
    type: Literal["ai.session"] = "ai.session"
    data: AISessionData


class AIJobEvent(BaseModel):
    seq: int
    ts: datetime
    topic: Literal["ai"] = "ai"
    type: Literal["ai.job"] = "ai.job"
    data: AIJobData
