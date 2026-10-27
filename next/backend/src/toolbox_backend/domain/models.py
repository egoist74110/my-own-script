"""Pure data models shared by HTTP responses and WebSocket events."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from toolbox_backend.domain.task_execution import CheckpointPayload, LogPayload, StatePayload


def utcnow() -> datetime:
    return datetime.now(UTC)


class AlertState(BaseModel):
    active: bool
    reason: str | None = None
    changed_at: datetime


class HelloData(BaseModel):
    pid: int
    version: str
    alert: AlertState


class HeartbeatData(BaseModel):
    uptime_s: float


class _Envelope(BaseModel):
    seq: int = Field(ge=0)
    topic: Literal["system"] = "system"
    ts: datetime


class SystemHelloEvent(_Envelope):
    type: Literal["system.hello"] = "system.hello"
    data: HelloData


class SystemHeartbeatEvent(_Envelope):
    type: Literal["system.heartbeat"] = "system.heartbeat"
    data: HeartbeatData


class SystemAlertEvent(_Envelope):
    type: Literal["system.alert"] = "system.alert"
    data: AlertState


class SettingsChangedData(BaseModel):
    revision: int = Field(ge=1)


class SettingsChangedEvent(_Envelope):
    topic: Literal["settings"] = "settings"
    type: Literal["settings.changed"] = "settings.changed"
    data: SettingsChangedData


class RunEventData(BaseModel):
    run_id: str
    run_seq: int = Field(ge=1)
    type: Literal["state", "log", "checkpoint"]
    payload: StatePayload | LogPayload | CheckpointPayload


class RunEvent(BaseModel):
    seq: int = Field(ge=0)
    topic: Literal["run"] = "run"
    ts: datetime
    type: Literal["run.event"] = "run.event"
    data: RunEventData


class RunSubscribedData(BaseModel):
    run_id: str
    last_seq: int = Field(ge=0)


class RunSubscribedEvent(BaseModel):
    seq: int = Field(ge=0)
    topic: Literal["run"] = "run"
    ts: datetime
    type: Literal["run.subscribed"] = "run.subscribed"
    data: RunSubscribedData


from toolbox_backend.api.telegram_schemas import TelegramStatusData  # noqa: E402


class TelegramStatusEvent(_Envelope):
    type: Literal["telegram.status"] = "telegram.status"
    data: TelegramStatusData


from toolbox_backend.api.ai_schemas import (  # noqa: E402
    AIEvent,
    AIJobEvent,
    AISessionEvent,
    AISubscribedEvent,
)
from toolbox_backend.api.mcp_schemas import (  # noqa: E402
    McpJobEvent,
    McpStatusEvent,
    McpSubscribedEvent,
)
from toolbox_backend.api.services_schemas import (  # noqa: E402
    ServicesStatusEvent,
    ServicesSubscribedEvent,
)
from toolbox_backend.api.vpn_schemas import (  # noqa: E402
    VpnCredentialConfigured,
    VpnMfaRequiredEvent,
    VpnRunEvent,
    VpnStatusEvent,
    VpnSubscribedEvent,
)

Event = Annotated[
    SystemHelloEvent
    | SystemHeartbeatEvent
    | SystemAlertEvent
    | SettingsChangedEvent
    | RunEvent
    | RunSubscribedEvent
    | TelegramStatusEvent
    | AIEvent
    | AIJobEvent
    | AISessionEvent
    | AISubscribedEvent
    | McpStatusEvent
    | McpJobEvent
    | McpSubscribedEvent
    | ServicesStatusEvent
    | ServicesSubscribedEvent
    | VpnCredentialConfigured
    | VpnMfaRequiredEvent
    | VpnRunEvent
    | VpnStatusEvent
    | VpnSubscribedEvent,
    Field(discriminator="type"),
]
