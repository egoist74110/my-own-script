from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from runner_app.config import (
    APP_ID,
    LocalConfig,
    load_local_config,
    load_tasks,
    resolve_tasks_path,
    save_local_config,
)
from runner_app.runner import build as do_build
from runner_app.runner import publish as do_publish
from runner_app.storage import Storage

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")


def _print_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _tasks(tasks_path_opt: Optional[str]) -> tuple[Path, object]:
    tasks_path = resolve_tasks_path(tasks_path_opt)
    tasks = load_tasks(tasks_path)
    return tasks_path, tasks


@app.command()
def publish(
    app_name: str = typer.Argument(..., metavar="<app>"),
    env: Optional[str] = typer.Argument(None, metavar="[env]"),
    ref: Optional[str] = typer.Argument(None, metavar="[ref]"),
    tasks_path: Optional[str] = typer.Option(None, "--tasks", help="Path to tasks.yaml"),
) -> None:
    """Publish an app (stubbed provider)."""
    _, tasks = _tasks(tasks_path)
    storage = Storage()
    try:
        do_publish(tasks=tasks, app=app_name, env=env, ref=ref, storage=storage)
    except Exception as e:
        _print_json({"error": str(e)})
        raise typer.Exit(code=1)


@app.command()
def build(
    app_name: str = typer.Argument(..., metavar="<app>"),
    ref: Optional[str] = typer.Argument(None, metavar="[ref]"),
    tasks_path: Optional[str] = typer.Option(None, "--tasks", help="Path to tasks.yaml"),
) -> None:
    """Build an app (stubbed provider)."""
    _, tasks = _tasks(tasks_path)
    storage = Storage()
    try:
        do_build(tasks=tasks, app=app_name, ref=ref, storage=storage)
    except Exception as e:
        _print_json({"error": str(e)})
        raise typer.Exit(code=1)


@app.command()
def status(
    job_id: str = typer.Argument(..., metavar="<job_id>"),
) -> None:
    """Get job status from storage."""
    storage = Storage()
    try:
        job = storage.get_job(job_id)
        _print_json(job.to_public_json())
    except Exception as e:
        _print_json({"error": str(e)})
        raise typer.Exit(code=1)


@app.command()
def logs(
    job_id: str = typer.Argument(..., metavar="<job_id>"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines"),
) -> None:
    """Show last N log lines for a job (JSON output)."""
    storage = Storage()
    try:
        job = storage.get_job(job_id)
        if not job.log_path:
            _print_json({"job_id": job_id, "lines": []})
            return
        p = Path(job.log_path)
        if not p.exists():
            _print_json({"job_id": job_id, "lines": []})
            return
        raw_lines = p.read_text("utf-8").splitlines()[-max(lines, 0) :]
        _print_json({"job_id": job_id, "lines": raw_lines})
    except Exception as e:
        _print_json({"error": str(e)})
        raise typer.Exit(code=1)


@app.command()
def setup() -> None:
    """Interactive setup: stores tokens in keyring; writes non-sensitive config."""
    import getpass

    import keyring

    cfg = load_local_config()

    typer.echo("Select providers to configure:")
    use_github = typer.confirm("Configure GitHub token?", default=True)
    use_azure = typer.confirm("Configure Azure DevOps token?", default=False)
    _ = typer.confirm("Configure Telegram notifier (stub)?", default=False)

    if use_github:
        typer.echo("GitHub token: create a Personal Access Token with appropriate repo/workflow permissions.")
        token = getpass.getpass("Enter GITHUB token (hidden): ")
        if token.strip():
            keyring.set_password(APP_ID, "github_token", token.strip())

    if use_azure:
        typer.echo("Azure DevOps token: create a PAT with build/release permissions.")
        token = getpass.getpass("Enter AZURE DevOps token (hidden): ")
        if token.strip():
            keyring.set_password(APP_ID, "azure_token", token.strip())

    if typer.confirm("Save default tasks.yaml path to user config?", default=True):
        path = typer.prompt("tasks.yaml path", default=str(resolve_tasks_path(None)))
        cfg.tasks_path = str(Path(path).expanduser())
        saved = save_local_config(cfg)
    else:
        saved = None

    # summary (never print token values)
    gh_set = (keyring.get_password(APP_ID, "github_token") is not None) or (
        keyring.get_password("runner", "github_token") is not None
    )
    az_set = (keyring.get_password(APP_ID, "azure_token") is not None) or (
        keyring.get_password("runner", "azure_token") is not None
    )
    _print_json(
        {
            "keyring": {"github_token": "saved" if gh_set else "missing", "azure_token": "saved" if az_set else "missing"},
            "config": {"tasks_path": cfg.tasks_path, "config_path": str(saved) if saved else None},
        }
    )


@config_app.command("show")
def config_show() -> None:
    """Show current configuration status (no secrets)."""
    import os

    import keyring

    cfg = load_local_config()
    tasks_path = resolve_tasks_path(cfg.tasks_path)
    gh_env = bool(os.getenv("GITHUB_TOKEN"))
    az_env = bool(os.getenv("AZURE_DEVOPS_TOKEN"))
    gh_kr = (keyring.get_password(APP_ID, "github_token") is not None) or (
        keyring.get_password("runner", "github_token") is not None
    )
    az_kr = (keyring.get_password(APP_ID, "azure_token") is not None) or (
        keyring.get_password("runner", "azure_token") is not None
    )

    _print_json(
        {
            "tasks_path": str(tasks_path),
            "tasks_exists": tasks_path.exists(),
            "tokens": {
                "github": {"env": gh_env, "keyring": gh_kr, "effective": gh_env or gh_kr},
                "azure": {"env": az_env, "keyring": az_kr, "effective": az_env or az_kr},
            },
        }
    )
