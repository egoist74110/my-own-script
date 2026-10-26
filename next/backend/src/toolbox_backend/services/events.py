"""In-process event hub: process-wide monotonic seq, bounded per-subscriber queues."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace

from pydantic import BaseModel

from toolbox_backend.domain.models import RunEvent, RunEventData, utcnow


class SubscriberQueue(asyncio.Queue):
    def __init__(self, maxsize):
        super().__init__(maxsize=maxsize)
        self.space = asyncio.Event()

    def get_nowait(self):
        item = super().get_nowait()
        self.space.set()
        return item


class Subscriber:
    def __init__(self, maxsize: int) -> None:
        self.queue = SubscriberQueue(maxsize)
        # Set when the queue overflowed; the connection handler must then close with 4408.
        self.overflowed = asyncio.Event()
        self.ai: dict[str, int] = {}
        self.ai_replaying: dict[str, list[dict]] = {}
        self.runs: dict[str, int] = {}
        self.replaying: dict[str, list[dict]] = {}
        self.mcp_after: int | None = None
        self.mcp_replaying: list[SimpleNamespace] | None = None
        self.mcp_unsubscribed: bool = False
        self.services_after = None
        self.services_replaying = None
        self.services_unsubscribed = False


class EventHub:
    def __init__(self, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._seq = 0
        self._subscribers: set[Subscriber] = set()
        self._mcp_seq = 0
        self._mcp_history: list[SimpleNamespace] = []
        self._services_seq = 0
        self._services_history = []

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event_cls: type[BaseModel], data: BaseModel) -> int:
        """Build, serialize and fan out one event. Never blocks; slow subscribers are dropped."""
        self._seq = seq = self._seq + 1
        payload = event_cls(seq=seq, ts=utcnow(), data=data).model_dump_json()
        self._fan_out(payload)
        return seq

    def enqueue(self, sub, event_cls, data):
        self._seq += 1
        payload = event_cls(seq=self._seq, ts=utcnow(), data=data).model_dump_json()
        try:
            sub.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._subscribers.discard(sub)
            sub.overflowed.set()

    def publish_run(self, event):
        rid, seq = event["run_id"], event["run_seq"]
        for sub in tuple(self._subscribers):
            if rid not in sub.runs or seq <= sub.runs[rid]:
                continue
            if rid in sub.replaying:
                pending = sub.replaying[rid]
                if len(pending) >= self._queue_size:
                    sub.overflowed.set()
                    self._subscribers.discard(sub)
                else:
                    pending.append(event)
            else:
                sub.runs[rid] = seq
                self.enqueue(sub, RunEvent, RunEventData(**event))

    def publish_ai(self, event):
        from toolbox_backend.api.ai_schemas import AIEvent, AIEventData

        sid, seq = event["session_id"], event["session_seq"]
        for sub in tuple(self._subscribers):
            if sid not in sub.ai or seq <= sub.ai[sid]:
                continue
            if sid in sub.ai_replaying:
                pending = sub.ai_replaying[sid]
                if len(pending) >= 256:
                    sub.overflowed.set()
                    self._subscribers.discard(sub)
                else:
                    pending.append(event)
            else:
                sub.ai[sid] = seq
                self.enqueue(sub, AIEvent, AIEventData(**event))

    def publish_mcp(self, event_cls: type[BaseModel], data: BaseModel) -> int:
        self._mcp_seq += 1
        mcp_seq = self._mcp_seq
        ev_type = event_cls.model_fields["type"].default
        entry = SimpleNamespace(
            mcp_seq=mcp_seq,
            event=ev_type,
            event_cls=event_cls,
            data=data,
        )
        self._mcp_history.append(entry)
        if len(self._mcp_history) > 1024:
            self._mcp_history = self._mcp_history[-1024:]
        for sub in tuple(self._subscribers):
            if sub.mcp_after is None or sub.mcp_unsubscribed or mcp_seq <= sub.mcp_after:
                continue
            if sub.mcp_replaying is not None:
                if len(sub.mcp_replaying) >= self._queue_size:
                    sub.overflowed.set()
                    self._subscribers.discard(sub)
                else:
                    sub.mcp_replaying.append(entry)
            else:
                sub.mcp_after = mcp_seq
                self.enqueue(sub, event_cls, data)
        return mcp_seq

    def publish_services(self, event_cls, data):
        self._services_seq += 1
        entry = SimpleNamespace(services_seq=self._services_seq, event_cls=event_cls, data=data)
        self._services_history.append(entry)
        self._services_history = self._services_history[-1024:]
        for sub in tuple(self._subscribers):
            if (
                sub.services_after is None
                or sub.services_unsubscribed
                or entry.services_seq <= sub.services_after
            ):
                continue
            if sub.services_replaying is not None:
                if len(sub.services_replaying) >= self._queue_size:
                    sub.overflowed.set()
                    self._subscribers.discard(sub)
                else:
                    sub.services_replaying.append(entry)
            else:
                sub.services_after = entry.services_seq
                self.enqueue(sub, event_cls, data)
        return self._services_seq

    def _state(self, topic: str) -> SimpleNamespace:
        if topic == "services":
            return SimpleNamespace(
                history=list(self._services_history), last_seq=self._services_seq
            )
        if topic == "mcp":
            return SimpleNamespace(history=list(self._mcp_history), last_seq=self._mcp_seq)
        return SimpleNamespace(history=[], last_seq=0)

    def _fan_out(self, payload: str) -> None:
        for sub in tuple(self._subscribers):
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._subscribers.discard(sub)
                sub.overflowed.set()

    def subscribe(self, hello: Callable[[int], str] | None = None) -> Subscriber:
        """Register a subscriber. ``hello(seq)`` is queued first, atomically with registration
        (no await in between), so every later event has seq greater than the hello's seq."""
        sub = Subscriber(self._queue_size)
        if hello is not None:
            sub.queue.put_nowait(hello(self._seq))
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)
