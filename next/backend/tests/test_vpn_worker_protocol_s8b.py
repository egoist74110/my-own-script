"""The child worker's control reader and lifecycle, entirely with a fake BrowserDriver."""

import asyncio
import json

import pytest

from toolbox_backend.vpn import login_worker as worker


class Driver:
    def __init__(self, options, emit):
        self.options, self.closed = options, False
        self.started = asyncio.Event()
        self.steps = []
        self.hang = False

    async def start(self):
        self.started.set()
        if self.hang:
            await asyncio.Event().wait()

    async def step(self, name, values):
        self.steps.append(name)

    async def outcome(self, name):
        return "mfa" if name == "credentials" else "callback"

    async def callback(self):
        return "s8probe://callback#id_token=S8_FAKE_TOKEN"

    async def close(self):
        self.closed = True


def startup(tmp_path, **extra):
    return dict(
        data_dir=str(tmp_path),
        scheme="s8probe",
        app_path="/fake/client.app",
        password="S8_FAKE_PASSWORD",
        timeout_s=2,
        **extra,
    )


async def test_child_protocol_roundtrip_is_bounded_and_secret_free(tmp_path, monkeypatch):
    reader = asyncio.StreamReader()
    reader.feed_data((json.dumps(startup(tmp_path)) + "\n").encode())
    drivers, events, deliveries = [], [], []

    def factory(options, emit):
        driver = Driver(options, emit)
        drivers.append(driver)
        return driver

    def emit(kind, **fields):
        events.append(worker.encode_event(kind, **fields))
        if kind == "need_mfa":
            reader.feed_data(b'{"event":"mfa","code":"918273"}\n')

    async def deliver(url, scheme, app_path, **kwargs):
        deliveries.append((url, scheme, app_path))
        return 6

    monkeypatch.setattr(worker, "deliver_callback", deliver)
    await asyncio.wait_for(worker.run_worker(reader, emit, driver_factory=factory), 1)
    assert drivers[0].closed and drivers[0].steps == [
        "workspace",
        "residency",
        "credentials",
        "mfa",
    ]
    assert json.loads(events[-1]) == {"event": "done"}
    assert len(deliveries) == 1
    for raw in events:
        assert len(raw) <= 65536
        assert all(value not in raw for value in (b"S8_FAKE_PASSWORD", b"S8_FAKE_TOKEN", b"918273"))


@pytest.mark.parametrize("stop", ["eof", "cancel", "oversized_control"])
async def test_child_eof_or_term_equivalent_cancellation_always_closes_driver(tmp_path, stop):
    reader = asyncio.StreamReader(limit=1 << 20)
    reader.feed_data((json.dumps(startup(tmp_path)) + "\n").encode())
    drivers = []

    def factory(options, emit):
        driver = Driver(options, emit)
        driver.hang = True
        drivers.append(driver)
        return driver

    task = asyncio.create_task(
        worker.run_worker(reader, lambda *a, **kw: None, driver_factory=factory)
    )
    await asyncio.sleep(0)
    await drivers[0].started.wait()
    if stop == "eof":
        reader.feed_eof()
    elif stop == "oversized_control":
        reader.feed_data(b"x" * 65537 + b"\n")
    else:
        task.cancel()  # SIGTERM handler in main() calls this same cancellation operation.
    expected = worker.LoginFailure if stop == "oversized_control" else asyncio.CancelledError
    with pytest.raises(expected):
        await asyncio.wait_for(task, 1)
    assert drivers[0].closed


@pytest.mark.parametrize(
    "raw", [b"x" * 65537 + b"\n", b"{}", b'{"entry":"https://forbidden.invalid"}\n']
)
async def test_child_rejects_oversized_unterminated_or_url_supplied_startup(raw):
    reader = asyncio.StreamReader(limit=1 << 20)
    reader.feed_data(raw)
    reader.feed_eof()

    def factory(*args):
        pytest.fail("invalid startup must not create a driver")

    with pytest.raises(worker.LoginFailure):
        await worker.run_worker(reader, lambda *a, **kw: None, driver_factory=factory)
