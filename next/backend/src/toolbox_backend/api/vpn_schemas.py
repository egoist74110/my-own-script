"""S8 VPN API and WebSocket DTOs; secret values are never response fields."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from toolbox_backend.domain.settings import StrictModel
from toolbox_backend.domain.vpn import VpnConfig


class VpnSnapshot(StrictModel):
    connected: bool
    ip: str | None
    client: dict
    credentials: dict[Literal["password", "totp_secret"], bool]
    permissions: dict[Literal["screen_recording", "accessibility"], str]
    settings: VpnConfig
    current_run: VpnRunView | None = None
    revision: int


class VpnSettingsPatch(StrictModel):
    revision: int = Field(ge=0)
    vpn: VpnConfig


class CredentialWrite(StrictModel):
    value: str = Field(min_length=1, max_length=4096)


class CredentialConfigured(StrictModel):
    configured: bool


class LegacyCredentialsImport(StrictModel):
    kinds: list[Literal["vpn_password", "vpn_totp_secret"]] = Field(min_length=1, max_length=2)
    fields: bool = False


class TotpImport(StrictModel):
    text: str = Field(min_length=1, max_length=1 << 20)
    index: int | None = Field(default=None, ge=0, le=1000)


class ManualMfa(StrictModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


class ManualMfaResult(StrictModel):
    accepted: bool


class VpnRunRequest(StrictModel):
    request_id: UUID | None = None
    max_rung: Literal[0, 1, 2, 3] | None = None
    allow_login: bool = True


class VpnRunView(StrictModel):
    run_id: str
    request_id: str | None = None
    state: Literal["queued", "running", "cancelling", "cancelled", "succeeded", "failed"]
    rung: int = 0
    created_at: datetime
    updated_at: datetime
    ip: str | None = None
    error_code: str | None = None
    events: list[dict] = Field(default_factory=list)


class VpnRunList(StrictModel):
    items: list[VpnRunView]


class VpnRunEventData(StrictModel):
    run_id: str
    run_seq: int = Field(ge=1)
    state: str
    rung: int
    event: str | None = None
    error_code: str | None = None
    ip: str | None = None


class _VpnEvent(StrictModel):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["vpn"] = "vpn"
    data: dict


class VpnStatusEvent(_VpnEvent):
    type: Literal["vpn.status"] = "vpn.status"


class VpnRunEvent(_VpnEvent):
    type: Literal["vpn.run"] = "vpn.run"


class VpnMfaRequiredEvent(_VpnEvent):
    type: Literal["vpn.mfa_required"] = "vpn.mfa_required"


class VpnSubscribedData(StrictModel):
    last_seq: int = Field(ge=0)


class VpnSubscribedEvent(StrictModel):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["vpn"] = "vpn"
    type: Literal["vpn.subscribed"] = "vpn.subscribed"
    data: VpnSubscribedData


class VpnCredentialConfiguredData(StrictModel):
    kind: Literal["vpn_password", "vpn_totp_secret"]
    configured: bool


class VpnCredentialConfigured(StrictModel):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["vpn"] = "vpn"
    type: Literal["vpn.credentials"] = "vpn.credentials"
    data: VpnCredentialConfiguredData
