from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from runner_app.config import config_dir


class RepoEntry(BaseModel):
    id: str
    provider: str  # azuredevops
    display_name: str

    # provider-specific (azuredevops)
    # - public cloud: org + project
    # - server: base_url + collection + project
    base_url: Optional[str] = None
    collection: Optional[str] = None
    org: Optional[str] = None
    project: Optional[str] = None


class UiSettings(BaseModel):
    repos: list[RepoEntry] = Field(default_factory=list)
    active_repo_id: Optional[str] = None


def settings_path() -> Path:
    return config_dir() / "ui_settings.yaml"


def load_ui_settings() -> UiSettings:
    path = settings_path()
    if not path.exists():
        return UiSettings()
    raw = yaml.safe_load(path.read_text("utf-8")) or {}
    return UiSettings.model_validate(raw)


def save_ui_settings(cfg: UiSettings) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    path = settings_path()
    path.write_text(yaml.safe_dump(cfg.model_dump(), sort_keys=False), "utf-8")
    return path
