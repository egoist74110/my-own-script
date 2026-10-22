from typing import Literal

from pydantic import Field

from toolbox_backend.domain.settings import StrictModel


class HtmlField(StrictModel):
    html: str | None
    omitted: Literal["too_large"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class WorkItemSummary(StrictModel):
    id: int
    title: str
    type: str | None = None
    state: str | None = None
    assigned_to: str | None = None
    board_column: str | None = None
    priority: int | None = None
    severity: str | None = None
    tags: list[str] = Field(default_factory=list)
    area_path: str | None = None
    iteration_path: str | None = None
    created_date: str | None = None
    changed_date: str | None = None


class HtmlFields(StrictModel):
    description: HtmlField | None = None
    repro_steps: HtmlField | None = None
    acceptance_criteria: HtmlField | None = None


class Attachment(StrictModel):
    name: str
    size: int | None = None
    is_image: bool
    media_id: str | None
    blocked_origin: str | None


class WorkItemLink(StrictModel):
    kind: Literal["pull_request", "commit", "hyperlink", "other"]
    label: str
    url: str | None = None


class WorkItemDetail(WorkItemSummary):
    rev: int | None = None
    web_url: str
    html: HtmlFields
    parent_id: int | None = None
    child_ids: list[int]
    attachments: list[Attachment]
    links: list[WorkItemLink]


class ColumnsResponse(StrictModel):
    columns: list[str]
    default: str = "开发中"


class WorkItemsResponse(StrictModel):
    items: list[WorkItemSummary]
    truncated: bool
    omitted: int


class ChildItem(WorkItemSummary):
    parent_id: int
    depth: int


class ChildrenResponse(StrictModel):
    items: list[ChildItem]
    truncated: bool


class Comment(StrictModel):
    id: int
    author: str | None = None
    created_date: str | None = None
    modified_date: str | None = None
    html: str | None
    omitted: Literal["too_large"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class CommentsResponse(StrictModel):
    comments: list[Comment]
    truncated: bool


class UpdateField(StrictModel):
    name: str
    old: str
    new: str


class Update(StrictModel):
    id: int
    rev: int | None = None
    revised_by: str | None = None
    revised_date: str | None = None
    fields: list[UpdateField]
    relations_added: int
    relations_removed: int


class UpdatesResponse(StrictModel):
    updates: list[Update]
    truncated: bool


class WorkItemErrorDetail(StrictModel):
    code: Literal[
        "validation_error",
        "not_found",
        "media_expired",
        "unsupported_media",
        "no_credential",
        "ado_request_failed",
        "busy",
        "store_unavailable",
    ]
    message: str
    category: (
        Literal[
            "unauthorized",
            "forbidden",
            "redirect",
            "blocked_origin",
            "tls",
            "timeout",
            "network",
            "bad_response",
            "too_large",
        ]
        | None
    ) = None


class WorkItemErrorResponse(StrictModel):
    detail: WorkItemErrorDetail
