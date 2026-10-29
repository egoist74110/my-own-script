"""发布发现使用临时 Git、隔离配置与假 ADO。"""

import subprocess

import httpx
import pytest

from tests.test_s4b_execution import execution
from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.services.release_discovery import QUEUE_VERSIONS, parse_remote

PREFIX = "/api/release-configs/discover"


@pytest.mark.parametrize(
    "remote,port",
    [
        ("https://user:secret@ADO.test/c/sample/_git/demo%20repo", None),
        ("https://ADO.test:8443/c/sample/_git/demo%20repo", 8443),
        ("ssh://user@ADO.test:22/c/sample/_git/demo%20repo", 22),
        ("git@ADO.test:v3/c/sample/demo%20repo", None),
    ],
)
def test_remote_forms(remote, port):
    host, actual, collection, project, repo, safe = parse_remote(remote)
    assert (host, actual, collection, project, repo) == (
        "ado.test",
        port,
        "c",
        "sample",
        "demo repo",
    )
    assert not any(s in safe for s in ("user", "secret", "git@"))


def test_default_collection():
    assert parse_remote("https://host/tfs/DefaultCollection/My%20Project/_git/repo")[2:5] == (
        "DefaultCollection",
        "My Project",
        "repo",
    )


@pytest.mark.parametrize(
    "remote", ["https://github.com/org/repo", "file:///tmp/repo", "https://host:bad/c/p/_git/r"]
)
def test_invalid_remote(remote):
    with pytest.raises(SettingsError) as exc:
        parse_remote(remote)
    assert exc.value.code == "remote_not_ado"


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["/usr/bin/git", "init", str(path)], check=True, capture_output=True)
    git(path, "remote", "add", "origin", "https://user:secret@ADO.test/C/SAMPLE/_git/demo")
    return path


def git(path, *args):
    subprocess.run(["/usr/bin/git", "-C", str(path), *args], check=True, capture_output=True)


def handler(calls):
    def transport(request):
        calls.append(request)
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("/refs"):
            assert request.url.params["filter"] == "heads/"
            return httpx.Response(
                200, json={"value": [{"name": "refs/heads/" + n} for n in ["z", "main", "a"]]}
            )
        if "/git/repositories/" in path:
            return httpx.Response(
                200, json={"id": "demo-repo", "name": "demo", "defaultBranch": "refs/heads/main"}
            )
        if path.endswith("/build/definitions"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": i,
                            "name": f"构建{i}",
                            "repository": {"id": rid},
                            "process": {"type": t},
                        }
                        for i, rid, t in [
                            (11, "demo-repo", 2),
                            (12, "demo-repo", 1),
                            (13, "other", 2),
                            (14, "demo-repo", 1),
                        ]
                    ]
                },
            )
        if path.endswith("/release/definitions"):
            if request.url.params["api-version"] == "6.0":
                return httpx.Response(400, json={"typeKey": "UnsupportedApiVersionException"})
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": 21,
                            "name": "生产",
                            "artifacts": [
                                {
                                    "type": "Build",
                                    "definitionReference": {"definition": {"id": str(i)}},
                                }
                                for i in [11, 12]
                            ],
                            "environments": [{"id": 1, "name": "环境"}],
                        },
                        {"id": 22, "name": "无关", "artifacts": []},
                    ]
                },
            )
        if path.endswith("/queues"):
            if request.url.params["api-version"] != QUEUE_VERSIONS[-1]:
                return httpx.Response(400, json={})
            return httpx.Response(200, json={"value": [{"id": 5, "name": "默认"}]})
        raise AssertionError(path)

    return transport


def client(app, authenticated=True):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://127.0.0.1:1234",
        headers={"Authorization": "Bearer s4b-local-test"} if authenticated else {},
    )


