"""发布配置迁移、固定命令、授权与既有执行链路的回归。"""

import asyncio
import copy
import json
import uuid

import httpx
import pytest

from tests.test_s4a_boundaries import message
from tests.test_s4b_execution import execution, latest
from toolbox_backend.adapters.config_store import ConfigStore
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import (
    Config,
    DynamicTask,
    config_v6_to_v7,
    config_v7_to_v8,
    task_label,
)
from toolbox_backend.services.tasks import execution_fields


def legacy_task(ident, repo, branch="main", **extra):
    return DynamicTask(
        id=ident,
        repo_id=repo,
        repo_name=repo,
        project_id="proj:test",
        local_repo_path=f"/tmp/{repo}",
        git_flow={"build_branch": branch},
        tg_command=ident.replace(":", "_"),
        tg_desc=f"运行 {ident}",
        targets=[
            {
                "build_kind": "build",
                "build_id": "11",
                "release_id": "21",
                "release_stage_ids": ["1"],
                "name": "生产",
            }
        ],
        **extra,
    ).model_dump()


def old_config(items):
    raw = Config().model_dump(by_alias=True)
    raw["schema_version"] = 6
    raw["tasks"] = {"items": items, "legacy_flows": []}
    return raw


def test_migration_equivalent_eight_tasks_grouping_ids_and_dedup():
    names = [
        "CG_Vue_Event",
        "CG_Vue_Event",
        "CG_Vue_Front",
        "CG_Vue_Front",
        "CG",
        "CG",
        "CG_Vue_Vip_H5",
        "CG_Vue_Vip_H5_DCR",
    ]
    items = [
        legacy_task(
            f"task:{i}", repo, "develop" if i == 3 else "main", sort_order=i, enabled=i != 5
        )
        for i, repo in enumerate(names)
    ]
    items[1]["targets"][0]["name"] = "别名"
    items[0]["targets"].append({**items[0]["targets"][0], "build_id": "12", "enabled": False})
    items[4]["targets"].append({**items[4]["targets"][0], "build_id": "13"})
    original = old_config(items)
    frozen = copy.deepcopy(original)
    migrated = config_v6_to_v7(original)
    assert original == frozen
    assert config_v6_to_v7(migrated) == migrated
    assert config_v6_to_v7(original) == migrated
    assert len(migrated["tasks"]["release_configs"]) == 6
    config = Config.model_validate(config_v7_to_v8(migrated))
    assert len(config.tasks.release_configs) == 5
    front = next(c for c in config.tasks.release_configs if c.name == "CG_Vue_Front")
    assert {b.build_branch for b in front.branches} == {"main", "develop"}
    assert len(front.commands) == 2
    assert {c.name: len(c.commands) for c in config.tasks.release_configs} == {
        "CG_Vue_Event": 2,
        "CG_Vue_Front": 2,
        "CG": 2,
        "CG_Vue_Vip_H5": 1,
        "CG_Vue_Vip_H5_DCR": 1,
    }
    event = next(c for c in config.tasks.release_configs if c.name == "CG_Vue_Event")
    assert len(event.targets) == 2
    assert event.commands[0].target_ids == event.commands[1].target_ids
    for old in items:
        parent = next(
            c for c in config.tasks.release_configs if any(m.id == old["id"] for m in c.commands)
        )
        command = next(m for m in parent.commands if m.id == old["id"])
        for field in ("id", "tg_command", "tg_desc", "enabled", "sort_order"):
            assert getattr(command, field) == old[field]
        assert command.name == old["tg_desc"]
        assert len(command.target_ids) == sum(t["enabled"] for t in old["targets"])
        assert set(parent.expand(command).model_dump()) == set(DynamicTask.model_fields)
    assert "items" not in migrated["tasks"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "proj:other"),
        ("repo_id", "other"),
        ("local_repo_path", "/tmp/other"),
        ("agent_queue_id", "2"),
        ("git_flow", {"build_branch": "main", "update_branches": ["develop"]}),
        ("git_flow", {"build_branch": "main", "future": "preserved"}),
    ],
)
def test_migration_all_source_fields_participate(field, value):
    first, second = legacy_task("a", "repo"), legacy_task("b", "repo")
    second[field] = value
    assert len(config_v6_to_v7(old_config([first, second]))["tasks"]["release_configs"]) == 2


