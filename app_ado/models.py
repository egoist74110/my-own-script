from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class LibraryEntry(BaseModel):
    id: str
    name: str
    base_url: str


class ProjectEntry(BaseModel):
    id: str
    library_id: str
    collection: str
    project: str


class FlowTaskConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = "sync_merge_build_release"  # or sync_build_release
    enabled: bool = True

    project_id: Optional[str] = None

    # local repo folder to run git commands
    local_repo_path: str = ""

    repo_id: Optional[str] = None
    repo_name: Optional[str] = None
    source_branch: str = ""
    target_branch: str = ""

    build_kind: Optional[str] = None
    build_id: Optional[str] = None
    build_name: Optional[str] = None

    release_id: Optional[str] = None
    release_name: Optional[str] = None

    release_stage_ids: list[str] = Field(default_factory=list)
    release_stage_names: list[str] = Field(default_factory=list)


class UiSettings(BaseModel):
    libraries: list[LibraryEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    active_library_id: Optional[str] = None
    active_project_id: Optional[str] = None

    telegram_chat_id: str = ""


class TaskSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    flows: list[FlowTaskConfig] = Field(default_factory=list)
