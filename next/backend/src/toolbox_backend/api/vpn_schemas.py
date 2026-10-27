"""S8 VPN API and WebSocket DTOs; secret values are never response fields."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from toolbox_backend.domain.settings import StrictModel
from toolbox_backend.domain.vpn import VpnConfig


class VpnClientView(StrictModel):
    installed: bool
    running: bool
    app_name: str | None = None
    version: str | None = None


class VpnSnapshot(StrictModel):
    connected: bool
    ip: str | None
    client: VpnClientView
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


class BrowserProfileCleared(StrictModel):
    cleared: bool


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
    vpn_seq: int = Field(ge=1)


class VpnRunBrief(StrictModel):
    run_id: str
    state: str
    rung: int


class VpnStatusData(StrictModel):
    connected: bool
    ip: str | None = None
    client: VpnClientView | None = None
    current_run: VpnRunBrief | None = None
    vpn_seq: int = Field(ge=1)


class VpnMfaRequiredData(StrictModel):
    run_id: str
    expires_in_s: int = Field(ge=1)
    vpn_seq: int = Field(ge=1)


class _VpnEvent(StrictModel):
    seq: int = Field(ge=0)
    ts: datetime
    topic: Literal["vpn"] = "vpn"


class VpnStatusEvent(_VpnEvent):
    type: Literal["vpn.status"] = "vpn.status"
    data: VpnStatusData


class VpnRunEvent(_VpnEvent):
    type: Literal["vpn.run"] = "vpn.run"
    data: VpnRunEventData


class VpnMfaRequiredEvent(_VpnEvent):
    type: Literal["vpn.mfa_required"] = "vpn.mfa_required"
    data: VpnMfaRequiredData


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