async def test_store_backup_idempotency_and_failed_migration_preserves_original(tmp_path):
    path = tmp_path / "config.json"
    original = json.dumps(old_config([legacy_task("task:a", "repo")])).encode()
    path.write_bytes(original)
    store = ConfigStore(tmp_path)
    migrated = await store.initialize()
    assert migrated.schema_version == 8 and migrated.revision == 1
    backups = list((tmp_path / "migrations").glob("config-v6-*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert await store.initialize() == migrated
    assert len(list((tmp_path / "migrations").glob("config-v6-*.json"))) == 1
    path.write_bytes(original)
    store = ConfigStore(tmp_path)

    def fail(_):
        raise OSError("模拟替换前失败")

    store.checkpoint = fail
    with pytest.raises(SettingsError):
        await store.initialize()
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".config-*"))


async def revision(client):
    return (await client.get("/api/release-configs")).json()["revision"]


@pytest.mark.parametrize("legacy,create", [(False, False), (False, True), (True, False), (True, True)])
async def test_branch_write_normalizes_flow_and_handles_blank_by_api(tmp_path, legacy, create):
    async with execution(tmp_path) as (app, _, _, _):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer s4b-local-test"},
        ) as client:
            parent = (await client.get("/api/release-configs")).json()["items"][0]
            base = "/api/tasks" if legacy else "/api/release-configs"
            ident = parent["commands"][0]["id"] if legacy else parent["id"]
            url = base if create else base + "/" + ident

            async def write(flow):
                body = {"revision": await revision(client)}
                if create:
                    body["name"] = "规范化测试"
                if legacy:
                    body["git_flow"] = flow
                else:
                    item = {} if create else {"id": parent["branches"][0]["id"]}
                    body["branches"] = [{**item, **flow}]
                return await client.request("POST" if create else "PATCH", url, json=body)

            for name in ("", " \t\n "):
                before = await revision(client)
                response = await write({"build_branch": name})
                if legacy:
                    assert response.status_code == 200, response.text
                    saved_id = response.json()["id"] if create else ident
                    saved = (await client.get(base + "/" + saved_id)).json()["item"]
                    assert saved["git_flow"]["build_branch"] == ""
                    assert await revision(client) == before + 1
                    continue
                assert response.status_code == 422, response.text
                assert response.json()["detail"] == {
                    "code": "validation_error",
                    "message": "构建分支名不能为空",
                }
                assert await revision(client) == before

            response = await write(
                {
                    "build_branch": " main \t",
                    "update_branches": [" develop ", "", " \t", " main\n"],
                    "push_branches": ["\tmain ", "\n", "", " develop "],
                    "merges": [{"source": " main ", "target": "\tdevelop\n"}],
                }
            )
            assert response.status_code == 200, response.text
            saved_id = response.json()["id"] if create else ident
            saved = (await client.get(base + "/" + saved_id)).json()["item"]
            flow = saved["git_flow"] if legacy else saved["branches"][0]
            assert flow["build_branch"] == "main"
            assert flow["update_branches"] == ["develop", "main"]
            assert flow["push_branches"] == ["main", "develop"]
            assert flow["merges"] == [{"source": "main", "target": "develop"}]


