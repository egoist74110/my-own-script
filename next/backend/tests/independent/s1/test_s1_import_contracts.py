import pytest


def tree_snapshot(root):
    return {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.iterdir())
        if p.is_file()
    }


async def preview(context):
    response = await context.client.post("/api/settings/import/preview")
    assert response.status_code == 200, response.text
    return response.json()


async def execute(context, fingerprint):
    return await context.client.post(
        "/api/settings/import/execute", json={"fingerprint": fingerprint}
    )


@pytest.mark.parametrize(
    ("raw", "expected_rule", "expected_count", "blocked"),
    [
        ("flows: [{id: old_flow, target_branch: main}]", "migrated_from_flows", 1, False),
        (
            "tasks: [{id: task_a, name: kept}]\nflows: [{id: old_flow}]",
            "kept_tasks",
            1,
            False,
        ),
        ("tasks: []\nflows: [{id: old_flow}]", "kept_tasks", 0, False),
        ("unknown: retained", "empty", 0, False),
        ("tasks: null\nflows: [{id: old_flow}]", "empty", 0, True),
        ("tasks: 17\nflows: [{id: old_flow}]", "empty", 0, True),
    ],
)
async def test_wp13_tasks_flows_shapes_and_acl_flow_mapping(
    s1ctx, raw, expected_rule, expected_count, blocked
):
    tasks_path = s1ctx.source_dir / "tasks.yaml"
    tasks_path.write_text(raw)
    ui_path = s1ctx.source_dir / "ui_settings.yaml"
    ui_path.write_text(
        ui_path.read_text().replace(
            "task_ids: [sync_merge_build_release]", "task_ids: [old_flow]"
        )
    )
    plan = await preview(s1ctx)
    assert plan["tasks_rule"] == expected_rule
    assert plan["task_count"] == expected_count
    assert bool(plan["errors"]) is blocked
    if not blocked:
        result = await execute(s1ctx, plan["fingerprint"])
        assert result.status_code == 200, result.text
        config = await s1ctx.app.state.config_store.read()
        assert len(config.tasks.items) == expected_count
        if expected_rule == "migrated_from_flows":
            task = config.tasks.items[0]
            assert task.legacy_flow_id == "old_flow"
            assert config.imported.telegram["acl_groups"][0]["task_ids"] == [task.id]
            assert config.tasks.legacy_flows[0]["id"] == "old_flow"
        elif raw.startswith("tasks: []"):
            assert config.tasks.items == []
    else:
        result = await execute(s1ctx, plan["fingerprint"])
        assert result.status_code == 409
        assert not s1ctx.app.state.config_store.path.exists()
        assert not s1ctx.new_credentials.values


async def test_import_source_and_old_credential_source_remain_read_only(s1ctx):
    initial = tree_snapshot(s1ctx.source_dir)
    preview_plan = await preview(s1ctx)
    assert tree_snapshot(s1ctx.source_dir) == initial
    assert s1ctx.old_credentials.calls
    assert {method for method, _ in s1ctx.old_credentials.calls} == {"get"}
    response = await execute(s1ctx, preview_plan["fingerprint"])
    assert response.status_code == 200, response.text
    assert tree_snapshot(s1ctx.source_dir) == initial
    assert {method for method, _ in s1ctx.old_credentials.calls} == {"get"}
    assert s1ctx.new_credentials.values["ado_pat:lib:sample"] == "FAKE_S1_LEGACY_PAT_36a"
    snapshots = list((s1ctx.data_dir / "import").glob("legacy-*"))
    assert len(snapshots) == 1
    for name, (content, _) in initial.items():
        assert (snapshots[0] / name).read_bytes() == content
        assert (snapshots[0] / name).stat().st_mode & 0o777 == 0o600