async def test_roundtrip_read_only(repo, tmp_path):
    calls = []
    async with execution(tmp_path) as (app, *_):
        app.state.work_items_service.http = AdoRead(httpx.MockTransport(handler(calls)))
        before = await app.state.config_store.read()
        async with client(app) as c:
            r = await c.post(PREFIX + "/repo", json={"local_repo_path": str(repo)})
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["project_id"] == "proj:test" and data["project_label"] == "c/sample"
            assert data["repo_id"] == "demo-repo" and data["suggested_name"] == "demo"
            assert data["existing_config_id"] == before.tasks.release_configs[0].id
            assert "user" not in data["remote_url"] and "secret" not in r.text
            params = {"project_id": "proj:test", "repo_id": "demo-repo"}
            assert (await c.get(PREFIX + "/branches", params=params)).json() == {
                "branches": ["main", "a", "z"],
                "default_branch": "main",
            }
            r = await c.get(PREFIX + "/targets", params=params)
            assert r.status_code == 200, r.text
            data = r.json()
            assert [b["kind"] for b in data["builds"]] == ["pipeline", "build", "build"]
            assert data["releases"][0]["build_definition_ids"] == ["11", "12"]
            assert [t["name"] for t in data["suggested_targets"]] == [
                "生产（构建11）",
                "生产（构建12）",
            ]
            assert data["suggested_targets"][0]["release_stage_ids"] == ["1"]
            assert data["suggested_targets"][0]["release_stage_names"] == ["环境"]
            assert (await c.get(PREFIX + "/queues", params=params)).json() == {
                "queues": [{"id": "5", "name": "默认"}]
            }
            assert [
                r.url.params["api-version"] for r in calls if r.url.path.endswith("/queues")
            ] == list(QUEUE_VERSIONS)
        assert await app.state.config_store.read() == before


@pytest.mark.parametrize(
    "remote",
    [
        "https://other/c/sample/_git/demo",
        "https://ado.test/c/other/_git/demo",
        "https://ado.test:8443/c/sample/_git/demo",
    ],
)
async def test_unmatched(repo, tmp_path, remote):
    git(repo, "remote", "set-url", "origin", remote)
    async with execution(tmp_path) as (app, *_):
        async with client(app) as c:
            r = await c.post(PREFIX + "/repo", json={"local_repo_path": str(repo)})
            assert r.status_code == 200
            assert r.json()["project_id"] is None and r.json()["reason"] == "project_not_matched"


@pytest.mark.parametrize(
    "failure,code,status",
    [
        ("missing", "pat_missing", 409),
        ("404", "ado_not_found", 404),
        ("timeout", "ado_unreachable", 502),
    ],
)
async def test_ado_errors(tmp_path, failure, code, status):
    async with execution(tmp_path) as (app, *_):

        def transport(request):
            if failure == "timeout":
                raise httpx.ReadTimeout("敏感响应")
            return httpx.Response(404, json={})

        app.state.work_items_service.http = AdoRead(httpx.MockTransport(transport))
        if failure == "missing":
            app.state.settings_service.credentials.delete("ado_pat:lib:test")
        async with client(app) as c:
            r = await c.get(
                PREFIX + "/branches", params={"project_id": "proj:test", "repo_id": "r"}
            )
            assert r.status_code == status, r.text
            assert r.json()["detail"]["code"] == code
            assert "敏感" not in r.text


async def test_local_errors_fallback_and_auth(repo, tmp_path):
    async with execution(tmp_path) as (app, *_):
        app.state.work_items_service.http = AdoRead(httpx.MockTransport(handler([])))
        async with client(app) as c:
            r = await c.post(PREFIX + "/repo", json={"local_repo_path": str(tmp_path / "absent")})
            assert r.json()["detail"]["code"] == "not_git_repo"
            git(repo, "remote", "rename", "origin", "backup")
            assert (
                await c.post(PREFIX + "/repo", json={"local_repo_path": str(repo)})
            ).status_code == 200
            git(repo, "remote", "remove", "backup")
            r = await c.post(PREFIX + "/repo", json={"local_repo_path": str(repo)})
            assert r.json()["detail"]["code"] == "no_remote"
        async with client(app, False) as c:
            assert (
                await c.get(PREFIX + "/queues", params={"project_id": "proj:test"})
            ).status_code == 401


async def test_missing_existing_config_and_expanded_path(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    async with execution(tmp_path) as (app, *_):

        def transport(request):
            return httpx.Response(200, json={"id": "new-repo", "name": "新仓库"})

        app.state.work_items_service.http = AdoRead(httpx.MockTransport(transport))
        async with client(app) as c:
            r = await c.post(PREFIX + "/repo", json={"local_repo_path": "~/repo"})
            assert r.status_code == 200, r.text
            assert r.json()["local_repo_path"] == str(repo.resolve())
            assert r.json()["existing_config_id"] is None
            assert r.json()["default_branch"] is None


def test_git_timeout_is_stable(repo, monkeypatch):
    from toolbox_backend.services.release_discovery import read_remote

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 10
        assert kwargs["stdin"] == subprocess.DEVNULL
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(SettingsError) as exc:
        read_remote(repo)
    assert exc.value.code == "not_git_repo"
