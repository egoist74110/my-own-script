"""S1-D regressions; only isolated stores and MockTransport."""

import asyncio
import logging
import threading

import httpx
import pytest

from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.api.settings_schemas import TestRequest as ConnectionRequest
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import Library
from toolbox_backend.logging_setup import contains_secret, register_secret

from .test_s1_settings import PAT, PAT2, create_library, execute, preview, revision
from .test_s1_settings import context as context
from .test_s1_settings import (
    test_preview_is_zero_write_then_import_keeps_rules_and_secrets_private as check_import_artifacts,
)


async def test_cr001_connection_releases_store_lock_before_http(context):
    app, client, _, _, _, _ = context
    lid = await create_library(client, pat=PAT)
    entered, release = threading.Event(), threading.Event()

    def handler(request):
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json={"value": []})

    app.state.settings_service.http = AdoHTTP(httpx.MockTransport(handler))
    task = asyncio.create_task(
        app.state.settings_service.connection(lid, ConnectionRequest(collection="Default"))
    )
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.wait_for(
            app.state.config_store.update(
                await revision(client), lambda c: setattr(c.ado.libraries[0], "name", "Renamed")
            ),
            0.3,
        )
    finally:
        release.set()
        await task


async def test_cr001_in_process_lock_wait_is_bounded(context):
    app, _, _, _, _, _ = context
    store = app.state.config_store
    store.lock_timeout_s = 0.02
    await store._lock.acquire()
    try:
        with pytest.raises(SettingsError, match="存储忙"):
            await asyncio.wait_for(store.update(0, lambda c: None), 0.3)
    finally:
        store._lock.release()


async def test_cr001_execute_reads_old_credentials_outside_store_lock(context, monkeypatch):
    app, client, _, old, _, _ = context
    fingerprint = (await preview(client))["fingerprint"]
    get = old.get

    def unlocked_get(key):
        assert not app.state.config_store._lock.locked(), "legacy get holds store lock"
        return get(key)

    monkeypatch.setattr(old, "get", unlocked_get)
    response = await client.post("/api/settings/import/execute", json={"fingerprint": fingerprint})
    assert response.status_code == 200


def test_cr001_response_total_deadline(monkeypatch):
    from toolbox_backend.adapters import ado_http

    ticks = iter([0, 11, 11, 11, 11])
    monkeypatch.setattr(
        ado_http,
        "time",
        type("Clock", (), {"monotonic": staticmethod(lambda: next(ticks))}),
        raising=False,
    )
    result, _ = AdoHTTP(
        httpx.MockTransport(lambda _: httpx.Response(200, json={"value": []}))
    ).projects(Library(id="lib:test", name="Test", base_url="https://ado.test/tfs"), "Default", PAT)
    assert result.category == "timeout"


async def test_cr002_failed_import_orphans_visible_and_decline_after_new_library(
    context, monkeypatch
):
    app, client, new, _, _, _ = context
    monkeypatch.setattr(
        app.state.settings_service, "_snapshot", lambda _: (_ for _ in ()).throw(OSError())
    )
    assert (await execute(client)).status_code == 409
    statuses = (await client.get("/api/credentials")).json()
    assert any(s["account"] == "ado_pat:lib:sample" and s["state"] == "orphan" for s in statuses)
    lid = await create_library(client)
    response = await client.post("/api/settings/import/decline")
    assert response.status_code == 200
    config = await app.state.config_store.read()
    assert [lib.id for lib in config.ado.libraries] == [lid]
    assert config.import_.state == "declined" and new.values == {}


async def test_cr003_short_pat_rejected_without_poisoning_redactor(context):
    _, client, _, _, _, _ = context
    lid = await create_library(client)
    response = await client.put(
        f"/api/ado/libraries/{lid}/pat", json={"revision": await revision(client), "pat": "short7!"}
    )
    assert response.status_code == 422
    register_secret("short7!")
    assert not contains_secret("short7!")


async def test_cr004_dot_segments_rejected_before_http(context):
    _, client, _, _, _, requests = context
    lid = await create_library(client, pat=PAT)
    for segment in (".", ".."):
        response = await client.post(f"/api/ado/libraries/{lid}/test", json={"collection": segment})
        assert response.status_code == 422
    assert requests == []


def test_cr004_adapter_rejects_normalized_path_escape():
    requests = []
    adapter = AdoHTTP(
        httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json={"value": []})
        )
    )
    result, _ = adapter.projects(
        Library(id="lib:test", name="Test", base_url="https://ado.test/tfs"), "..", PAT
    )
    assert result.category == "network" and result.message == "请求地址越界"
    assert requests == []


