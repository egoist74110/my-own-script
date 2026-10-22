"""S1-E regressions using isolated configuration and transport faults."""

import time

import httpx

from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Library

from .test_s1_settings import PAT, PAT2, create_library
from .test_s1_settings import context as context


async def test_cr007_post_replace_read_failure_keeps_replacement_pat(context, monkeypatch):
    app, client, credentials, _, _, _ = context
    lid = await create_library(client, pat=PAT)
    store = app.state.config_store
    before = await store.read()
    read = store._read
    fail_read = False

    def checkpoint(stage):
        nonlocal fail_read
        if stage == "after_replace":
            fail_read = True
            raise OSError("injected post-replace failure")

    def read_once_fails():
        nonlocal fail_read
        if fail_read:
            fail_read = False
            raise SettingsError("store_unavailable", "injected read failure", 503)
        return read()

    monkeypatch.setattr(store, "checkpoint", checkpoint)
    monkeypatch.setattr(store, "_read", read_once_fails)
    response = await client.patch(
        f"/api/ado/libraries/{lid}",
        json={"revision": before.revision, "base_url": "https://new.test", "pat": PAT2},
    )
    assert response.status_code == 503
    assert (await store.read()).ado.libraries[0].base_url == "https://new.test"
    assert credentials.values["ado_pat:" + lid] == PAT2


def test_cr008_one_byte_slow_drip_times_out_near_total_deadline():
    class SlowDrip(httpx.SyncByteStream):
        closed = False
        chunks = 0

        def __iter__(self):
            for _ in range(42):
                time.sleep(0.5)
                self.chunks += 1
                yield b" "

        def close(self):
            self.closed = True

    stream = SlowDrip()
    started = time.monotonic()
    result, projects = AdoHTTP(
        httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    ).projects(Library(id="lib:test", name="Test", base_url="https://ado.test/tfs"), "Default", PAT)
    elapsed = time.monotonic() - started
    assert result.category == "timeout" and projects == []
    assert stream.closed
    assert elapsed < 11.5, f"deadline checked only after {elapsed:.1f}s / {stream.chunks} bytes"
    assert stream.chunks <= 21
