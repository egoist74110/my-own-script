import hashlib
import json
import logging
import shutil
import stat
from pathlib import Path

import httpx
import pytest

from toolbox_backend.adapters.ado_http import AdoHTTP
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import CredentialMeta, DynamicTask
from toolbox_backend.logging_setup import RedactingFormatter
from toolbox_backend.settings import Settings

PAT = "FAKE_S1_PAT_MUST_NEVER_APPEAR_731cae"
PAT2 = "FAKE_S1_PAT_REPLACEMENT_295abc"
FIXTURES = Path(__file__).parent / "fixtures/legacy"


class FakeCredentials(MemoryCredentials):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail = None
        self.fail_account = None

    def _call(self, method, key):
        self.calls.append((method, key))
        if method == self.fail and (self.fail_account is None or key == self.fail_account):
            raise RuntimeError("backend may echo " + PAT)

    def get(self, key):
        self._call("get", key)
        return super().get(key)

    def set(self, key, value):
        self._call("set", key)
        return super().set(key, value)

    def delete(self, key):
        self._call("delete", key)
        return super().delete(key)


@pytest.fixture
async def context(tmp_path):
    legacy_dir = tmp_path / "legacy"
    shutil.copytree(FIXTURES, legacy_dir)
    new, old = FakeCredentials(), FakeCredentials()
    old.values["azuredevops_pat:lib:sample"] = PAT
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"value": [{"name": "Project A"}]})

    app = create_app(
        Settings(
            token="test-api-token",
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=legacy_dir,
        ),
        credentials=new,
        legacy_credentials=old,
        ado_http=AdoHTTP(httpx.MockTransport(handler)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer test-api-token"},
    ) as client:
        yield app, client, new, old, legacy_dir, requests


def tree_state(root):
    if not root.exists():
        return None
    return {
        str(p.relative_to(root)): (
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None,
        )
        for p in [root, *root.rglob("*")]
    }


async def preview(client):
    response = await client.post("/api/settings/import/preview")
    assert response.status_code == 200, response.text
    return response.json()


async def execute(client):
    plan = await preview(client)
    assert plan["errors"] == []
    return await client.post(
        "/api/settings/import/execute", json={"fingerprint": plan["fingerprint"]}
    )


async def revision(client):
    response = await client.get("/api/settings")
    return response.json()["revision"]


async def create_library(client, **kwargs):
    response = await client.post(
        "/api/ado/libraries",
        json={
            "revision": await revision(client),
            "name": "Main",
            "base_url": "https://ado.example.test/tfs",
            **kwargs,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_preview_is_zero_write_then_import_keeps_rules_and_secrets_private(context, caplog):
    app, client, new, old, source, _ = context
    before = tree_state(source)
    data = app.state.config_store.data_dir
    assert not data.exists()
    plan = await preview(client)
    assert plan["tasks_rule"] == "migrated_from_flows"
    assert plan["task_count"] == 1
    assert plan["libraries"][0]["pat_status"] == "found"
    assert len(plan["warnings"]) >= 2
    assert not data.exists() and tree_state(source) == before
    assert all(call[0] == "get" for call in old.calls)
    assert new.calls == []
    sub = app.state.hub.subscribe()
    try:
        response = await client.post(
            "/api/settings/import/execute", json={"fingerprint": plan["fingerprint"]}
        )
        assert response.status_code == 200, response.text
        config = await app.state.config_store.read()
        assert config.import_.state == "completed"
        task = config.tasks.items[0]
        assert task.git_flow.build_branch == "main"
        assert task.targets[0].build_id == "42"
        assert config.imported.telegram["acl_groups"][0]["task_ids"] == [task.id]
        assert config.imported.extra["ui_settings"]["unknown_ui_key"] == {"nested": "preserved"}
        assert config.tasks.legacy_flows[0]["id"] == "sync_merge_build_release"
        assert new.values["ado_pat:lib:sample"] == PAT
        assert all(call[0] == "get" for call in old.calls)
        assert tree_state(source) == before
        snapshots = list((data / "import").glob("legacy-*"))
        assert len(snapshots) == 1
        assert {p.name for p in snapshots[0].iterdir()} == {
            "ui_settings.yaml",
            "tasks.yaml",
            "lark_settings.yaml",
            "figma_settings.yaml",
        }
        for path in snapshots[0].iterdir():
            assert path.read_bytes() == (source / path.name).read_bytes()
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        artifacts = [json.dumps(plan), response.text]
        for route in ("/api/settings", "/api/ado", "/api/credentials"):
            artifacts.append((await client.get(route)).text)
        artifacts.extend(p.read_text() for p in data.rglob("*") if p.is_file())
        while not sub.queue.empty():
            event = sub.queue.get_nowait()
            assert json.loads(event)["topic"] == "settings"
            artifacts.append(event)
        formatter = RedactingFormatter([], "%(message)s")
        artifacts.extend(formatter.format(record) for record in caplog.records)
        record = logging.LogRecord("test", logging.ERROR, "", 0, "failure " + PAT, (), None)
        artifacts.append(formatter.format(record))
        assert all(PAT not in artifact for artifact in artifacts)
        again = await client.post(
            "/api/settings/import/execute", json={"fingerprint": plan["fingerprint"]}
        )
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "import_not_allowed"
    finally:
        app.state.hub.unsubscribe(sub)


@pytest.mark.parametrize(
    "raw,rule,count",
    [
        ("tasks: []\nflows: [{id: old}]", "kept_tasks", 0),
        ("{}", "empty", 0),
        (
            "tasks: [{id: task1, custom: kept, git_flow: {update_branches: [main]}}]",
            "kept_tasks",
            1,
        ),
    ],
)
async def test_task_key_presence_normalization_and_unknown_fields(context, raw, rule, count):
    app, client, _, _, source, _ = context
    (source / "tasks.yaml").write_text(raw)
    plan = await preview(client)
    assert plan["errors"] == []
    assert plan["tasks_rule"] == rule and plan["task_count"] == count
    response = await execute(client)
    assert response.status_code == 200
    config = await app.state.config_store.read()
    assert len(config.tasks.items) == count
    if count:
        assert config.tasks.items[0].sort_order == 10
        assert config.tasks.items[0].git_flow.build_branch == "main"
        assert config.tasks.items[0].model_extra == {"custom": "kept"}


@pytest.mark.parametrize(
    "raw", ["tasks: null", "tasks: 42", "tasks: [42]", "flows: null", "flows: [null]", "flows: {}"]
)
async def test_invalid_task_shapes_block_import(context, raw):
    app, client, new, _, source, _ = context
    (source / "tasks.yaml").write_text(raw)
    plan = await preview(client)
    assert plan["errors"]
    response = await client.post(
        "/api/settings/import/execute", json={"fingerprint": plan["fingerprint"]}
    )
    assert response.status_code == 409
    assert not app.state.config_store.data_dir.exists() or not app.state.config_store.path.exists()
    assert new.calls == []


async def test_fingerprint_changes_non_first_import_and_decline(context):
    app, client, new, _, source, _ = context
    plan = await preview(client)
    (source / "figma_settings.yaml").write_text("port: 3334")
    source_before = tree_state(source)
    credentials_before = dict(new.values)
    response = await client.post(
        "/api/settings/import/execute", json={"fingerprint": plan["fingerprint"]}
    )
    assert response.json()["detail"]["code"] == "import_source_changed"
    assert not app.state.config_store.path.exists()
    assert not list(app.state.config_store.data_dir.glob("import/legacy-*"))
    assert new.values == credentials_before and new.calls == []
    assert tree_state(source) == source_before
    # Directory and lock are permitted infrastructure; business data stays untouched.
    assert stat.S_IMODE(app.state.config_store.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((app.state.config_store.data_dir / "config.lock").stat().st_mode) == 0o600
    assert (await client.post("/api/settings/import/decline")).status_code == 200
    assert (await client.post("/api/settings/import/preview")).status_code == 409
    assert (await app.state.config_store.read()).import_.state == "declined"


async def test_nonempty_store_blocks_import(context):
    _, client, _, _, _, _ = context
    await create_library(client)
    response = await client.post("/api/settings/import/preview")
    assert response.json()["detail"]["code"] == "import_not_allowed"


@pytest.mark.parametrize("failure", ["keyring", "snapshot", "final_store"])
async def test_import_failure_residue_and_retry(context, monkeypatch, failure):
    app, client, new, old, source, _ = context
    ui = source / "ui_settings.yaml"
    ui.write_text(ui.read_text() + "\n")
    if failure == "keyring":
        # Two libraries prove an earlier successful set survives a later failure.
        import yaml

        config = yaml.safe_load(ui.read_text())
        config["libraries"].append(
            {"id": "lib:second", "name": "Second", "base_url": "https://second.example.test"}
        )
        ui.write_text(yaml.safe_dump(config))
        old.values["azuredevops_pat:lib:second"] = PAT2
        new.fail, new.fail_account = "set", "ado_pat:lib:second"
    elif failure == "snapshot":
        monkeypatch.setattr(
            app.state.settings_service,
            "_snapshot",
            lambda _: (_ for _ in ()).throw(OSError("snapshot failure")),
        )
    else:

        def fail(stage):
            if stage == "before_replace" and app.state.config_store.path.exists():
                raw = json.loads(app.state.config_store.path.read_text())
                # start + one credential record committed, final commit is next.
                if raw["revision"] == 2:
                    app.state.config_store.checkpoint = lambda _: None
                    raise OSError("final store failure")

        app.state.config_store.checkpoint = fail
    response = await execute(client)
    assert response.status_code == 409, response.text
    config = await app.state.config_store.read()
    assert config.import_.state == "failed"
    assert not config.ado.libraries and not config.tasks.items
    assert config.import_.written_credentials == ["ado_pat:lib:sample"]
    assert new.values["ado_pat:lib:sample"] == PAT
    assert not list(app.state.config_store.data_dir.glob("import/legacy-*"))
    assert PAT not in app.state.config_store.path.read_text() + response.text
    new.fail = None
    monkeypatch.undo()
    response = await execute(client)
    assert response.status_code == 200, response.text
    assert (await app.state.config_store.read()).import_.state == "completed"


async def test_decline_cleans_written_credentials_after_failed_import(context, monkeypatch):
    app, client, new, _, _, _ = context
    monkeypatch.setattr(
        app.state.settings_service, "_snapshot", lambda _: (_ for _ in ()).throw(OSError())
    )
    assert (await execute(client)).status_code == 409
    assert new.values
    assert (await client.post("/api/settings/import/decline")).status_code == 200
    assert new.values == {}
    assert (await app.state.config_store.read()).import_.state == "declined"


@pytest.mark.parametrize("problem", ["large", "symlink", "parse", "bad_id", "plain_secret"])
async def test_unsafe_legacy_sources_are_blocked_without_echo(context, problem, tmp_path):
    _, client, _, _, source, _ = context
    if problem == "large":
        (source / "tasks.yaml").write_bytes(b"x" * ((1 << 20) + 1))
    elif problem == "symlink":
        outside = tmp_path / "outside.yaml"
        outside.write_text("secret: not-read")
        (source / "tasks.yaml").unlink()
        (source / "tasks.yaml").symlink_to(outside)
    elif problem == "parse":
        (source / "tasks.yaml").write_text("[broken yaml")
    elif problem == "bad_id":
        (source / "tasks.yaml").write_text('tasks: [{id: "../../escape"}]')
    else:
        (source / "tasks.yaml").write_text("tasks: []\nunknown_secret: " + PAT)
    plan = await preview(client)
    assert plan["errors"]
    assert PAT not in json.dumps(plan)


async def test_library_project_crud_revision_references_and_pat_origin(context):
    app, client, new, _, _, _ = context
    lid = await create_library(client, pat=PAT)
    assert lid.startswith("lib:")
    response = await client.patch(
        f"/api/ado/libraries/{lid}", json={"revision": 0, "name": "stale"}
    )
    assert response.status_code == 409 and response.json()["detail"]["code"] == "revision_conflict"
    response = await client.patch(
        f"/api/ado/libraries/{lid}",
        json={"revision": await revision(client), "base_url": "https://new.example.test"},
    )
    assert response.json()["detail"]["code"] == "pat_origin_change"
    response = await client.patch(
        f"/api/ado/libraries/{lid}",
        json={
            "revision": await revision(client),
            "base_url": "https://new.example.test",
            "keep_pat": True,
        },
    )
    assert response.status_code == 200
    response = await client.post(
        "/api/ado/projects",
        json={
            "revision": await revision(client),
            "library_id": lid,
            "collection": "Default Collection",
            "project": "Project",
        },
    )
    assert response.status_code == 200, response.text
    pid = response.json()["id"]
    assert pid.startswith("proj:")
    assert (
        await client.put(
            "/api/ado/active",
            json={"revision": await revision(client), "library_id": lid, "project_id": pid},
        )
    ).status_code == 200
    await app.state.config_store.update(
        await revision(client),
        lambda c: c.tasks.items.append(
            DynamicTask(id="task:ref", name="task name", project_id=pid)
        ),
    )
    for path in (f"/api/ado/projects/{pid}", f"/api/ado/libraries/{lid}"):
        response = await client.delete(path, params={"revision": await revision(client)})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "in_use"
        assert response.json()["detail"]["tasks"] == ["task name"]
    await app.state.config_store.update(await revision(client), lambda c: c.tasks.items.clear())
    response = await client.patch(
        f"/api/ado/projects/{pid}", json={"revision": await revision(client), "project": "Updated"}
    )
    assert response.status_code == 200
    response = await client.delete(
        f"/api/ado/libraries/{lid}", params={"revision": await revision(client)}
    )
    assert response.status_code == 200
    config = await app.state.config_store.read()
    assert config.ado.active_library_id is config.ado.active_project_id is None
    assert config.ado.libraries == config.ado.projects == []
    assert new.values == {} and config.credentials == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "file:///etc/passwd"},
        {"base_url": "https://user:pass@host.test"},
        {"base_url": "https://host.test?x=y"},
        {"base_url": "https://host.test#fragment"},
        {"name": " "},
        {"name": "a" * 101},
        {"base_url": "https://host.test\\evil"},
    ],
)
async def test_invalid_libraries_have_safe_422(context, changes):
    _, client, _, _, _, _ = context
    response = await client.post(
        "/api/ado/libraries",
        json={
            "revision": 0,
            "name": "Main",
            "base_url": "https://host.test",
            "pat": PAT,
            **changes,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "validation_error"
    assert PAT not in response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"library_id": "lib:missing"},
        {"collection": "../escape"},
        {"project": "evil\\path"},
        {"project": "evil\nline"},
    ],
)
async def test_invalid_project_reference_and_segments(context, changes):
    _, client, _, _, _, _ = context
    lid = await create_library(client)
    response = await client.post(
        "/api/ado/projects",
        json={
            "revision": await revision(client),
            "library_id": lid,
            "collection": "Default",
            "project": "Project",
            **changes,
        },
    )
    assert response.status_code == 422, response.text


