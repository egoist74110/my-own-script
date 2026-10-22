"""Independent regressions for uncertain library commits and raw ADO chunks."""

import shutil

import httpx
import pytest

from tests.independent.s1.conftest import LEGACY_FIXTURES, S1Context, TrackedCredentials
from toolbox_backend.adapters.ado_http import LIMIT, AdoHTTP
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import Library
from toolbox_backend.settings import Settings

PAT = "FAKE_S1E_REPLACEMENT_PAT_007_008"


@pytest.fixture
async def context(tmp_path):
    source_dir = tmp_path / "legacy"
    shutil.copytree(LEGACY_FIXTURES, source_dir)
    new_credentials = TrackedCredentials()
    old_credentials = TrackedCredentials()

    def response_handler(_request):
        return httpx.Response(200, json={"value": []})

    app = create_app(
        Settings(
            token="isolated-s1e-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=source_dir,
        ),
        credentials=new_credentials,
        legacy_credentials=old_credentials,
        ado_http=AdoHTTP(httpx.MockTransport(response_handler)),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer isolated-s1e-token"},
    )
    context = S1Context(
        app,
        client,
        new_credentials,
        old_credentials,
        source_dir,
        tmp_path / "data",
        [],
    )
    try:
        yield context
    finally:
        await context.close()


async def test_cr007_no_old_pat_is_deleted_when_failed_commit_left_old_origin(context):
    created = await context.create_library()
    assert created.status_code == 200, created.text
    lid = created.json()["id"]
    key = "ado_pat:" + lid
    assert key not in context.new_credentials.values

    store = context.app.state.config_store

    def fail_before_replace(point):
        if point == "before_replace":
            raise OSError("injected pre-replace failure")

    store.checkpoint = fail_before_replace
    response = await context.client.patch(
        f"/api/ado/libraries/{lid}",
        json={
            "revision": await context.revision(),
            "base_url": "https://new.example.test/tfs",
            "pat": PAT,
        },
    )

    assert response.status_code == 503
    assert key not in context.new_credentials.values
    config = await store.read()
    library = next(item for item in config.ado.libraries if item.id == lid)
    assert library.base_url == "https://ado.example.test"


@pytest.mark.parametrize(("failed_reads", "marker_expected"), [(1, True), (None, False)])
async def test_cr007_unreadable_disk_deletes_pat_without_stale_write(
    context, monkeypatch, failed_reads, marker_expected
):
    created = await context.create_library()
    assert created.status_code == 200, created.text
    lid = created.json()["id"]
    key = "ado_pat:" + lid
    store = context.app.state.config_store
    original_read = store._read
    failure_started = False
    fail_once = True
    reads_remaining = failed_reads

    def fail_before_replace(point):
        nonlocal failure_started, fail_once
        if point == "before_replace" and fail_once:
            fail_once = False
            failure_started = True
            raise OSError("injected pre-replace failure")

    def unreadable_after_failure():
        nonlocal reads_remaining
        if failure_started and (reads_remaining is None or reads_remaining > 0):
            if reads_remaining is not None:
                reads_remaining -= 1
            raise OSError("injected unreadable configuration")
        return original_read()

    store.checkpoint = fail_before_replace
    monkeypatch.setattr(store, "_read", unreadable_after_failure)
    response = await context.client.patch(
        f"/api/ado/libraries/{lid}",
        json={
            "revision": await context.revision(),
            "base_url": "https://new.example.test/tfs",
            "pat": PAT,
        },
    )

    assert response.status_code == 503
    assert key not in context.new_credentials.values

    # Read the persisted marker through the original method after the injected outage.
    monkeypatch.setattr(store, "_read", original_read)
    config = await store.read()
    if marker_expected:
        assert config.credentials[key].state == "pending_delete"
    else:
        assert key not in config.credentials
    assert next(item for item in config.ado.libraries if item.id == lid).base_url == (
        "https://ado.example.test"
    )


@pytest.mark.parametrize("disk_state", ["library_removed", "other_base_url"])
async def test_cr007_unexpected_disk_state_deletes_pat_and_preserves_disk_state(context, disk_state):
    created = await context.create_library()
    assert created.status_code == 200, created.text
    lid = created.json()["id"]
    key = "ado_pat:" + lid
    store = context.app.state.config_store
    injected = False

    def fail_after_external_disk_change(point):
        nonlocal injected
        if point != "after_replace" or injected:
            return
        injected = True
        store.checkpoint = lambda _: None
        try:
            changed = store._read()
            library = next(item for item in changed.ado.libraries if item.id == lid)
            if disk_state == "library_removed":
                changed.ado.libraries.remove(library)
            else:
                library.base_url = "https://concurrent.example.test/tfs"
            store._write(changed)
        finally:
            store.checkpoint = fail_after_external_disk_change
        raise OSError("injected post-replace uncertainty")

    store.checkpoint = fail_after_external_disk_change
    response = await context.client.patch(
        f"/api/ado/libraries/{lid}",
        json={
            "revision": await context.revision(),
            "base_url": "https://new.example.test/tfs",
            "pat": PAT,
        },
    )

    assert response.status_code == 503
    assert key not in context.new_credentials.values
    config = await store.read()
    assert config.credentials[key].state == "pending_delete"
    if disk_state == "library_removed":
        assert all(item.id != lid for item in config.ado.libraries)
    else:
        assert next(item for item in config.ado.libraries if item.id == lid).base_url == (
            "https://concurrent.example.test/tfs"
        )


class ChunkedStream(httpx.SyncByteStream):
    def __init__(self, chunk_size: int, total: int):
        self.chunk_size = chunk_size
        self.total = total
        self.bytes_yielded = 0
        self.closed = False

    def __iter__(self):
        while self.bytes_yielded < self.total:
            size = min(self.chunk_size, self.total - self.bytes_yielded)
            self.bytes_yielded += size
            yield b"x" * size

    def close(self):
        self.closed = True


def test_cr008_rejects_small_raw_chunks_promptly_after_limit():
    stream = ChunkedStream(chunk_size=4096, total=LIMIT + 4 * 4096)
    adapter = AdoHTTP(httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))

    result, projects = adapter.projects(
        Library(id="lib:test", name="Test", base_url="https://ado.example.test/tfs"),
        "Default",
        PAT,
    )

    assert result.category == "bad_response"
    assert projects == []
    assert stream.bytes_yielded <= LIMIT + 4096
    assert stream.closed
