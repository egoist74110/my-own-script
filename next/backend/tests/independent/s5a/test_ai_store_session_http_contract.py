"""S5-A persistence and HTTP boundaries without external CLI or credentials."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from toolbox_backend.adapters.ai_store import AIStore
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.errors import SettingsError
from toolbox_backend.domain.settings import LocalRepo
from toolbox_backend.settings import Settings

FAKE_CLI_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "fake_cli"
FAKE_CLI = FAKE_CLI_DIR / "fake.py"
APP_TOKEN = "s5a-test-app-token"


@dataclass
class AIContext:
    app: object
    client: httpx.AsyncClient
    credentials: MemoryCredentials
    repo_path: Path


class FakeOwner:
    """In-memory supervised process double; no subprocess or CLI is started."""

    def __init__(self):
        self._finished = asyncio.Event()
        self.closed = False
        self.identity = {
            "pid": 41001,
            "pgid": 41001,
            "proc_start_time": "fake-start",
            "executable": str(FAKE_CLI),
        }
        self.proc = SimpleNamespace(stdout=None, wait=self._wait)

    async def _wait(self):
        await self._finished.wait()
        return 0

    def stop(self):
        self._finished.set()

    def close_control(self):
        return None

    async def close(self):
        self.closed = True
        self._finished.set()


@asynccontextmanager
async def open_ai_app(tmp_path: Path, monkeypatch, *, repo_path: Path | None = None):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join([str(FAKE_CLI_DIR), "/usr/bin", "/bin"]),
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    credentials = MemoryCredentials()
    app = create_app(
        Settings(
            token=APP_TOKEN,
            port=1234,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=credentials,
        legacy_credentials=MemoryCredentials(),
    )
    app.state.ai_service.path_extras = []
    if repo_path is not None:
        await app.state.config_store.initialize()
        await app.state.config_store.update(
            0,
            lambda config: config.ado.local_repos.append(
                LocalRepo(id="repo-1", name="Temporary repo", path=str(repo_path))
            ),
        )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:1234",
            headers={"Authorization": f"Bearer {APP_TOKEN}"},
        ) as client:
            yield AIContext(app, client, credentials, repo_path or Path())


def _session_payload(*, request_id: str | None = None, repo_id: str = "repo-1", **extra):
    return {
        "request_id": request_id or str(uuid4()),
        "kind": "terminal",
        "profile_id": "codex",
        "repo_id": repo_id,
        **extra,
    }


@pytest.mark.asyncio
async def test_corrupt_ai_database_enters_readonly_without_rewriting_original(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "ai.sqlite3"
    original = b"not a sqlite database\x00original"
    database.write_bytes(original)
    store = AIStore(data_dir)

    await store.initialize()

    assert store.readonly_error
    assert database.read_bytes() == original
    with pytest.raises(SettingsError) as raised:
        store.require()
    assert raised.value.code == "ai_store_unavailable"
    await store.close()


@pytest.mark.asyncio
async def test_unknown_ai_database_version_is_readonly_and_preserved(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "ai.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=99")
    before = database.read_bytes()
    store = AIStore(data_dir)

    await store.initialize()

    assert store.readonly_error
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
    assert database.read_bytes() == before
    await store.close()


@pytest.mark.asyncio
async def test_symlink_ai_database_is_refused_without_touching_target(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = tmp_path / "outside.sqlite3"
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES('preserve')")
    before = target.read_bytes()
    (data_dir / "ai.sqlite3").symlink_to(target)
    store = AIStore(data_dir)

    await store.initialize()

    assert store.readonly_error
    assert target.read_bytes() == before
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "preserve"
    await store.close()


@pytest.mark.asyncio
async def test_request_id_replay_returns_same_session_without_second_start(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    starts: list[FakeOwner] = []

    async def fake_start(*_args, **_kwargs):
        owner = FakeOwner()
        starts.append(owner)
        return owner

    monkeypatch.setattr(
        "toolbox_backend.services.ai_sessions.SupervisedProcess.start", fake_start
    )
    async with open_ai_app(tmp_path, monkeypatch, repo_path=repo) as ctx:
        monkeypatch.setattr(
            ctx.app.state.ai_service,
            "_resolve",
            lambda _command: [sys.executable, str(FAKE_CLI), "--echo"],
        )
        payload = _session_payload(request_id=str(uuid4()))
        first = await ctx.client.post("/api/ai/sessions", json=payload)
        second = await ctx.client.post("/api/ai/sessions", json=payload)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["id"] == second.json()["id"]
        assert len(starts) == 1
        closed = await ctx.client.post(
            f"/api/ai/sessions/{first.json()['id']}/close", json={}
        )
        assert closed.status_code == 200, closed.text
        assert starts[0].closed


@pytest.mark.asyncio
async def test_session_rejects_unregistered_repo_and_client_supplied_path(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    starts = 0

    async def fake_start(*_args, **_kwargs):
        nonlocal starts
        starts += 1
        return FakeOwner()

    monkeypatch.setattr(
        "toolbox_backend.services.ai_sessions.SupervisedProcess.start", fake_start
    )
    async with open_ai_app(tmp_path, monkeypatch, repo_path=repo) as ctx:
        unknown = await ctx.client.post(
            "/api/ai/sessions", json=_session_payload(repo_id="not-configured")
        )
        supplied_path = await ctx.client.post(
            "/api/ai/sessions",
            json=_session_payload(cwd=str(tmp_path / "outside")),
        )

        assert unknown.status_code == 409
        assert unknown.json()["detail"]["code"] == "repo_missing"
        assert supplied_path.status_code == 422
        assert supplied_path.json()["detail"]["code"] == "validation_error"
        assert starts == 0


@pytest.mark.asyncio
async def test_session_rejects_repo_replaced_with_symlink(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    starts = 0

    async def fake_start(*_args, **_kwargs):
        nonlocal starts
        starts += 1
        return FakeOwner()

    monkeypatch.setattr(
        "toolbox_backend.services.ai_sessions.SupervisedProcess.start", fake_start
    )
    async with open_ai_app(tmp_path, monkeypatch, repo_path=repo) as ctx:
        repo.rmdir()
        repo.symlink_to(outside, target_is_directory=True)
        response = await ctx.client.post("/api/ai/sessions", json=_session_payload())

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "repo_missing"
        assert starts == 0


@pytest.mark.asyncio
async def test_http_rejects_session_model_and_cli_enum_injection(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    starts = 0

    async def fake_start(*_args, **_kwargs):
        nonlocal starts
        starts += 1
        return FakeOwner()

    monkeypatch.setattr(
        "toolbox_backend.services.ai_sessions.SupervisedProcess.start", fake_start
    )
    async with open_ai_app(tmp_path, monkeypatch, repo_path=repo) as ctx:
        injection_path = tmp_path / "model-injection-marker"
        bad_model = await ctx.client.post(
            "/api/ai/sessions",
            json=_session_payload(model=f"$(touch {injection_path})"),
        )
        bad_kind = await ctx.client.post(
            "/api/ai/sessions", json=_session_payload(kind="terminal;exec")
        )
        bad_cli = await ctx.client.post(
            "/api/ai/profiles",
            json={
                "revision": 1,
                "name": "Injected",
                "command": "codex",
                "cli": "codex;exec",
            },
        )

        assert bad_model.status_code == 422
        assert bad_model.json()["detail"]["code"] == "validation_error"
        assert bad_kind.status_code == 422
        assert bad_kind.json()["detail"]["code"] == "validation_error"
        assert bad_cli.status_code == 422
        assert bad_cli.json()["detail"]["code"] == "validation_error"
        assert starts == 0
        assert not os.path.exists(injection_path)  # noqa: ASYNC240
