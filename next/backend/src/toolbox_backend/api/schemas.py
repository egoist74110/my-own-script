from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    pid: int
    uptime_s: float
    alert: bool


class AlertRequest(BaseModel):
    active: bool
    reason: str | None = None