@pytest.mark.parametrize("create", [False, True])
async def test_branch_write_rejects_duplicates_after_trimming(tmp_path, create):
    async with execution(tmp_path) as (app, _, _, _):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer s4b-local-test"},
        ) as client:
            parent = (await client.get("/api/release-configs")).json()["items"][0]
            url = "/api/release-configs" + ("" if create else "/" + parent["id"])
            original = {} if create else {"id": parent["branches"][0]["id"]}
            before = await revision(client)
            body = {
                "revision": before,
                "name": "唯一性测试",
                "branches": [
                    {**original, "build_branch": "main "},
                    {"build_branch": " main"},
                ],
            }
            response = await client.request("POST" if create else "PATCH", url, json=body)
            assert response.status_code == 422, response.text
            assert response.json()["detail"]["code"] == "validation_error"
            assert await revision(client) == before
            # 保留大小写敏感语义。
            body["branches"][1]["build_branch"] = " Main "
            response = await client.request("POST" if create else "PATCH", url, json=body)
            assert response.status_code == 200, response.text
            cid = response.json()["id"]
            saved = (await client.get("/api/release-configs/" + cid)).json()["item"]
            assert [b["build_branch"] for b in saved["branches"]] == ["main", "Main"]


async def test_branch_migration_and_reads_preserve_whitespace(tmp_path):
    tasks = [legacy_task("a", "repo", "main"), legacy_task("b", "repo", "main ")]
    tasks[1]["git_flow"].update(
        update_branches=[" develop ", ""],
        push_branches=[" main ", "\t"],
        merges=[{"source": " main ", "target": " develop "}],
    )
    raw = config_v6_to_v7(old_config(tasks))
    frozen = copy.deepcopy(raw)
    migrated = config_v7_to_v8(raw)
    assert raw == frozen
    flows = [b for c in migrated["tasks"]["release_configs"] for b in c["branches"]]
    assert [{k: v for k, v in b.items() if k != "id"} for b in flows] == [
        t["git_flow"] for t in tasks
    ]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    store = ConfigStore(tmp_path)
    initialized = await store.initialize()
    persisted = path.read_bytes()
    assert await store.read() == initialized
    assert path.read_bytes() == persisted
    assert [b.model_dump() for b in initialized.tasks.release_configs[0].branches] == flows


