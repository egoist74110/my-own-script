"""S6 HTTP contracts. Secrets are accepted only in write requests."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, SecretStr

from toolbox_backend.api.settings_schemas import RevisionRequest
from toolbox_backend.domain.mcp import (
    AdoMcp,
    FigmaMcp,
    LarkMcp,
    McpConfig,
    Runtime,
)
from toolbox_backend.domain.settings import StrictModel

CredentialKind = Literal["lark_app_secret", "figma_token"]
LarkRuntimeState = Literal[
    "stopped",
    "starting",
    "running",
    "running_degraded",
    "unhealthy",
    "stopping",
    "logging_in",
    "failed",
]
PatchMarkerState = Literal["applied", "skipped", "failed", "unknown"]
TokenStatusState = Literal["ok", "refresh_failing", "unknown"]
McpJobState = Literal["running", "completed", "failed", "cancelled"]


class MCPSettingsPatch(RevisionRequest):
    ado: AdoMcp | None = None
    lark: LarkMcp | None = None
    figma: FigmaMcp | None = None
    runtime: Runtime | None = None
    mcp: McpConfig | None = None


class CredentialPut(RevisionRequest):
    value: SecretStr = Field(min_length=8, max_length=4096)
    app_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    expiry_days: Literal[1, 7, 30, 90] = 90


class CredentialImport(RevisionRequest):
    kinds: list[CredentialKind] = Field(min_length=1, max_length=2)
    app_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")


class PolicyImport(RevisionRequest):
    path: str = Field(min_length=1, max_length=4096)


class SelfTestRequest(StrictModel):
    timeout_s: float = Field(default=15, ge=1, le=60)


class SelfTestResult(StrictModel):
    ok: bool = False
    protocol_version: str | None = None
    server_name: str | None = None
    tools: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    error_code: str | None = None
    stderr_tail: str = ""


class LarkPatchStatus(StrictModel):
    auth_store: PatchMarkerState = "unknown"
    oidc: PatchMarkerState = "unknown"
    mcp_tool: PatchMarkerState = "unknown"
    all_applied: bool = False


class LarkTokenStatus(StrictModel):
    state: TokenStatusState = "unknown"
    logged_in_at: str | None = None
    last_event_at: str | None = None
    message: str | None = None


class LarkMcpView(LarkMcp):
    state: LarkRuntimeState = "stopped"
    secret_configured: bool = False
    pid: int | None = None
    endpoint: str = "http://localhost:19320/mcp"
    patches: LarkPatchStatus = Field(default_factory=LarkPatchStatus)
    keytar_available: bool = True
    token_status: LarkTokenStatus = Field(default_factory=LarkTokenStatus)
    warnings: list[str] = Field(default_factory=list)
    last_error: str | None = None
    log_tail: str = ""


class FigmaMcpView(FigmaMcp):
    token_configured: bool = False


class RuntimeView(Runtime):
    ready: bool = False
    packages_installed: bool = False
    lark_package_ready: bool = False
    figma_package_ready: bool = False
    keytar_ready: bool = False
    warnings: list[str] = Field(default_factory=list)


class McpJobView(StrictModel):
    job_id: str
    kind: Literal["runtime_install"] = "runtime_install"
    state: McpJobState
    started_at: str
    finished_at: str | None = None
    output: str = ""
    error: str | None = None


class LarkOwnershipRequest(StrictModel):
    revision: int | None = Field(default=None, ge=0)
    ack_old_app_stopped: bool = False
    request_id: UUID | None = None


class LarkActionRequest(StrictModel):
    request_id: UUID | None = None
    timeout_s: float | None = Field(default=None, ge=0.1, le=600)


class RuntimeInstallRequest(StrictModel):
    request_id: UUID | None = None
    force_node: bool = False


class MCPSnapshot(StrictModel):
    revision: int
    ado: AdoMcp
    lark: LarkMcpView = Field(default_factory=LarkMcpView)
    figma: FigmaMcpView = Field(default_factory=FigmaMcpView)
    runtime: RuntimeView
    node_min_version: str
    managed_node_version: str
    self_test_running: bool
    active_job: McpJobView | None = None


class ClientConfig(StrictModel):
    server: Literal["ado", "lark", "figma"]
    cli: Literal["claude", "codex", "agy"]
    name: str
    config: dict[str, JsonValue]
    snippet: str


class McpStatusEvent(BaseModel):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["mcp"] = "mcp"
    type: Literal["mcp.status"] = "mcp.status"
    data: MCPSnapshot


class McpJobEvent(BaseModel):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["mcp"] = "mcp"
    type: Literal["mcp.job"] = "mcp.job"
    data: McpJobView


class McpSubscribedData(BaseModel):
    last_seq: int = Field(ge=0)


class McpSubscribedEvent(BaseModel):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["mcp"] = "mcp"
    type: Literal["mcp.subscribed"] = "mcp.subscribed"
    data: McpSubscribedData