async def test_cr005_create_keychain_failure_rolls_back_library(context):
    app, client, new, _, _, _ = context
    new.fail = "set"
    response = await client.post(
        "/api/ado/libraries",
        json={"revision": 0, "name": "Main", "base_url": "https://ado.test", "pat": PAT},
    )
    assert response.status_code == 502
    config = await app.state.config_store.read()
    assert config.ado.libraries == [] and config.credentials == {}


async def test_cr005_put_failure_keeps_metadata_unchanged(context):
    app, client, new, _, _, _ = context
    lid = await create_library(client, pat=PAT)
    before = await app.state.config_store.read()
    new.fail = "set"
    response = await client.put(
        f"/api/ado/libraries/{lid}/pat", json={"revision": before.revision, "pat": PAT2}
    )
    assert response.status_code == 502
    assert await app.state.config_store.read() == before


async def test_cr005_patch_commit_failure_restores_old_pat(context, monkeypatch):
    app, client, new, _, _, _ = context
    lid = await create_library(client, pat=PAT)
    before = await app.state.config_store.read()
    monkeypatch.setattr(
        app.state.config_store,
        "_write",
        lambda _: (_ for _ in ()).throw(SettingsError("store_unavailable", "injected", 503)),
    )
    response = await client.patch(
        f"/api/ado/libraries/{lid}",
        json={"revision": before.revision, "base_url": "https://new.test", "pat": PAT2},
    )
    assert response.status_code == 503
    assert new.values["ado_pat:" + lid] == PAT
    assert await app.state.config_store.read() == before


async def test_cr006_raw_log_assertion_detects_injected_leak(context, caplog):
    # Mutation check: the real artifact assertion must catch an unredacted record.
    logging.getLogger("s1d.synthetic").error("synthetic leak %s", PAT)
    with pytest.raises(AssertionError):
        await check_import_artifacts(context, caplog)


async def test_cr002_orphan_can_be_deleted_without_reappearing(context, monkeypatch):
    app, client, new, _, _, _ = context
    monkeypatch.setattr(
        app.state.settings_service, "_snapshot", lambda _: (_ for _ in ()).throw(OSError())
    )
    assert (await execute(client)).status_code == 409
    key = "ado_pat:lib:sample"
    response = await client.delete(
        "/api/credentials/" + key, params={"revision": await revision(client)}
    )
    assert response.status_code == 200
    assert key not in new.values
    assert not any(s["account"] == key for s in (await client.get("/api/credentials")).json())


@pytest.mark.parametrize("delete_fails", [False, True])
async def test_cr005_patch_restore_failure_marks_pending_delete(context, monkeypatch, delete_fails):
    app, client, new, _, _, _ = context
    lid = await create_library(client, pat=PAT)
    before = await app.state.config_store.read()
    original_write, original_set = app.state.config_store._write, new.set
    calls = 0

    def fail_once(config):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SettingsError("store_unavailable", "injected", 503)
        original_write(config)

    def fail_restore(key, value):
        if value == PAT:
            raise RuntimeError("injected restore failure")
        original_set(key, value)

    monkeypatch.setattr(app.state.config_store, "_write", fail_once)
    monkeypatch.setattr(new, "set", fail_restore)
    if delete_fails:
        new.fail = "delete"
    response = await client.patch(
        f"/api/ado/libraries/{lid}",
        json={"revision": before.revision, "base_url": "https://new.test", "pat": PAT2},
    )
    assert response.status_code == (502 if delete_fails else 503)
    config = await app.state.config_store.read()
    assert config.ado == before.ado
    assert config.credentials["ado_pat:" + lid].state == "pending_delete"
    if not delete_fails:
        assert "ado_pat:" + lid not in new.values


def test_cr001_stream_checks_total_deadline_and_closes(monkeypatch):
    from toolbox_backend.adapters import ado_http

    now = [0]

    class SlowStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b" " * 65536
            now[0] = 11
            yield b'{"value":[]}'

        def close(self):
            self.closed = True

    stream = SlowStream()
    monkeypatch.setattr(ado_http.time, "monotonic", lambda: now[0])
    result, _ = AdoHTTP(httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))).projects(
        Library(id="lib:test", name="Test", base_url="https://ado.test/tfs"), "Default", PAT
    )
    assert result.category == "timeout" and stream.closed


async def test_cr005_create_registers_pat_before_first_config_commit(context):
    app, client, new, _, _, _ = context
    candidate = "S1D_FAKE_UNIQUE_CREDENTIAL_491ad2"
    response = await client.post(
        "/api/ado/libraries",
        json={
            "revision": 0,
            "name": candidate,
            "base_url": "https://ado.test",
            "pat": candidate,
        },
    )
    assert response.status_code == 422
    assert not app.state.config_store.path.exists()
    assert new.values == {}