async def test_unique_library_name_and_project_tuple(context):
    _, client, _, _, _, _ = context
    lid = await create_library(client)
    response = await client.post(
        "/api/ado/libraries",
        json={
            "revision": await revision(client),
            "name": " Main ",
            "base_url": "https://other.test",
        },
    )
    assert response.status_code == 422
    body = {"library_id": lid, "collection": "Default", "project": "Same"}
    assert (
        await client.post("/api/ado/projects", json={"revision": await revision(client), **body})
    ).status_code == 200
    assert (
        await client.post("/api/ado/projects", json={"revision": await revision(client), **body})
    ).status_code == 422
    assert (
        await client.post(
            "/api/ado/projects",
            json={"revision": await revision(client), **body, "collection": "Another"},
        )
    ).status_code == 200


async def test_credentials_present_missing_unreadable_orphan_and_pending_retry(context):
    app, client, new, _, _, _ = context
    lid = await create_library(client)
    assert (await client.get("/api/credentials")).json()[0]["state"] == "missing"
    new.values["ado_pat:" + lid] = PAT
    status = (await client.get("/api/credentials")).json()[0]
    assert status["state"] == "present" and status["source"] == "unknown"
    new.fail = "get"
    status = (await client.get("/api/credentials")).json()[0]
    assert status["state"] == "unreadable" and status["present"] is None
    new.fail = None
    assert (
        await client.put(
            f"/api/ado/libraries/{lid}/pat", json={"revision": await revision(client), "pat": PAT}
        )
    ).status_code == 200
    assert (await client.get("/api/credentials")).json()[0]["source"] == "manual"
    new.fail = "delete"
    response = await client.delete(
        f"/api/ado/libraries/{lid}", params={"revision": await revision(client)}
    )
    assert response.status_code == 200 and response.json()["warnings"]
    status = (await client.get("/api/credentials")).json()[0]
    assert status["state"] == "pending_delete"
    new.fail = None
    response = await client.delete(
        "/api/credentials/ado_pat:" + lid, params={"revision": await revision(client)}
    )
    assert response.status_code == 200
    assert (await client.get("/api/credentials")).json() == [] and new.values == {}
    await app.state.config_store.update(
        await revision(client),
        lambda c: c.credentials.update(
            {
                "ado_pat:lib:orphan": CredentialMeta(
                    ref="lib:orphan", source="imported", updated_at="2026-10-22T00:00:00Z"
                )
            }
        ),
    )
    assert (await client.get("/api/credentials")).json()[0]["state"] == "orphan"