async def test_release_api_selection_snapshot_acl_tg_and_protected_delete(tmp_path):
    async with execution(tmp_path) as (app, tg, fake, _):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer s4b-local-test"},
        ) as client:
            listed = (await client.get("/api/release-configs")).json()
            parent = listed["items"][0]
            cid = parent["id"]
            url = f"/api/release-configs/{cid}"
            response = await client.patch(
                url, json={"revision": listed["revision"], "name": "节庆活动"}
            )
            assert response.status_code == 200, response.text
            original = parent["targets"][0]
            added = {k: v for k, v in original.items() if k != "id"}
            added.update(build_id="12", release_id="12", name="第二目标")
            response = await client.patch(
                url, json={"revision": await revision(client), "targets": [original, added]}
            )
            assert response.status_code == 200, response.text
            parent = (await client.get(url)).json()["item"]
            tids = [t["id"] for t in parent["targets"]]
            response = await client.post(
                url + "/commands",
                json={
                    "revision": await revision(client),
                    "name": "完整发布",
                    "tg_command": "both",
                    "tg_desc": "所有环境",
                    "target_ids": tids[::-1],
                    "branch_id": parent["branches"][0]["id"],
                },
            )
            assert response.status_code == 200, response.text
            mid = response.json()["id"]
            response = await client.patch(
                "/api/tasks/task:test",
                json={
                    "revision": await revision(client),
                    "name": "不能从旧表单改共享来源",
                },
            )
            assert response.status_code == 422
            config = await app.state.config_store.read()
            assert tg.dispatcher.allowed(
                config, message(1, 6002), "sync_build_release", "task:test"
            )
            assert not tg.dispatcher.allowed(config, message(1, 6002), "sync_build_release", mid)
            await tg.process_updates([message(1, 6002, text="/deploy")])
            assert "节庆活动：deploy" in latest(app)[0]
            await tg.process_updates([message(2, 6002, text="/both")])
            assert fake.writes == []
            assert task_label(config, mid) == "节庆活动：完整发布"
            response = await client.post(
                f"/api/tasks/{mid}/preflight",
                json={
                    "revision": await revision(client),
                    "operation": "sync_build_release",
                },
            )
            assert response.status_code == 200, response.text
            plan = response.json()
            bad = await client.post(
                f"/api/tasks/{mid}/runs",
                json={
                    "plan_id": plan["plan_id"],
                    "request_id": str(uuid.uuid4()),
                    "ack_old_app_idle": True,
                    "target_ids": [tids[0]],
                },
            )
            assert bad.status_code == 422
            response = await client.post(
                f"/api/tasks/{mid}/runs",
                json={
                    "plan_id": plan["plan_id"],
                    "request_id": str(uuid.uuid4()),
                    "ack_old_app_idle": True,
                },
            )
            assert response.status_code == 202, response.text
            rid = response.json()["run_id"]
            run = await app.state.run_store.get(rid)
            snapshot = run["task_snapshot"]
            expanded = next(t for t in config.tasks.items if t.id == mid)
            assert {k: snapshot[k] for k in execution_fields(expanded)} == execution_fields(
                expanded
            )
            assert snapshot["id"] == run["task_id"] == mid
            assert [t["build_id"] for t in snapshot["targets"]] == ["12", "11"]
            assert all("id" not in t for t in snapshot["targets"])
            response = await client.delete(
                url, params={"revision": await revision(client), "detach_acl": True}
            )
            assert (
                response.status_code == 409 and response.json()["detail"]["code"] == "task_active"
            )
            response = await client.delete(
                url + "/commands/" + mid,
                params={
                    "revision": await revision(client),
                    "detach_acl": True,
                },
            )
            assert (
                response.status_code == 409 and response.json()["detail"]["code"] == "task_active"
            )
            await app.state.run_service.cancel(rid)
            for _ in range(200):
                if not app.state.run_store.active_snapshots():
                    break
                await asyncio.sleep(0.01)
            overview = (await client.get(url + "/commands/" + mid)).json()["item"]
            assert overview["last_run"]["run_id"] == rid
            response = await client.delete(
                url + "/commands/task:test",
                params={
                    "revision": await revision(client),
                },
            )
            assert (
                response.status_code == 409
                and response.json()["detail"]["code"] == "task_referenced"
            )
            response = await client.delete(url, params={"revision": await revision(client)})
            assert (
                response.status_code == 409
                and response.json()["detail"]["code"] == "task_referenced"
            )
            response = await client.delete(
                url, params={"revision": await revision(client), "detach_acl": True}
            )
            assert response.status_code == 200, response.text
            assert (await client.get("/api/tasks")).json()["items"] == []
            config = await app.state.config_store.read()
            assert all("task:test" not in g.task_ids for g in config.telegram.acl_groups)


