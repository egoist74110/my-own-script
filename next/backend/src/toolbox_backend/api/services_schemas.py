"""S7 HTTP/WS DTOs. No credential fields exist in this contract."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from toolbox_backend.domain.services import Model, ServicesConfig


class ActionRequest(Model):
    request_id: UUID | None = None
    ack_public: bool = Field(default=False, strict=True)


class TunnelCreate(ActionRequest):
    target_url: str = Field(min_length=1, max_length=2048)


class SettingsPatch(Model):
    revision: int = Field(ge=0)
    services: ServicesConfig


class ProtocolRequest(Model):
    revision: int = Field(ge=0)
    protocol: Literal["http2", "quic"]


class LegacyImport(Model):
    revision: int = Field(ge=0)
    path: str = Field(min_length=1, max_length=4096)


class NetworkInfo(Model):
    vpn_ip: str | None = None
    lan_ip: str | None = None
    on_lan: bool = False


class BinaryInfo(Model):
    found: bool = False
    path: str | None = None
    confirmed: bool = False
    version: str | None = None


class BinariesView(Model):
    code_server: BinaryInfo = Field(default_factory=BinaryInfo)
    cloudflared: BinaryInfo = Field(default_factory=BinaryInfo)


class ServiceView(Model):
    id: str | None = None
    state: Literal[
        "stopped", "starting", "running", "stopping", "failed", "external", "unhealthy"
    ] = "stopped"
    owned: bool = False
    port: int | None = None
    url: str | None = None
    target_url: str | None = None
    last_error: str | None = None
    log_tail_available: bool = False


class CloudflaredView(Model):
    global_: ServiceView = Field(default_factory=ServiceView, alias="global")
    tunnels: list[ServiceView] = Field(default_factory=list)


class ServicesSnapshot(Model):
    code_server: ServiceView
    cloudflared: CloudflaredView
    network: NetworkInfo
    binaries: BinariesView
    settings: ServicesConfig
    revision: int


class SettingsResult(Model):
    revision: int
    restart_required: bool = False


class LogsResult(Model):
    text: str


class ServicesStatusData(Model):
    services_seq: int = Field(ge=1)
    snapshot: ServicesSnapshot


class ServicesStatusEvent(Model):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["services"] = "services"
    type: Literal["services.status"] = "services.status"
    data: ServicesStatusData


class ServicesSubscribedData(Model):
    last_seq: int = Field(ge=0)


class ServicesSubscribedEvent(Model):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["services"] = "services"
    type: Literal["services.subscribed"] = "services.subscribed"
    data: ServicesSubscribedData