async def test_changed_fingerprint_has_no_business_write_or_snapshot(s1ctx):
    before = tree_snapshot(s1ctx.source_dir)
    plan = await preview(s1ctx)
    path = s1ctx.source_dir / "figma_settings.yaml"
    path.write_text(path.read_text() + "\n")
    changed = tree_snapshot(s1ctx.source_dir)
    response = await execute(s1ctx, plan["fingerprint"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "import_source_changed"
    assert not s1ctx.app.state.config_store.path.exists()
    assert not list(s1ctx.data_dir.glob("import/legacy-*"))
    assert not s1ctx.new_credentials.values
    assert tree_snapshot(s1ctx.source_dir) == changed
    assert before != changed


async def test_import_is_rejected_after_store_has_ado_data(s1ctx):
    created = await s1ctx.create_library()
    assert created.status_code == 200
    response = await s1ctx.client.post("/api/settings/import/preview")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "import_not_allowed"


async def test_credential_write_failure_can_retry_then_completes(s1ctx):
    import yaml

    ui = s1ctx.source_dir / "ui_settings.yaml"
    legacy = yaml.safe_load(ui.read_text())
    legacy["libraries"].append(
        {"id": "lib:second", "name": "Second", "base_url": "https://second.example.test"}
    )
    ui.write_text(yaml.safe_dump(legacy, allow_unicode=True))
    s1ctx.old_credentials.values["azuredevops_pat:lib:second"] = "FAKE_S1_SECOND_PAT_36b"
    s1ctx.new_credentials.fail_set_accounts.add("ado_pat:lib:second")
    plan = await preview(s1ctx)
    failed = await execute(s1ctx, plan["fingerprint"])
    assert failed.status_code == 409
    assert failed.json()["detail"]["code"] == "import_failed"
    config = await s1ctx.app.state.config_store.read()
    assert config.import_.state == "failed"
    assert config.import_.written_credentials == ["ado_pat:lib:sample"]
    assert config.ado.libraries == [] and config.tasks.items == []
    assert s1ctx.new_credentials.values == {
        "ado_pat:lib:sample": "FAKE_S1_LEGACY_PAT_36a"
    }
    retried = await execute(s1ctx, plan["fingerprint"])
    assert retried.status_code == 200, retried.text
    assert (await s1ctx.app.state.config_store.read()).import_.state == "completed"
    assert s1ctx.new_credentials.values == {
        "ado_pat:lib:sample": "FAKE_S1_LEGACY_PAT_36a",
        "ado_pat:lib:second": "FAKE_S1_SECOND_PAT_36b",
    }


async def test_failed_import_decline_deletes_earlier_written_credentials(s1ctx):
    import yaml

    ui = s1ctx.source_dir / "ui_settings.yaml"
    content = yaml.safe_load(ui.read_text())
    content["libraries"].append(
        {"id": "lib:second", "name": "Second", "base_url": "https://second.example.test"}
    )
    ui.write_text(yaml.safe_dump(content, allow_unicode=True))
    s1ctx.old_credentials.values["azuredevops_pat:lib:second"] = "FAKE_S1_SECOND_PAT_36b"
    s1ctx.new_credentials.fail_set_accounts.add("ado_pat:lib:second")
    plan = await preview(s1ctx)
    result = await execute(s1ctx, plan["fingerprint"])
    assert result.status_code == 409
    config = await s1ctx.app.state.config_store.read()
    assert config.import_.state == "failed"
    assert config.ado.libraries == [] and config.tasks.items == []
    assert config.import_.written_credentials == ["ado_pat:lib:sample"]
    assert s1ctx.new_credentials.values == {
        "ado_pat:lib:sample": "FAKE_S1_LEGACY_PAT_36a"
    }
    declined = await s1ctx.client.post("/api/settings/import/decline")
    assert declined.status_code == 200, declined.text
    assert not s1ctx.new_credentials.values
    assert (await s1ctx.app.state.config_store.read()).import_.state == "declined"


async def test_completed_import_is_terminal(s1ctx):
    plan = await preview(s1ctx)
    first = await execute(s1ctx, plan["fingerprint"])
    assert first.status_code == 200, first.text
    second = await execute(s1ctx, plan["fingerprint"])
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "import_not_allowed"


@pytest.mark.parametrize("problem", ["external_symlink", "over_limit"])
async def test_import_blocks_external_symlink_and_file_over_one_mib(s1ctx, tmp_path, problem):
    task_file = s1ctx.source_dir / "tasks.yaml"
    if problem == "external_symlink":
        outside = tmp_path / "outside.yaml"
        outside.write_text("tasks: []")
        task_file.unlink()
        task_file.symlink_to(outside)
    else:
        task_file.write_bytes(b"x" * ((1 << 20) + 1))
    before = task_file.lstat().st_mtime_ns
    plan = await preview(s1ctx)
    assert plan["errors"]
    assert all(method == "get" for method, _ in s1ctx.old_credentials.calls)
    assert not s1ctx.new_credentials.values
    assert task_file.lstat().st_mtime_ns == before
    response = await execute(s1ctx, plan["fingerprint"])
    assert response.status_code == 409
    assert not s1ctx.app.state.config_store.path.exists()
    assert not list(s1ctx.data_dir.glob("import/legacy-*"))
