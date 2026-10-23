"""Shared fixtures for S5-B: a real app, the real supervisor and the fake CLIs."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest_asyncio

from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.app import create_app
from toolbox_backend.domain.settings import LocalRepo
from toolbox_backend.settings import Settings

FAKE_DIR = Path(__file__).parent / "fixtures/fake_cli"
TOKEN = "s5b-local-test-token"


def make_app(tmp_path, *, home=None):
    return create_app(
        Settings(
            token=TOKEN,
            port=12345,
            data_dir=tmp_path / "data",
            legacy_config_dir=tmp_path / "legacy",
        ),
        credentials=MemoryCredentials(),
    )


async def configure(app, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)

    def add(c):
        if not any(r.id == "repo" for r in c.ado.local_repos):
            c.ado.local_repos.append(LocalRepo(id="repo", name="repo", path=str(repo)))

    config = await app.state.config_store.read()
    await app.state.config_store.update(config.revision, add)
    app.state.ai_service.path_extras = []
    return repo


def client_for(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:12345",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


def use_fakes(monkeypatch, tmp_path):
    log = tmp_path / "fake.log"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", f"{FAKE_DIR}:{Path(sys.executable).parent}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_AI_PYTHON", sys.executable)
    monkeypatch.setenv("FAKE_AI_LOG", str(log))
    return log


def records(log):
    if not Path(log).exists():
        return []
    return [json.loads(line) for line in Path(log).read_text().splitlines() if line]


def new_body(profile="claude_code", **extra):
    return dict(request_id=str(uuid4()), kind="chat", profile_id=profile, repo_id="repo", **extra)


async def wait_for(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached")


async def session_state(client, sid, state):
    async def check():
        view = (await client.get(f"/api/ai/sessions/{sid}")).json()
        return view if view["state"] == state else None

    return await wait_for(check)


async def events(client, sid):
    return (await client.get(f"/api/ai/sessions/{sid}/events", params={"limit": 1000})).json()["items"]


async def wait_event(client, sid, kind, count=1, **match):
    async def check():
        found = [
            e
            for e in await events(client, sid)
            if e["kind"] == kind and all(e["payload"].get(k) == v for k, v in match.items())
        ]
        return found if len(found) >= count else None

    return await wait_for(check)


async def say(client, sid, text):
    response = await client.post(
        f"/api/ai/sessions/{sid}/messages", json=dict(request_id=str(uuid4()), text=text)
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest_asyncio.fixture
async def chat(tmp_path, monkeypatch):
    log = use_fakes(monkeypatch, tmp_path)
    app = make_app(tmp_path)
    async with app.router.lifespan_context(app):
        repo = await configure(app, tmp_path)
        async with client_for(app) as client:
            yield app, client, repo, log
    assert os.environ["HOME"]
