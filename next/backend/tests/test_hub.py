"""EventHub unit tests: seq, atomic hello, bounded queue overflow isolation."""

import asyncio

from toolbox_backend.domain.models import AlertState, SystemAlertEvent, utcnow
from toolbox_backend.services.events import EventHub


def alert():
    return AlertState(active=True, reason=None, changed_at=utcnow())


async def test_seq_monotonic_and_hello_aligned():
    hub = EventHub()
    assert hub.publish(SystemAlertEvent, alert()) == 1
    sub = hub.subscribe(hello=lambda seq: f"hello@{seq}")
    assert sub.queue.get_nowait() == "hello@1"
    assert hub.publish(SystemAlertEvent, alert()) == 2
    assert '"seq":2' in sub.queue.get_nowait()


async def test_overflow_drops_only_slow_subscriber():
    hub = EventHub(queue_size=256)
    slow = hub.subscribe()
    fast = hub.subscribe()
    for _ in range(256):
        hub.publish(SystemAlertEvent, alert())
        fast.queue.get_nowait()
    assert not slow.overflowed.is_set()
    hub.publish(SystemAlertEvent, alert())  # 257th for slow: overflow
    assert slow.overflowed.is_set()
    assert not fast.overflowed.is_set()
    assert hub.subscriber_count == 1
    assert fast.queue.qsize() == 1
    hub.publish(SystemAlertEvent, alert())
    assert fast.queue.qsize() == 2
    await asyncio.sleep(0)