async def test_release_command_crud_validation_order_revision_and_auth(tmp_path):
    async with execution(tmp_path) as (app, _, _, _):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer s4b-local-test"},
        ) as client:
            body = {
                "revision": await revision(client),
                "name": "新配置",
                "project_id": "proj:test",
                "repo_id": "new-repo",
                "branches": [{"build_branch": "develop"}],
                "targets": [{"build_kind": "build", "build_id": "22"}],
            }
            denied = await client.post(
                "/api/release-configs", json=body, headers={"Authorization": "Bearer invalid"}
            )
            assert denied.status_code == 401
            response = await client.post("/api/release-configs", json=body)
            assert response.status_code == 200, response.text
            cid = response.json()["id"]
            url = f"/api/release-configs/{cid}"
            parent = (await client.get(url)).json()["item"]
            tid = parent["targets"][0]["id"]
            assert parent["name"] == "新配置" and parent["commands"] == []
            stale = await client.patch(url, json={"revision": 0, "name": "过期"})
            assert stale.status_code == 409
            for selected in ([], [tid, tid], ["foreign"]):
                response = await client.post(
                    url + "/commands",
                    json={
                        "revision": await revision(client),
                        "name": "拒绝",
                        "target_ids": selected,
                        "branch_id": parent["branches"][0]["id"],
                    },
                )
                assert response.status_code == 422, response.text
            mids = []
            for name in ("A", "B"):
                response = await client.post(
                    url + "/commands",
                    json={
                        "revision": await revision(client),
                        "name": name,
                        "target_ids": [tid],
                        "branch_id": parent["branches"][0]["id"],
                        "tg_command": "command_" + name.lower(),
                    },
                )
                assert response.status_code == 200, response.text
                mids.append(response.json()["id"])
            response = await client.patch(
                url + "/commands/" + mids[1],
                json={
                    "revision": await revision(client),
                    "tg_command": "deploy",
                },
            )
            assert response.status_code == 422
            response = await client.patch(
                url + "/commands/" + mids[0],
                json={
                    "revision": await revision(client),
                    "name": "改名",
                    "enabled": False,
                },
            )
            assert response.status_code == 200
            single = (await client.get(url + "/commands/" + mids[0])).json()["item"]
            assert single["name"] == "改名" and single["enabled"] is False
            assert single["last_run"] is None and single["active_run_id"] is None
            response = await client.patch(
                url, json={"revision": await revision(client), "targets": []}
            )
            assert response.status_code == 422
            response = await client.patch(
                url, json={"revision": await revision(client), "targets": None}
            )
            assert response.status_code == 422
            response = await client.put(
                url + "/commands/order",
                json={
                    "revision": await revision(client),
                    "ids": mids[::-1],
                },
            )
            assert response.status_code == 200
            assert [m["id"] for m in (await client.get(url + "/commands")).json()["items"]] == mids[
                ::-1
            ]
            ids = [c["id"] for c in (await client.get("/api/release-configs")).json()["items"]]
            response = await client.put(
                "/api/release-configs/order",
                json={
                    "revision": await revision(client),
                    "ids": ids[::-1],
                },
            )
            assert response.status_code == 200
            assert [
                c["id"] for c in (await client.get("/api/release-configs")).json()["items"]
            ] == ids[::-1]
            response = await client.delete(
                url + "/commands/" + mids[0], params={"revision": await revision(client)}
            )
            assert response.status_code == 200
            assert (await client.get(url + "/commands/" + mids[0])).status_code == 404
            response = await client.delete(url, params={"revision": await revision(client)})
            assert response.status_code == 200
            assert (await client.get(url)).status_code == 404


def test_migration_empty_selection_and_target_identity_fields():
    first = legacy_task("a", "repo")
    first["tg_desc"] = ""
    first["targets"][0]["enabled"] = False
    second = legacy_task("b", "repo")
    for field, value in (
        ("build_kind", "pipeline"),
        ("build_id", "12"),
        ("release_id", "22"),
        ("release_stage_ids", ["2"]),
    ):
        second["targets"].append({**second["targets"][0], field: value})
    migrated = Config.model_validate(config_v7_to_v8(config_v6_to_v7(old_config([first, second]))))
    parent = migrated.tasks.release_configs[0]
    assert len(parent.targets) == 5
    assert parent.commands[0].target_ids == []
    assert parent.commands[0].name == "a"
    assert len(parent.commands[1].target_ids) == 5


def test_empty_release_config_still_protects_import_and_ado_source():
    from toolbox_backend.domain.settings import ReleaseConfig
    from toolbox_backend.services.settings import SettingsService, allowed

    config = Config()
    config.tasks.release_configs = [
        ReleaseConfig(id="release:empty", name="空配置", project_id="proj:test")
    ]
    assert config.tasks.items == []
    with pytest.raises(SettingsError) as exc:
        allowed(config)
    assert exc.value.code == "import_not_allowed"
    with pytest.raises(SettingsError) as exc:
        SettingsService._in_use(config, {"proj:test"})
    assert exc.value.code == "in_use" and exc.value.extra["tasks"] == ["空配置"]


def test_migration_repository_identity_adds_branch_even_if_display_name_changed():
    first = legacy_task("a", "repo", "main")
    second = legacy_task("b", "repo", "develop")
    second["repo_name"] = "仓库新名称"
    configs = config_v6_to_v7(old_config([first, second]))["tasks"]["release_configs"]
    assert [c["name"] for c in configs] == ["repo（main）", "仓库新名称（develop）"]


