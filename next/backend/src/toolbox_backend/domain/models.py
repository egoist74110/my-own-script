"""Pure data models shared by HTTP responses and WebSocket events."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


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
    payload: dict


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


Event = Annotated[
    SystemHelloEvent
    | SystemHeartbeatEvent
    | SystemAlertEvent
    | SettingsChangedEvent
    | RunEvent
    | RunSubscribedEvent,
    Field(discriminator="type"),
]
