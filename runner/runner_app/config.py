from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class AppSpec(BaseModel):
    provider: str
    allowed_envs: list[str] = Field(default_factory=list)
    env_default: Optional[str] = None
    ref_default: Optional[str] = None

    # provider-specific fields (kept flexible for now)
    repo: Optional[str] = None
    workflow: Optional[str] = None
    org: Optional[str] = None
    project: Optional[str] = None
    pipeline_id: Optional[int] = None


class TasksConfig(BaseModel):
    apps: dict[str, AppSpec]


class LocalConfig(BaseModel):
    tasks_path: Optional[str] = None


def config_dir() -> Path:
    return Path.home() / ".config" / "runner"


def data_dir() -> Path:
    return Path.home() / ".local" / "share" / "runner"


def load_local_config() -> LocalConfig:
    cfg_path = config_dir() / "config.yaml"
    if not cfg_path.exists():
        return LocalConfig()
    raw = yaml.safe_load(cfg_path.read_text("utf-8")) or {}
    return LocalConfig.model_validate(raw)


def save_local_config(cfg: LocalConfig) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    path = cd / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(), sort_keys=False), "utf-8")
    return path


def resolve_tasks_path(explicit: Optional[str] = None) -> Path:
    # Highest priority: explicit CLI option
    if explicit:
        return Path(explicit).expanduser()

    # Next: env var
    env_path = os.getenv("RUNNER_TASKS_PATH")
    if env_path:
        return Path(env_path).expanduser()

    # Next: user config
    local = load_local_config()
    if local.tasks_path:
        return Path(local.tasks_path).expanduser()

    # Fallback: ./tasks.yaml
    return Path.cwd() / "tasks.yaml"


def load_tasks(tasks_path: Path) -> TasksConfig:
    if not tasks_path.exists():
        raise FileNotFoundError(
            f"tasks.yaml not found at: {tasks_path}. Create it from tasks.example.yaml."
        )

    raw: Any = yaml.safe_load(tasks_path.read_text("utf-8"))
    if raw is None:
        raw = {}
    return TasksConfig.model_validate(raw)


def get_app_spec(tasks: TasksConfig, app: str) -> AppSpec:
    if app not in tasks.apps:
        raise KeyError(f"Unknown app '{app}'. Allowed: {', '.join(sorted(tasks.apps.keys()))}")
    return tasks.apps[app]
