from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from runner_app.config import config_dir


class LibraryEntry(BaseModel):
    id: str
    provider: str = "azuredevops"
    name: str
    base_url: str


class ProjectEntry(BaseModel):
    id: str
    library_id: str
    collection: str
    project: str


class UiSettings(BaseModel):
    libraries: list[LibraryEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    active_library_id: Optional[str] = None
    active_project_id: Optional[str] = None


def settings_path() -> Path:
    return config_dir() / "ui_settings.yaml"


def load_ui_settings() -> UiSettings:
    path = settings_path()
    if not path.exists():
        return UiSettings()

    raw = yaml.safe_load(path.read_text("utf-8")) or {}

    # Back-compat migration from older schema that used `repos`.
    if "repos" in raw and "libraries" not in raw:
        libs: list[dict] = []
        projs: list[dict] = []
        for r in raw.get("repos") or []:
            rid = r.get("id")
            if not rid:
                continue
            libs.append(
                {
                    "id": rid,
                    "provider": "azuredevops",
                    "name": r.get("display_name") or rid,
                    "base_url": r.get("base_url") or "",
                }
            )
            # If legacy had a project, create a project entry.
            coll = r.get("default_collection") or r.get("collection") or r.get("org")
            if coll and (r.get("project") or (r.get("projects") or [])):
                # prefer first
                pj = r.get("project") or (r.get("projects") or [None])[0]
                if pj:
                    projs.append(
                        {
                            "id": f"proj:{rid}",
                            "library_id": rid,
                            "collection": coll,
                            "project": pj,
                        }
                    )

        raw2 = {
            "libraries": libs,
            "projects": projs,
            "active_library_id": raw.get("active_repo_id"),
            "active_project_id": None,
        }
        raw = raw2

    cfg = UiSettings.model_validate(raw)

    # default actives
    if cfg.libraries and not cfg.active_library_id:
        cfg.active_library_id = cfg.libraries[0].id
    if cfg.projects and not cfg.active_project_id:
        cfg.active_project_id = cfg.projects[0].id

    save_ui_settings(cfg)
    return cfg


def save_ui_settings(cfg: UiSettings) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    path = settings_path()
    path.write_text(yaml.safe_dump(cfg.model_dump(), sort_keys=False), "utf-8")
    return path
