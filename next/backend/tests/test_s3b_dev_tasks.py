"""Dev fixtures are isolated, stateful and inaccessible from production mode."""

import asyncio
import json
import uuid
from pathlib import Path

import httpx
import pytest

from toolbox_backend.adapters.ado_read import AdoRead
from toolbox_backend.adapters.credentials import MemoryCredentials
from toolbox_backend.adapters.dev_tasks import git_for_root, seed, task_root
from toolbox_backend.adapters.fake_ado import fake_transport
from toolbox_backend.app import create_app
from toolbox_backend.settings import Settings


@pytest.mark.parametrize(
    "dev,memory,fake", [(False, True, True), (True, False, True), (True, True, False)]
)
def test_fixture_file_protocol_requires_all_three_gates(tmp_path, monkeypatch, dev, memory, fake):
    monkeypatch.setenv("TOOLBOX_DEV_TASK_ROOT", str(tmp_path))
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory" if memory else "keyring")
    if fake:
        monkeypatch.setenv("TOOLBOX_DEV_FAKE_ADO", "not-accessed")
    else:
        monkeypatch.delenv("TOOLBOX_DEV_FAKE_ADO", raising=False)
    with pytest.raises(ValueError):
        task_root(dev)


async def test_dev_tasks_seed_git_and_three_observable_paths(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "fake-ado"
    root = tmp_path / "task-root"
    root.mkdir()
    monkeypatch.setenv("TOOLBOX_DEV_TASK_ROOT", str(root))
    monkeypatch.setenv("TOOLBOX_DEV_FAKE_ADO", str(fixture))
    monkeypatch.setenv("TOOLBOX_CREDENTIALS", "memory")
    transport = fake_transport(True)
    settings = Settings(
        token="dev-task-bearer-isolated",
        port=1234,
        dev=True,
        data_dir=tmp_path / "data",
        legacy_config_dir=tmp_path / "legacy",
    )
    app = create_app(
        settings,
        credentials=MemoryCredentials(),
        legacy_credentials=MemoryCredentials(),
        ado_read=AdoRead(transport),
        task_git=git_for_root(settings.data_dir, task_root(True)),
    )
    try:
        await seed(app, root)
        async with app.router.lifespan_context(app):
            config = await app.state.config_store.read()
            assert len(config.tasks.items) == 4
            git = app.state.tasks_service.git
            assert git.environment()["GIT_ALLOW_PROTOCOL"] == "file"
            assert "SSH_AUTH_SOCK" not in git.environment()
            for t in config.tasks.items:
                info = await git.preflight(t.local_repo_path)
                assert Path(info["root"]).is_relative_to(root)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:1234",
                headers={"Authorization": "Bearer dev-task-bearer-isolated"},
            ) as client:
                for task_id, operation, status in [
                    ("task:demo-sync", "sync_build_release", "succeeded"),
                    ("task:demo-deploy", "deploy_only", "failed"),
                    ("task:demo-rollback", "rollback", "unknown"),
                ]:
                    response = await client.post(
                        f"/api/tasks/{task_id}/preflight",
                        json={
                            "revision": config.revision,
                            "operation": operation,
                            **({"rollback_offset": 1} if operation == "rollback" else {}),
                        },
                    )
                    assert response.status_code == 200, response.text
                    plan = response.json()
                    response = await client.post(
                        f"/api/tasks/{task_id}/runs",
                        json={
                            "plan_id": plan["plan_id"],
                            "request_id": str(uuid.uuid4()),
                            "ack_old_app_idle": True,
                        },
                    )
                    assert response.status_code == 202, response.text
                    rid = response.json()["run_id"]
                    await asyncio.gather(*list(app.state.run_service.workers.values()))
                    response = await client.get(f"/api/runs/{rid}")
                    assert response.status_code == 200, response.text
                    assert response.json()["status"] == status, response.text
                    assert "fake-task-demo-pat" not in response.text
                before = len(transport.task_service.writes)
                response = await client.post(
                    "/api/tasks/task:demo-disabled/preflight",
                    json={"revision": config.revision, "operation": "sync_build_release"},
                )
                assert response.status_code == 422
                assert len(transport.task_service.writes) == before
                events = (await client.get(f"/api/runs/{rid}/events")).json()
                assert "fake-task-demo-pat" not in json.dumps(events)
    finally:
        await app.state.run_service.close()