@pytest.mark.parametrize("pat", ["", "has space", "line\nbreak", "x" * 1025])
async def test_pat_validation_never_echoes_input(context, pat):
    _, client, _, _, _, _ = context
    lid = await create_library(client)
    response = await client.put(
        f"/api/ado/libraries/{lid}/pat", json={"revision": await revision(client), "pat": pat}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "validation_error", "message": "请求校验失败"}}


async def test_readonly_store_reports_reason_and_rejects_all_writes(context):
    app, client, _, _, _, _ = context
    app.state.config_store.data_dir.mkdir()
    app.state.config_store.path.write_text('{"schema_version": 99}')
    response = await client.get("/api/settings")
    assert response.json()["store_state"] == "readonly_error"
    assert response.json()["store_error"]
    response = await client.post(
        "/api/ado/libraries", json={"revision": 0, "name": "Main", "base_url": "https://ado.test"}
    )
    assert response.status_code == 503 and response.json()["detail"]["code"] == "store_unavailable"


async def test_all_new_routes_require_bearer_before_parsing(context):
    app, client, _, _, _, _ = context
    routes = app.openapi()["paths"]
    for path, operations in routes.items():
        if not path.startswith(("/api/settings", "/api/ado", "/api/credentials")):
            continue
        path = path.replace("{id}", "lib:test").replace("{account}", "ado_pat:lib:test")
        for method in operations:
            response = await client.request(method, path, headers={"Authorization": ""})
            assert response.status_code == 401, (method, path, response.text)


