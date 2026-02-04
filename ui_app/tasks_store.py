from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from runner_app.config import config_dir


class FlowTaskConfig(BaseModel):
    id: str = "sync_merge_build_release"
    enabled: bool = True

    project_id: Optional[str] = None
    repo_id: Optional[str] = None
    repo_name: Optional[str] = None
    source_branch: str = ""
    target_branch: str = ""

    # build target (pipeline|builddef)
    build_kind: Optional[str] = None
    build_id: Optional[str] = None
    build_name: Optional[str] = None

    # release target
    release_kind: Optional[str] = None
    release_id: Optional[str] = None
    release_name: Optional[str] = None

    # release stage (environment) within release definition
    release_stage_id: Optional[str] = None
    release_stage_name: Optional[str] = None

    build_timeout_min: int = 30
    release_timeout_min: int = 60


class TaskSettings(BaseModel):
    flows: list[FlowTaskConfig] = Field(default_factory=list)


def tasks_path() -> Path:
    return config_dir() / "tasks.yaml"


def load_task_settings() -> TaskSettings:
    p = tasks_path()
    if not p.exists():
        return TaskSettings(flows=[FlowTaskConfig()])
    raw = yaml.safe_load(p.read_text("utf-8")) or {}
    cfg = TaskSettings.model_validate(raw)
    if not cfg.flows:
        cfg.flows = [FlowTaskConfig()]
    return cfg


def save_task_settings(cfg: TaskSettings) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    p = tasks_path()
    p.write_text(yaml.safe_dump(cfg.model_dump(), sort_keys=False), "utf-8")
    return p


def get_flow(cfg: TaskSettings, flow_id: str = "sync_merge_build_release") -> FlowTaskConfig:
    for f in cfg.flows:
        if f.id == flow_id:
            return f
    f = FlowTaskConfig(id=flow_id)
    cfg.flows.append(f)
    return f
