"""发布配置只读发现契约。"""

from typing import Literal

from pydantic import BaseModel, Field

from toolbox_backend.api.release_schemas import ReleaseTargetInput
from toolbox_backend.domain.settings import StrictModel


class DiscoverRepoInput(StrictModel):
    local_repo_path: str = Field(min_length=1, max_length=4096)


class DiscoverRepoResponse(BaseModel):
    local_repo_path: str
    remote_url: str
    project_id: str | None = None
    project_label: str | None = None
    repo_id: str | None = None
    repo_name: str | None = None
    default_branch: str | None = None
    suggested_name: str | None = None
    existing_config_id: str | None = None
    reason: Literal["project_not_matched"] | None = None


class DiscoverBranchesResponse(BaseModel):
    branches: list[str]
    default_branch: str | None


class DiscoveredItem(BaseModel):
    id: str
    name: str


class DiscoveredBuild(DiscoveredItem):
    kind: Literal["pipeline", "build"]


class DiscoveredRelease(DiscoveredItem):
    build_definition_ids: list[str]
    environments: list[DiscoveredItem]


class DiscoverTargetsResponse(BaseModel):
    builds: list[DiscoveredBuild]
    releases: list[DiscoveredRelease]
    suggested_targets: list[ReleaseTargetInput]


class DiscoverQueuesResponse(BaseModel):
    queues: list[DiscoveredItem]