async def test_body_limit_and_cors_methods(context):
    _, client, _, _, _, _ = context
    assert (
        await client.post("/api/settings/import/preview", content=b"x" * 65537)
    ).status_code == 413

    async def stream():
        yield b"x" * 32000
        yield b"x" * 33537
        raise AssertionError("must reject without reading rest")

    assert (await client.post("/api/settings/import/preview", content=stream())).status_code == 413
    response = await client.post(
        "/api/system/alert",
        content=b"[" * 50_000 + b"]" * 50_000,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    health = await client.get("/health")
    assert health.status_code == 200 and health.json()["alert"] is False
    for method in ("PATCH", "DELETE", "PUT"):
        response = await client.options(
            "/api/ado/libraries/lib:test",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "Authorization, Content-Type",
                "Authorization": "",
            },
        )
        assert response.status_code == 200
        assert {m.strip() for m in response.headers["access-control-allow-methods"].split(",")} == {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
        }
    for method in ("TRACE", "CONNECT"):
        response = await client.options(
            "/api/ado",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": method,
            },
        )
        assert response.status_code == 400
    response = await client.options(
        "/api/ado",
        headers={
            "Origin": "https://evil.example.test",
            "Access-Control-Request-Method": "PATCH",
        },
    )
    assert response.status_code == 400
    assert (
        await client.post(
            "/api/settings/import/preview", headers={"Authorization": ""}, content=b"x" * 65537
        )
    ).status_code == 401


