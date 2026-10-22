"""Executor S2-D regressions, using synthetic traffic and guarded fixtures."""

import asyncio
import threading

import httpx
import pytest

from tests.test_s2_work_items import context as s2_context
from tests.test_s2_work_items import get
from toolbox_backend.domain.settings import LocalRepo
from toolbox_backend.services import work_items

context = s2_context


@pytest.mark.parametrize("key", ["added", "removed"])
async def test_002_numeric_update_relations_are_bad_response(context, key):
    _, client, _, _, state = context
    state["handler"] = lambda _: httpx.Response(
        200, json={"value": [{"id": 1, "relations": {key: 42}}]}
    )
    response = await get(client, "/10/updates")
    assert response.status_code == 502
    assert response.json()["detail"]["category"] == "bad_response"


async def test_i2_repeated_cancel_keeps_worker_permit(monkeypatch):
    gate = asyncio.Semaphore(1)
    monkeypatch.setattr(work_items, 'OUTBOUND', gate)
    started, release, ended = threading.Event(), threading.Event(), threading.Event()

    def worker():
        started.set()
        try:
            assert release.wait(3)
        finally:
            ended.set()

    task = asyncio.create_task(work_items.outbound(worker))
    try:
        for _ in range(1000):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        assert started.is_set()
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not ended.is_set() and gate.locked() and not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.to_thread(ended.wait, 3)
    assert ended.is_set() and not gate.locked()


async def test_i4_duplicate_legacy_name_allows_path_only_patch(context, tmp_path):
    app, client, _, _, _ = context
    await app.state.config_store.update(1, lambda c: c.ado.local_repos.extend([
        LocalRepo(id='repo:one', name='same', path='/old/one'),
        LocalRepo(id='repo:two', name='same', path='/old/two'),
    ]))
    response = await client.patch('/api/ado/local-repos/repo:one', json={'revision': 2, 'path': str(tmp_path)})
    assert response.status_code == 200, response.text
    config = await app.state.config_store.read()
    assert config.ado.local_repos[0].path == str(tmp_path)
    assert config.ado.local_repos[1].path == '/old/two'
    response = await client.patch('/api/ado/local-repos/repo:one', json={'revision': 3, 'name': 'same'})
    assert response.status_code == 422
    assert (await app.state.config_store.read()).revision == 3
