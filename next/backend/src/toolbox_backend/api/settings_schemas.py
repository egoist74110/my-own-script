from typing import Literal

from pydantic import Field, JsonValue

from toolbox_backend.adapters.ado_http import ConnectionCategory
from toolbox_backend.domain.settings import (
    BaseURL,
    Id,
    ImportState,
    Library,
    LocalRepo,
    Name,
    Pat,
    Project,
    RepoPath,
    Segment,
    StrictModel,
)


class RevisionRequest(StrictModel):
    revision: int = Field(ge=0)


class LibraryCreate(RevisionRequest):
    name: Name
    base_url: BaseURL
    pat: Pat | None = None


class LibraryPatch(RevisionRequest):
    name: Name | None = None
    base_url: BaseURL | None = None
    pat: Pat | None = None
    keep_pat: bool = False


class PatRequest(RevisionRequest):
    pat: Pat


class ProjectCreate(RevisionRequest):
    library_id: Id
    collection: Segment
    project: Segment


class ProjectPatch(RevisionRequest):
    library_id: Id | None = None
    collection: Segment | None = None
    project: Segment | None = None


class LocalRepoCreate(RevisionRequest):
    name: Name
    path: RepoPath


class LocalRepoPatch(RevisionRequest):
    name: Name | None = None
    path: RepoPath | None = None


class LocalRepoView(LocalRepo):
    exists: bool
    warnings: list[str] = Field(default_factory=list)


class ActiveRequest(RevisionRequest):
    library_id: Id | None
    project_id: Id | None


class TestRequest(StrictModel):
    collection: Segment
    pat: Pat | None = None


class ImportRequest(StrictModel):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class MutationResponse(StrictModel):
    revision: int
    id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CredentialStatus(StrictModel):
    kind: Literal[
        "ado_pat", "telegram_bot", "telegram_ai_bot", "lark_app_secret", "figma_token"
    ] = "ado_pat"
    account: str
    ref: str
    ref_name: str | None
    present: bool | None
    source: Literal["imported", "manual", "unknown"]
    state: Literal["present", "missing", "unreadable", "orphan", "pending_delete"]
    updated_at: str | None


class LibraryCredential(StrictModel):
    present: bool | None
    source: Literal["imported", "manual", "unknown"]
    state: Literal["present", "missing", "unreadable", "orphan", "pending_delete"]


class LibraryView(Library):
    credential: LibraryCredential


class AdoResponse(StrictModel):
    revision: int
    libraries: list[LibraryView]
    projects: list[Project]
    local_repos: list[LocalRepoView]
    active_library_id: str | None
    active_project_id: str | None


class SettingsResponse(StrictModel):
    revision: int
    schema_version: int = 1
    store_state: Literal["ok", "readonly_error"]
    store_error: str | None = None
    data_dir: str
    legacy_config_dir: str
    app_version: str
    import_: ImportState = Field(alias="import")


class ImportPreview(StrictModel):
    fingerprint: str
    source_dir: str
    files: list[dict[str, JsonValue]]
    libraries: list[dict[str, JsonValue]]
    projects: list[Project]
    tasks_rule: Literal["empty", "kept_tasks", "migrated_from_flows"]
    task_count: int
    preserved_sections: list[str]
    warnings: list[str]
    errors: list[str]


class AdoRequestErrorDetail(StrictModel):
    code: Literal["ado_request_failed"] = "ado_request_failed"
    category: ConnectionCategory
    message: str


class AdoRequestErrorResponse(StrictModel):
    detail: AdoRequestErrorDetail


class NoCredentialErrorDetail(StrictModel):
    code: Literal["no_credential"] = "no_credential"
    message: str


class NoCredentialErrorResponse(StrictModel):
    detail: NoCredentialErrorDetail


class ValidationErrorDetail(StrictModel):
    code: Literal["validation_error"] = "validation_error"
    message: str


class ValidationErrorResponse(StrictModel):
    detail: ValidationErrorDetail
