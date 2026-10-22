"""Independent S3-A task configuration contracts."""


async def test_patch_preserves_unknown_fields_on_an_existing_task(s3actx):
    task_id = "task:legacy-preserved"
    revision = await s3actx.seed_task(
        task_id,
        name="S3A task",
        enabled=True,
        future_extension={"owner": "legacy", "flags": ["keep-me"]},
    )

    listed = await s3actx.client.get("/api/tasks")
    assert listed.status_code == 200, listed.text
    assert listed.json()["revision"] == revision
    item = next(task for task in listed.json()["items"] if task["id"] == task_id)
    assert item["future_extension"] == {"owner": "legacy", "flags": ["keep-me"]}

    updated = await s3actx.client.patch(
        f"/api/tasks/{task_id}",
        json={"revision": revision, "name": "Renamed task"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == revision + 1

    fetched = await s3actx.client.get(f"/api/tasks/{task_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["revision"] == revision + 1
    assert fetched.json()["item"]["name"] == "Renamed task"
    assert fetched.json()["item"]["future_extension"] == {
        "owner": "legacy",
        "flags": ["keep-me"],
    }


async def test_task_create_rejects_unrecognized_execution_fields(s3actx):
    response = await s3actx.create_task(
        name="Task with unexpected parameter",
        arbitrary_command=["sh", "-c", "echo unsafe"],
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "validation_error"


async def test_stale_task_revision_is_rejected_without_overwriting_newer_state(s3actx):
    created = await s3actx.create_task(name="First")
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]
    stale_revision = created.json()["revision"] - 1

    response = await s3actx.client.patch(
        f"/api/tasks/{task_id}", json={"revision": stale_revision, "name": "Stale edit"}
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "revision_conflict"
    fetched = await s3actx.client.get(f"/api/tasks/{task_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["item"]["name"] == "First"
    assert fetched.json()["revision"] == created.json()["revision"]


async def test_delete_is_blocked_while_imported_acl_group_references_task(s3actx):
    created = await s3actx.create_task(name="ACL referenced")
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]
    revision = created.json()["revision"]

    def add_acl_reference(config):
        config.imported.telegram["acl_groups"] = [
            {"name": "Release operators", "task_ids": [task_id]}
        ]

    await s3actx.app.state.config_store.update(revision, add_acl_reference)
    current_revision = await s3actx.revision()
    deleted = await s3actx.client.delete(
        f"/api/tasks/{task_id}", params={"revision": current_revision}
    )

    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["detail"]["code"] == "task_referenced"
    assert "Release operators" in deleted.text
    still_present = await s3actx.client.get(f"/api/tasks/{task_id}")
    assert still_present.status_code == 200, still_present.text
    assert still_present.json()["item"]["id"] == task_id


async def test_task_order_requires_exact_unique_ids_and_commits_atomically(s3actx):
    revision = await s3actx.seed_task("task:order-a", name="A", sort_order=0)
    revision = await s3actx.seed_task("task:order-b", name="B", sort_order=1)
    revision = await s3actx.seed_task("task:order-c", name="C", sort_order=2)
    requested = ["task:order-c", "task:order-a", "task:order-b"]

    invalid = await s3actx.client.put(
        "/api/tasks/order", json={"revision": revision, "ids": [requested[0], requested[0]]}
    )
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["detail"]["code"] == "validation_error"
    unchanged = await s3actx.client.get("/api/tasks")
    assert unchanged.json()["revision"] == revision
    assert [item["id"] for item in unchanged.json()["items"]] == [
        "task:order-a",
        "task:order-b",
        "task:order-c",
    ]

    ordered = await s3actx.client.put(
        "/api/tasks/order", json={"revision": revision, "ids": requested}
    )
    assert ordered.status_code == 200, ordered.text
    assert ordered.json()["revision"] == revision + 1
    final = await s3actx.client.get("/api/tasks")
    assert [item["id"] for item in final.json()["items"]] == requested
    assert [item["sort_order"] for item in final.json()["items"]] == [0, 1, 2]


async def test_repeated_telegram_command_is_rejected_without_adding_second_task(s3actx):
    first = await s3actx.create_task(name="First", tg_command="deploy_prod")
    assert first.status_code == 200, first.text

    duplicate = await s3actx.create_task(name="Second", tg_command="deploy_prod")

    assert duplicate.status_code == 422, duplicate.text
    assert duplicate.json()["detail"]["code"] == "validation_error"
    tasks = await s3actx.client.get("/api/tasks")
    assert len(tasks.json()["items"]) == 1
    assert tasks.json()["items"][0]["name"] == "First"


async def test_deleting_last_task_never_recreates_it_from_legacy_flows(s3actx):
    task_id = "task:legacy-flow-retained"
    revision = await s3actx.seed_task(task_id, name="Migrated task")
    legacy_flows = [{"id": "legacy-flow-1", "name": "Old flow"}]

    def retain_legacy_flows(config):
        config.tasks.legacy_flows = legacy_flows

    await s3actx.app.state.config_store.update(revision, retain_legacy_flows)
    current_revision = await s3actx.revision()
    deleted = await s3actx.client.delete(
        f"/api/tasks/{task_id}", params={"revision": current_revision}
    )
    assert deleted.status_code == 200, deleted.text

    empty = await s3actx.client.get("/api/tasks")
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []
    persisted = await s3actx.app.state.config_store.read()
    assert persisted.tasks.legacy_flows == legacy_flows