async def test_interrupted_import_recovers_without_reading_legacy_credentials(context):
    app, client, new, old, _, _ = context
    new.values["ado_pat:lib:sample"] = PAT

    def interrupted(c):
        c.import_.state = "in_progress"
        c.import_.written_credentials = ["ado_pat:lib:sample"]

    await app.state.config_store.update(0, interrupted)
    async with app.router.lifespan_context(app):
        config = await app.state.config_store.read()
        assert config.import_.state == "failed"
        assert config.import_.written_credentials == ["ado_pat:lib:sample"]
        assert old.calls == []
        assert (await client.post("/api/settings/import/decline")).status_code == 200
    assert new.values == {}


async def test_no_origin_rejected_before_accept_without_network(context):
    from toolbox_backend.api.ws import events

    app, _, _, _, _, _ = context

    class MissingOrigin:
        headers = {}
        closed = None

        async def close(self, code):
            self.closed = code

        async def accept(self):
            raise AssertionError("must reject before accepting")

    ws = MissingOrigin()
    ws.app = app
    await events(ws)
    assert ws.closed == 1008


async def test_backend_errors_do_not_echo_pat_and_remote_failure_not_empty_success(context):
    app, client, new, _, _, _ = context
    lid = await create_library(client)
    new.fail = "set"
    response = await client.put(
        f"/api/ado/libraries/{lid}/pat", json={"revision": await revision(client), "pat": PAT}
    )
    assert (
        response.status_code == 502
        and response.json()["detail"]["code"] == "credential_backend_error"
    )
    assert PAT not in response.text
    new.fail = None
    app.state.settings_service.http = AdoHTTP(httpx.MockTransport(lambda _: httpx.Response(401)))
    new.values["ado_pat:" + lid] = PAT
    response = await client.get(
        f"/api/ado/libraries/{lid}/remote-projects", params={"collection": "Default"}
    )
    assert response.status_code == 502 and response.json()["detail"]["code"] == "ado_request_failed"
    assert response.json()["detail"]["category"] == "unauthorized"
    assert PAT not in response.text


