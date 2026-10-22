import asyncio
import os
import time

from toolbox_backend import __version__
from toolbox_backend.domain.models import (
    AlertState,
    HeartbeatData,
    HelloData,
    SystemAlertEvent,
    SystemHeartbeatEvent,
    SystemHelloEvent,
    utcnow,
)
from toolbox_backend.services.events import EventHub


class SystemService:
    def __init__(self, hub: EventHub) -> None:
        self.hub = hub
        self.pid = os.getpid()
        self._started = time.monotonic()
        self._alert = AlertState(active=False, reason=None, changed_at=utcnow())

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self._started

    @property
    def alert(self) -> AlertState:
        return self._alert

    def set_alert(self, active: bool, reason: str | None) -> AlertState:
        self._alert = AlertState(active=active, reason=reason, changed_at=utcnow())
        self.hub.publish(SystemAlertEvent, self._alert)
        return self._alert

    def hello_json(self, seq: int) -> str:
        data = HelloData(pid=self.pid, version=__version__, alert=self._alert)
        return SystemHelloEvent(seq=seq, ts=utcnow(), data=data).model_dump_json()

    async def heartbeat_loop(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            self.hub.publish(SystemHeartbeatEvent, HeartbeatData(uptime_s=self.uptime_s))
