"""S4 HTTP/WS contracts. Inputs are strict; legacy output entries are retained."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, JsonValue, SecretStr, StringConstraints, model_validator

from toolbox_backend.domain.settings import StrictModel
from toolbox_backend.domain.telegram import ACLGroup, ACLMember, Control, Notify, numeric, username

ChatId = Annotated[str, StringConstraints(pattern=r"^-?\d{1,20}$")]
Username = Annotated[str, StringConstraints(pattern=r"^@[A-Za-z0-9_]{5,32}$")]


class RevisionRequest(StrictModel):
    revision: int = Field(ge=0)


class TokenRequest(RevisionRequest):
    token: SecretStr


class EnableRequest(RevisionRequest):
    ack_old_bot_stopped: bool
    delete_webhook: bool = False


class NotifyPatch(StrictModel):
    include_details: bool | None = None
    ui_runs_to_owner: bool | None = None


class TelegramSettingsRequest(RevisionRequest):
    notify: NotifyPatch | None = None


class GroupFields(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    can_run: bool = False
    can_stop: bool = False
    can_status: bool = True
    can_rollback: bool = False
    task_ids: list[str] = Field(default_factory=list, max_length=200)


class GroupCreate(GroupFields):
    revision: int = Field(ge=0)


class GroupPatch(RevisionRequest):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    can_run: bool | None = None
    can_stop: bool | None = None
    can_status: bool | None = None
    can_rollback: bool | None = None
    task_ids: list[str] | None = Field(default=None, max_length=200)


class MemberCreate(RevisionRequest):
    group_id: str
    chat_id: ChatId | None = None
    username: Username | None = None
    label: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def identity(self):
        if not (self.chat_id or self.username):
            raise ValueError("成员身份不能为空")
        return self


class MemberPatch(RevisionRequest):
    group_id: str | None = None
    chat_id: ChatId | None = None
    username: Username | None = None
    label: str | None = Field(default=None, max_length=64)


class WhitelistRequest(RevisionRequest):
    legacy_whitelist: list[str]

    @model_validator(mode="after")
    def entries(self):
        values = self.legacy_whitelist
        if any(not (numeric(v) or username(v)) for v in values):
            raise ValueError("白名单无效")
        if len({v.lower() for v in values}) != len(values):
            raise ValueError("白名单重复")
        return self


class CredentialView(BaseModel):
    present: bool
    source: Literal["imported", "manual", "unknown"]


class BotView(BaseModel):
    credential: CredentialView
    bot_id: str | None
    username: str | None


class OwnerView(BaseModel):
    bound: bool
    chat_id: str | None
    source: Literal["imported", "bound"] | None


PollState = Literal[
    "disabled",
    "starting",
    "polling",
    "backoff",
    "conflict",
    "token_invalid",
    "webhook_set",
    "store_unavailable",
    "stopping",
]


AIId = Literal["claude_code", "codex", "gemini"]


class _PollStatus(BaseModel):
    state: PollState
    since: str
    last_error_category: str | None = None


class TelegramStatusData(_PollStatus):
    # Additive (S5-C): "main" or "ai:<ai_id>"; absent in older payloads means main.
    slot: str = "main"


class PollerView(_PollStatus):
    # No slot here: the main GET keeps its S4 shape; AIBotView carries its own slot.
    last_poll_at: str | None = None
    consecutive_failures: int = 0


class ACLView(BaseModel):
    groups: list[ACLGroup | JsonValue]
    members: list[ACLMember | JsonValue]
    legacy_whitelist: list[JsonValue]


class TelegramView(BaseModel):
    revision: int
    control: Control
    bot: BotView
    owner: OwnerView
    notify: Notify
    poller: PollerView
    acl: ACLView
    warnings: list[str]


class AIBotEnableRequest(RevisionRequest):
    ack_old_bot_cleared: bool
    delete_webhook: bool = False


class AIBotControlView(BaseModel):
    enabled: bool
    enabled_at: str | None = None
    bot_id: str | None = None


class AIBotView(BaseModel):
    ai_id: AIId
    slot: str
    control: AIBotControlView
    bot: BotView
    owner: OwnerView
    poller: PollerView


class AIBotsView(BaseModel):
    revision: int
    items: list[AIBotView]
    warnings: list[str] = Field(default_factory=list)


class BindCodeResponse(BaseModel):
    code: str
    expires_at: str


class ActivityItem(BaseModel):
    received_at: str
    kind: str
    command: str | None
    chat_id: str | None
    status: str
    reason: str | None


class ActivityResponse(BaseModel):
    items: list[ActivityItem]


class InjectRequest(StrictModel):
    update: dict[str, JsonValue]
    bot_id: int | None = Field(default=None, ge=1)


class FakeSentItem(BaseModel):
    bot_id: str | None = None
    method: str
    payload: dict[str, JsonValue]


class FakeSentResponse(BaseModel):
    items: list[FakeSentItem]


class TelegramErrorDetail(BaseModel):
    code: Literal[
        "validation_error",
        "telegram_active",
        "ack_required",
        "webhook_set",
        "bot_in_use",
        "legacy_missing",
        "owner_not_bound",
        "telegram_request_failed",
        "telegram_store_unavailable",
        "revision_conflict",
        "no_credential",
        "credential_backend_error",
        "store_unavailable",
        "store_busy",
        "busy",
        "not_found",
    ]
    message: str
    category: (
        Literal[
            "network",
            "timeout",
            "http_4xx",
            "http_5xx",
            "conflict",
            "unauthorized",
            "rate_limited",
            "bad_response",
        ]
        | None
    ) = None
    revision: int | None = None


class TelegramErrorResponse(BaseModel):
    detail: TelegramErrorDetail
