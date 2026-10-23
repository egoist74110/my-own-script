"""Approved S3-B read extensions: directional pagination and batched last_run."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import DynamicTask
from toolbox_backend.settings import Settings


@pytest.fixture
async def reads(tmp_path):
    app = create_app(
        Settings(
            token="read-extension-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
    )
    await app.state.config_store.initialize()
    await app.state.run_store.initialize()
    await app.state.config_store.update(
        0,
        lambda c: setattr(
            c.tasks,
            "items",
            [
                DynamicTask(id="task:a", name="a"),
                DynamicTask(id="task:b", name="b"),
                DynamicTask(id="task:empty", name="empty"),
            ],
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer read-extension-token"},
    ) as client:
        try:
            yield app, client
        finally:
            await app.state.run_service.close()


async def add_run(
    app,
    task="task:a",
    status="failed",
    created="2026-10-23T00:00:00+00:00",
    operation="sync_build_release",
):
    store = app.state.run_store
    run = await store.create(
        task_id=task,
        operation=operation,
        request_id=str(uuid.uuid4()),
        request_hash="hash",
        config_revision=1,
        snapshot={"id": task},
        resources=[],
        steps=[],
        deadline_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    if status != "queued":
        run = await store.transition(run["run_id"], run["state_version"], "running")
        if status != "running":
            run = await store.transition(run["run_id"], run["state_version"], status)
    await store.call(
        lambda: store._db.execute(
            "UPDATE runs SET created_at=? WHERE run_id=?", (created, run["run_id"])
        )
    )
    return await store.get(run["run_id"])


@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_order_pagination_ties_filters_and_default_compatibility(reads, order):
    app, client = reads
    rows = [
        await add_run(app),
        await add_run(app),
        await add_run(app, created="2026-10-24T00:00:00+00:00"),
    ]
    await add_run(app, task="task:b", created="2026-10-25T00:00:00+00:00")
    await add_run(app, task="task:a", status="running", created="2026-10-26T00:00:00+00:00")
    expected = sorted(rows, key=lambda r: (r["created_at"], r["run_id"]), reverse=order == "desc")
    seen, cursor = [], None
    for _ in range(3):
        params = {"task_id": "task:a", "status": "failed", "limit": 1, "order": order}
        if cursor:
            params["cursor"] = cursor
        response = await client.get("/api/runs", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        seen.extend(r["run_id"] for r in page["items"])
        cursor = page["cursor"]
    assert cursor is None
    assert seen == [r["run_id"] for r in expected]
    if order == "asc":
        implicit = await client.get(
            "/api/runs", params={"task_id": "task:a", "status": "failed", "limit": 1}
        )
        explicit = await client.get(
            "/api/runs",
            params={"task_id": "task:a", "status": "failed", "limit": 1, "order": "asc"},
        )
        assert implicit.json() == explicit.json()
        assert len(json.loads(implicit.json()["cursor"])) == 2


@pytest.mark.parametrize("original,other", [("asc", "desc"), ("desc", "asc")])
async def test_cursor_cannot_cross_directions(reads, original, other):
    app, client = reads
    await add_run(app)
    await add_run(app)
    first = (await client.get("/api/runs", params={"order": original, "limit": 1})).json()
    response = await client.get("/api/runs", params={"order": other, "cursor": first["cursor"]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"


async def test_invalid_order_is_rejected(reads):
    _, client = reads
    response = await client.get("/api/runs", params={"order": "drop table runs"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"


async def test_last_run_none_completed_and_active_is_batched(reads):
    app, client = reads
    await add_run(app, created="2026-10-22T00:00:00+00:00")
    older_b = await add_run(app, task="task:b", operation="deploy_only")
    latest_a = await add_run(
        app, status="running", created="2026-10-24T00:00:00+00:00", operation="rollback"
    )
    statements = []
    app.state.run_store._db.set_trace_callback(statements.append)
    try:
        response = await client.get("/api/tasks")
    finally:
        app.state.run_store._db.set_trace_callback(None)
    assert response.status_code == 200
    rows = {t["id"]: t for t in response.json()["items"]}
    assert rows["task:empty"]["last_run"] is None
    for task, run in (("task:a", latest_a), ("task:b", older_b)):
        expected = {
            key: run[key] for key in ("run_id", "status", "operation", "created_at", "finished_at")
        }
        assert rows[task]["last_run"] == expected
        single = await client.get(f"/api/tasks/{task}")
        assert single.json()["item"]["last_run"] == expected
    assert rows["task:a"]["active_run_id"] == latest_a["run_id"]
    assert rows["task:a"]["last_run"]["finished_at"] is None
    selects = [s for s in statements if s.lstrip().upper().startswith(("SELECT", "WITH"))]
    assert len(selects) == 1, selects


async def test_last_run_tie_uses_run_id_and_not_finish_time(reads):
    app, client = reads
    rows = [await add_run(app), await add_run(app)]
    expected = max(rows, key=lambda r: (r["created_at"], r["run_id"]))
    response = await client.get("/api/tasks/task:a")
    assert response.json()["item"]["last_run"]["run_id"] == expected["run_id"]


@pytest.mark.parametrize("fault", ["readonly", "closed", "sqlite_error"])
async def test_unavailable_run_store_degrades_task_reads(reads, fault):
    app, client = reads
    await add_run(app)
    store = app.state.run_store
    if fault == "readonly":
        store.readonly_error = "injected readonly"
    elif fault == "closed":
        await store.close()
    else:
        await store.call(lambda: store._db.execute("ALTER TABLE runs RENAME TO unavailable_runs"))
    for url in ("/api/tasks", "/api/tasks/task:a"):
        response = await client.get(url)
        assert response.status_code == 200, response.text
        rows = response.json().get("items", [response.json().get("item")])
        assert all(row["last_run"] is None for row in rows)
        assert all(any("运行库不可用" in w for w in row["warnings"]) for row in rows)


async def test_new_read_fields_preserve_bearer_boundary(reads):
    _, client = reads
    for url in ("/api/runs?order=desc", "/api/tasks", "/api/tasks/task:a"):
        response = await client.get(url, headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 401