def test_v7_to_v8_merge_flow_dedup_names_command_identity_and_extensions():
    tasks = [legacy_task("a", "repo"), legacy_task("b", "repo", "develop")]
    raw = config_v6_to_v7(old_config(tasks))
    configs = raw["tasks"]["release_configs"]
    configs[0]["sort_order"], configs[1]["sort_order"] = 2, 1
    configs[1]["name"] = "自定义名称"
    configs[1]["git_flow"]["future"] = {"strategy": "保留"}
    configs[1]["git_flow"]["merges"] = [{"source": "main", "target": "develop", "future": 3}]
    duplicate = copy.deepcopy(configs[1])
    duplicate["id"] = "release:duplicate"
    duplicate["sort_order"] = 3
    duplicate["targets"][0]["id"] = "target:duplicate"
    duplicate["commands"][0].update(id="c", target_ids=["target:duplicate"], future="命令扩展")
    configs.append(duplicate)
    frozen = copy.deepcopy(raw)
    result = config_v7_to_v8(raw)
    assert raw == frozen
    reordered = copy.deepcopy(raw)
    reordered["tasks"]["release_configs"].reverse()
    assert config_v7_to_v8(reordered) == result
    assert config_v7_to_v8(raw) == result == config_v7_to_v8(result)
    config = Config.model_validate(result)
    assert len(config.tasks.release_configs) == 1
    parent = config.tasks.release_configs[0]
    assert parent.id == configs[1]["id"] and parent.name == "自定义名称"
    assert len(parent.branches) == 2 and len(parent.targets) == 1
    commands = {m.id: m for m in parent.commands}
    assert commands["b"].branch_id == commands["c"].branch_id != commands["a"].branch_id
    for old in configs:
        for command in old["commands"]:
            current = commands[command["id"]].model_dump(exclude={"branch_id", "target_ids"})
            assert current == {k: v for k, v in command.items() if k != "target_ids"}
            expanded = parent.expand(commands[command["id"]]).model_dump()
            assert expanded["git_flow"] == old["git_flow"]
            assert "branches" not in expanded and "branch_id" not in expanded
            assert "id" not in expanded["targets"][0]
    assert commands["a"].target_ids == commands["b"].target_ids == commands["c"].target_ids


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "proj:other"),
        ("repo_id", "other"),
        ("local_repo_path", "/tmp/other"),
        ("agent_queue_id", "2"),
    ],
)
def test_v8_shared_source_identity_prevents_merge(field, value):
    raw = config_v6_to_v7(old_config([legacy_task("a", "repo"), legacy_task("b", "repo", "dev")]))
    raw["tasks"]["release_configs"][1][field] = value
    assert len(config_v7_to_v8(raw)["tasks"]["release_configs"]) == 2


