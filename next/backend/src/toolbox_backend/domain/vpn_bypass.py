"""User-owned bypass preferences; privileged runtime accepts a validated snapshot only."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from toolbox_backend.vpn.bypass_daemon import validate_config


class BypassApp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    executable_path: str | None = None
    application_path: str | None = None


class VpnBypassConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    gateway: str | None = None
    interface: str | None = None
    interval_s: int = Field(default=20, ge=5, le=300)
    retention_s: int = Field(default=300, ge=0, le=3600)
    apps: list[BypassApp] = Field(default_factory=list, max_length=32)
    targets: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def safe_snapshot(self):
        normalized = validate_config(self.model_dump())
        self.targets = normalized["targets"]
        return self


class BypassSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    settings: VpnBypassConfig


class BypassActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class BypassTargetStatus(BaseModel):
    target: str
    gateway: str | None = None
    interface: str | None = None
    owned: bool = False
    verified: bool = False


class BypassStatus(BaseModel):
    mode: Literal["managed"] = "managed"
    installed: bool = False
    running: bool = False
    synced: bool = False
    state: Literal["not_installed", "stopped", "pending", "active", "degraded", "error"] = (
        "not_installed"
    )
    message: str = "尚未安装后台助手；保存配置不代表规则已生效。"
    last_sweep_at: float | None = None
    targets: list[BypassTargetStatus] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "规则按目标 IPv4 地址分流，访问同一地址的所有应用都会受到影响。",
            "只发现已连接的 TCP/UDP 远端地址，不覆盖 IPv6。",
            "应用辅助进程需单独配置；现有连接可能需要重建，VPN 强制策略仍可能阻止直连。",
        ]
    )


class BypassSnapshot(BaseModel):
    revision: int
    settings: VpnBypassConfig
    status: BypassStatus = Field(default_factory=BypassStatus)


class BypassSweepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apply: bool = False


class BypassSweepResult(BaseModel):
    applied: Literal[False] = False
    requires_privilege: bool
    targets: list[str]
    gateway: str | None
    interface: str | None
    errors: list[str]
    message: str


class BypassExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    python_path: str = Field(min_length=1, max_length=4096)


class BypassExport(BaseModel):
    config_json: str
    helper_source: str
    launchd_plist: str
    instructions: list[str]
    runtime_requirement: str
