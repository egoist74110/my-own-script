"""Launcher-owned, dev-only temporary Git fixture. No production file-protocol switch."""

import json
import os
from pathlib import Path

from toolbox_backend.adapters.task_git import GitAdapter
from toolbox_backend.domain.settings import DynamicTask, Library, Project

TASK_ROOT_ENV = "TOOLBOX_DEV_TASK_ROOT"


def task_root(dev):
    value = os.environ.get(TASK_ROOT_ENV)
    if value is None:
        return None
    if not (
        dev
        and os.environ.get("TOOLBOX_CREDENTIALS") == "memory"
        and os.environ.get("TOOLBOX_DEV_FAKE_ADO")
    ):
        raise ValueError("TOOLBOX_DEV_TASK_ROOT requires dev + memory + fake ADO")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError("task fixture root must be an existing temporary directory")
    path = path.resolve()
    # Only accept a launcher-created empty directory under the OS temporary tree.
    import tempfile

    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()) or any(path.iterdir()):
        raise ValueError("task fixture root must be empty and inside the OS temporary directory")
    return path


async def seed(app, root):
    git = app.state.tasks_service.git
    root = Path(root)
    bare, clone = root / "remote.git", root / "clone"
    # GitAdapter supplies the same isolated argv/environment and process lifecycle as production.
    await git.command(root, ["init", "--bare", str(bare)])
    await git.command(root, ["clone", str(bare), str(clone)])
    await git.command(clone, ["config", "user.name", "Toolbox Demo"])
    await git.command(clone, ["config", "user.email", "demo@example.invalid"])
    await git.command(clone, ["checkout", "-b", "main"])
    (clone / "README.txt").write_text("Toolbox isolated dev fixture\n", encoding="utf-8")
    await git.command(clone, ["add", "README.txt"])
    await git.command(clone, ["commit", "-m", "Seed isolated demo"])
    await git.command(clone, ["push", "origin", "refs/heads/main:refs/heads/main"])
    commit = await git.command(clone, ["rev-parse", "HEAD"])
    # MockTransport owns this in-memory state; no production network transport can reach here.
    app.state.work_items_service.http.transport.task_service.commit = commit
    for build in app.state.work_items_service.http.transport.task_service.builds.values():
        build["sourceVersion"] = commit
    fixture_path = Path(os.environ["TOOLBOX_DEV_FAKE_ADO"]) / "tasks.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    config = await app.state.config_store.initialize()
    if config.tasks.release_configs or config.ado.libraries:
        raise ValueError("dev task seed requires a fresh isolated data directory")

    def populate(c):
        c.ado.libraries = [
            Library(id="lib:sample", name="示例 ADO", base_url="http://ado.example.test/tfs")
        ]
        c.ado.projects = [
            Project(
                id="proj:sample",
                library_id="lib:sample",
                collection="Default Collection",
                project="示例项目",
            )
        ]
        c.ado.active_library_id, c.ado.active_project_id = "lib:sample", "proj:sample"
        c.import_.state = "declined"
        c.tasks.items = [
            DynamicTask(
                id=t["id"],
                name=t["name"],
                enabled=t["enabled"],
                project_id="proj:sample",
                repo_id="demo-repo",
                local_repo_path=str(clone),
                git_flow={"build_branch": "main", "update_branches": ["main"]},
                targets=[
                    {
                        "name": "演示环境",
                        "enabled": True,
                        "build_kind": "build",
                        "build_id": str(t["definition"]),
                        "release_id": str(t["definition"]),
                        "release_stage_ids": ["1"],
                    }
                ],
            )
            for t in fixture["tasks"]
        ]

    await app.state.config_store.update(config.revision, populate)
    await app.state.settings_service.put_pat(
        "lib:sample", config.revision + 1, "fake-task-demo-pat-000000"
    )


def git_for_root(data_dir, root):
    return GitAdapter(data_dir, test_remote_root=root)