async def test_v7_store_backup_atomic_failure_and_idempotency(tmp_path):
    raw = config_v6_to_v7(old_config([legacy_task("a", "repo"), legacy_task("b", "repo", "dev")]))
    path = tmp_path / "config.json"
    original = json.dumps(raw).encode()
    path.write_bytes(original)
    store = ConfigStore(tmp_path)
    store.checkpoint = lambda _: (_ for _ in ()).throw(OSError("替换前失败"))
    with pytest.raises(SettingsError):
        await store.initialize()
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".config-*"))
    backups = list((tmp_path / "migrations").glob("config-v7-*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    store = ConfigStore(tmp_path)
    result = await store.initialize()
    assert result.schema_version == 8 and result.revision == raw["revision"] + 1
    backup_count = len(list((tmp_path / "migrations").glob("config-v7-*.json")))
    assert await store.initialize() == result
    assert len(list((tmp_path / "migrations").glob("config-v7-*.json"))) == backup_count
    assert len(result.tasks.release_configs) == 1


async def test_branch_catalog_selection_reference_errors_and_legacy_write(tmp_path):
    async with execution(tmp_path) as (app, _, _, _):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": "Bearer s4b-local-test"},
        ) as client:
            parent = (await client.get("/api/release-configs")).json()["items"][0]
            url = "/api/release-configs/" + parent["id"]
            original = {**parent["branches"][0], "build_branch": "develop"}
            branches = [
                original,
                {
                    "build_branch": "main",
                    "update_branches": ["main"],
                    "merges": [{"source": "main", "target": "develop", "future": "merge"}],
                    "push_branches": ["develop"],
                    "future": {"strategy": "保留"},
                },
            ]
            response = await client.patch(
                url, json={"revision": await revision(client), "branches": branches}
            )
            assert response.status_code == 200, response.text
            parent = (await client.get(url)).json()["item"]
            branch = parent["branches"][1]
            mid = parent["commands"][0]["id"]
            command_url = url + "/commands/" + mid
            for selected in (None, "branch:foreign"):
                response = await client.patch(
                    command_url, json={"revision": await revision(client), "branch_id": selected}
                )
                assert response.status_code == 422
            response = await client.patch(
                command_url, json={"revision": await revision(client), "branch_id": branch["id"]}
            )
            assert response.status_code == 200, response.text
            task = (await client.get("/api/tasks/" + mid)).json()["item"]
            assert task["git_flow"] == {k: v for k, v in branch.items() if k != "id"}
            assert "branches" not in task and "branch_id" not in task
            response = await client.post(
                f"/api/tasks/{mid}/preflight",
                json={
                    "revision": await revision(client),
                    "operation": "deploy_only",
                },
            )
            assert response.status_code == 200, response.text
            response = await client.post(
                f"/api/tasks/{mid}/runs",
                json={
                    "plan_id": response.json()["plan_id"],
                    "request_id": str(uuid.uuid4()),
                    "ack_old_app_idle": True,
                },
            )
            assert response.status_code == 202, response.text
            rid = response.json()["run_id"]
            snapshot = (await app.state.run_store.get(rid))["task_snapshot"]
            assert (
                snapshot["git_flow"]
                == execution_fields(DynamicTask.model_validate(task))["git_flow"]
            )
            assert "branch_id" not in snapshot and "branches" not in snapshot
            await app.state.run_service.cancel(rid)
            for _ in range(200):
                if not app.state.run_store.active_snapshots():
                    break
                await asyncio.sleep(0.01)
            for field, value, code, message in (
                ("branches", [original], "branch_in_use", "分支仍被运行命令引用"),
                ("targets", [], "target_in_use", "目标仍被运行命令引用"),
            ):
                before = await revision(client)
                response = await client.patch(url, json={"revision": before, field: value})
                assert response.status_code == 422
                assert response.json()["detail"] == {"code": code, "message": message}
                assert await revision(client) == before
            for value in (
                [original, {"build_branch": original["build_branch"]}],
                [original, {"id": "branch:foreign", "build_branch": "x"}],
                None,
            ):
                response = await client.patch(
                    url, json={"revision": await revision(client), "branches": value}
                )
                assert response.status_code == 422
            response = await client.patch(
                "/api/tasks/" + mid,
                json={"revision": await revision(client), "git_flow": {"build_branch": "other"}},
            )
            assert response.status_code == 422
            # 删除未引用分支后，旧接口可编辑唯一分支；扩展字段继续保留。
            response = await client.patch(
                url, json={"revision": await revision(client), "branches": [branch]}
            )
            assert response.status_code == 200
            response = await client.patch(
                "/api/tasks/" + mid,
                json={"revision": await revision(client), "git_flow": {"build_branch": "other"}},
            )
            assert response.status_code == 200, response.text
            task = (await client.get("/api/tasks/" + mid)).json()["item"]
            assert task["git_flow"]["build_branch"] == "other"
            assert task["git_flow"]["future"] == branch["future"]
            assert task["git_flow"]["merges"][0]["future"] == "merge"