@pytest.mark.parametrize("registered", [True, False])
async def test_startup_migration_registration_or_readonly_error(context, registered):
    from .test_s1_store import synthetic_v0, v0_to_v1

    previous_app, _, new, old, _, _ = context
    directory = previous_app.state.config_store.data_dir
    directory.mkdir()
    original = synthetic_v0(directory)
    app = create_app(
        previous_app.state.settings,
        credentials=new,
        legacy_credentials=old,
        migrations={0: v0_to_v1} if registered else None,
    )
    async with app.router.lifespan_context(app):
        result = await app.state.settings_service.settings()
        assert result.store_state == ("ok" if registered else "readonly_error")
        assert new.calls == old.calls == []
        if registered:
            assert result.revision == 4
            assert next(directory.glob("config.json.bak-v0-*")).read_bytes() == original
        else:
            assert app.state.config_store.path.read_bytes() == original
            response = await app.state.settings_service.settings()
            assert response.store_error


async def test_memory_credentials_require_dev_and_data_dir_override(monkeypatch, tmp_path):
    from toolbox_backend.server import parse_args, serve

    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    monkeypatch.setenv("TOOLBOX_DATA_DIR", str(tmp_path / "env-data"))
    monkeypatch.setenv("TOOLBOX_LEGACY_CONFIG_DIR", str(tmp_path / "env-legacy"))
    settings = Settings(token="local", port=0)
    assert settings.data_dir == tmp_path / "env-data"
    assert settings.legacy_config_dir == tmp_path / "env-legacy"
    args = parse_args(["--data-dir", str(tmp_path / "cli-data"), "--dev"])
    assert args.data_dir == tmp_path / "cli-data" and args.dev
    with pytest.raises(ValueError, match="require --dev"):
        await serve(settings, None)


DEV_FAKE = Path(__file__).parent / "fixtures/dev-credentials.json"


@pytest.mark.parametrize(
    ("dev", "mode"), [(False, "memory"), (True, "keyring"), (False, "keyring")]
)
async def test_dev_fake_credentials_rejected_outside_dev_memory(monkeypatch, dev, mode):
    from toolbox_backend.server import serve

    monkeypatch.setenv("TOOLBOX_CREDENTIALS", mode)
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_CREDENTIALS", str(DEV_FAKE))
    with pytest.raises(ValueError, match="requires --dev and TOOLBOX_CREDENTIALS=memory|require --dev"):
        await serve(Settings(token="local", port=0, dev=dev), None)


def test_dev_fake_credentials_file_validation(tmp_path):
    from toolbox_backend.adapters.credentials import seed_fake_credentials

    bad = tmp_path / "bad.json"
    for content in ("not json", "[]", '{"other": {}}', '{"legacy": {"a": 1}}'):
        bad.write_text(content)
        with pytest.raises(ValueError) as info:
            seed_fake_credentials(bad, legacy=MemoryCredentials(), current=MemoryCredentials())
        assert "fake-pat" not in str(info.value)


async def test_dev_fake_credentials_seed_legacy_pat_state(tmp_path):
    from toolbox_backend.adapters.credentials import seed_fake_credentials

    legacy_dir = tmp_path / "legacy"
    shutil.copytree(FIXTURES, legacy_dir)
    new, old = MemoryCredentials(), MemoryCredentials()
    seed_fake_credentials(DEV_FAKE, legacy=old, current=new)
    assert new.values == {}
    assert old.values["azuredevops_pat:lib:sample"].startswith("fake-pat-")
    app = create_app(
        Settings(token="t", port=1, data_dir=tmp_path / "data", legacy_config_dir=legacy_dir),
        credentials=new,
        legacy_credentials=old,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:1",
        headers={"Authorization": "Bearer t"},
    ) as client:
        plan = (await client.post("/api/settings/import/preview")).json()
        assert [lib["pat_status"] for lib in plan["libraries"] if lib["id"] == "lib:sample"] == ["found"]
        assert "fake-pat-" not in json.dumps(plan)
