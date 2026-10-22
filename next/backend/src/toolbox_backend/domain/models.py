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


Event = Annotated[
    SystemHelloEvent | SystemHeartbeatEvent | SystemAlertEvent | SettingsChangedEvent,
    Field(discriminator="type"),
]
