"""Every S3-A task and run HTTP entry point stays behind S0 bearer auth."""


async def test_task_and_run_routes_reject_invalid_bearer_before_touching_storage(s3actx):
    requests = [
        ("GET", "/api/tasks", None),
        ("GET", "/api/tasks/task:missing", None),
        ("POST", "/api/tasks", {"revision": 0, "name": "unauthorized"}),
        ("PATCH", "/api/tasks/task:missing", {"revision": 0, "name": "unauthorized"}),
        ("DELETE", "/api/tasks/task:missing?revision=0", None),
        ("PUT", "/api/tasks/order", {"revision": 0, "ids": []}),
        (
            "POST",
            "/api/tasks/task:missing/preflight",
            {"operation": "sync_build_release", "revision": 0},
        ),
        (
            "POST",
            "/api/tasks/task:missing/runs",
            {"plan_id": "untrusted", "request_id": "untrusted", "ack_old_app_idle": True},
        ),
        ("GET", "/api/runs", None),
        ("GET", "/api/runs/00000000-0000-0000-0000-000000000000", None),
        ("POST", "/api/runs/00000000-0000-0000-0000-000000000000/cancel", None),
        ("GET", "/api/runs/00000000-0000-0000-0000-000000000000/events", None),
        ("POST", "/api/runs/00000000-0000-0000-0000-000000000000/reconcile", None),
    ]

    for method, path, body in requests:
        response = await s3actx.client.request(
            method,
            path,
            json=body,
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401, (method, path, response.status_code, response.text)

    assert not s3actx.data_dir.exists()


async def test_start_is_rejected_as_unsupported_until_s3b_executor_exists(s3actx):
    response = await s3actx.client.post(
        "/api/tasks/task:unsupported/runs",
        json={
            "plan_id": "00000000-0000-4000-8000-000000000001",
            "request_id": "00000000-0000-4000-8000-000000000002",
            "ack_old_app_idle": True,
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "unsupported_task"
    assert not (s3actx.data_dir / "runs.sqlite3").exists()
