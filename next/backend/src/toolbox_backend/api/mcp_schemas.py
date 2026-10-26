"""S6-A HTTP contracts. Secrets are accepted only in write requests."""

from typing import Literal

from pydantic import Field, JsonValue, SecretStr

from toolbox_backend.api.settings_schemas import RevisionRequest
from toolbox_backend.domain.mcp import AdoMcp, FigmaMcp, LarkMcp, McpConfig, Runtime
from toolbox_backend.domain.settings import StrictModel

CredentialKind = Literal["lark_app_secret", "figma_token"]


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


class MCPSnapshot(StrictModel):
    revision: int
    ado: AdoMcp
    runtime: Runtime
    node_min_version: str
    managed_node_version: str
    self_test_running: bool


class ClientConfig(StrictModel):
    server: Literal["ado", "lark", "figma"]
    cli: Literal["claude", "codex", "agy"]
    name: str
    config: dict[str, JsonValue]
    snippet: str
