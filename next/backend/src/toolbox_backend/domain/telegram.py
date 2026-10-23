"""Typed current Telegram configuration; malformed legacy entries remain inspectable."""

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class Extensible(BaseModel):
    model_config = ConfigDict(extra="allow")


class Control(Extensible):
    enabled: bool = False
    enabled_at: str | None = None
    bot_id: str | None = None


class Owner(Extensible):
    chat_id: str | None = None
    source: Literal["imported", "bound"] | None = None
    bound_at: str | None = None


class Notify(Extensible):
    include_details: bool = False
    ui_runs_to_owner: bool = True


class ACLGroup(Extensible):
    id: str = ""
    name: str = ""
    can_run: bool = False
    can_stop: bool = False
    can_status: bool = True
    can_rollback: bool = False
    task_ids: list[str] = Field(default_factory=list)


class ACLMember(Extensible):
    id: str
    group_id: str
    chat_id: str | None = None
    username: str | None = None
    user_id: str | None = None
    label: str = ""


class TelegramConfig(Extensible):
    control: Control = Field(default_factory=Control)
    owner: Owner = Field(default_factory=Owner)
    notify: Notify = Field(default_factory=Notify)
    legacy_whitelist: list[JsonValue] = Field(default_factory=list)
    acl_groups: list[ACLGroup | JsonValue] = Field(default_factory=list)
    acl_members: list[ACLMember | JsonValue] = Field(default_factory=list)

    @field_validator("acl_groups", "acl_members", mode="before")
    @classmethod
    def typed_entries(cls, value, info):
        model = ACLGroup if info.field_name == "acl_groups" else ACLMember
        if not isinstance(value, list):
            raise ValueError("invalid ACL list")
        result = []
        for item in value:
            if isinstance(item, model):
                result.append(item)
                continue
            try:
                result.append(model.model_validate(item, strict=True))
            except ValueError:
                result.append(item)
        return result


def as_dict(item):
    return item.model_dump() if isinstance(item, BaseModel) else item


def migrate_telegram(legacy):
    """One normalizer for both direct S1 import and startup v1 migration."""
    raw = dict(legacy) if isinstance(legacy, dict) else {"invalid_legacy": legacy}
    control = raw.pop("control", {})
    control = dict(control) if isinstance(control, dict) else {}
    raw.pop("control_enabled", None)
    control.update(enabled=False, enabled_at=None, bot_id=None)
    owner = raw.pop("owner", {})
    owner = dict(owner) if isinstance(owner, dict) else {}
    chat = raw.pop("chat_id", owner.get("chat_id"))
    owner.update(
        chat_id=str(chat) if chat is not None else None,
        source="imported" if chat else None,
        bound_at=None,
    )
    notify = raw.pop("notify", {})
    notify = dict(notify) if isinstance(notify, dict) else {}
    details = raw.pop("notify_include_details", notify.get("include_details", False))
    notify.update(include_details=details is True, ui_runs_to_owner=True)
    whitelist = raw.pop("whitelist", raw.pop("legacy_whitelist", []))
    if not isinstance(whitelist, list):
        whitelist = [whitelist]
    raw.update(control=control, owner=owner, notify=notify, legacy_whitelist=whitelist)
    for key in ("acl_groups", "acl_members"):
        entries = raw.get(key, [])
        if not isinstance(entries, list):
            entries = [entries]
        if key == "acl_members":
            entries = [
                {**item, "id": item.get("id") or "acl_member:" + str(uuid.uuid4())}
                if isinstance(item, dict)
                else item
                for item in entries
            ]
        raw[key] = entries
    return TelegramConfig.model_validate(raw)


def config_v1_to_v2(raw):
    legacy = raw["imported"].pop("telegram", {})
    raw["telegram"] = migrate_telegram(legacy).model_dump()
    raw["schema_version"] = 2
    return raw


def numeric(value):
    return isinstance(value, str) and re.fullmatch(r"-?\d{1,20}", value) is not None


def username(value):
    return isinstance(value, str) and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", value) is not None


def acl_validity(config):
    """Return valid entries + warnings; ambiguous/over-limit entries grant nothing."""
    tg = config.telegram
    groups, members, warnings = [], [], []
    all_groups = [as_dict(g) for g in tg.acl_groups]
    all_members = [as_dict(m) for m in tg.acl_members]
    task_ids = {t.id for t in config.tasks.items}
    for i, g in enumerate(all_groups):
        valid = isinstance(g, dict)
        if valid:
            valid = (
                i < 50
                and isinstance(g.get("id"), str)
                and bool(g["id"])
                and isinstance(g.get("name"), str)
                and 1 <= len(g["name"]) <= 64
                and sum(isinstance(x, dict) and x.get("id") == g["id"] for x in all_groups) == 1
                and sum(isinstance(x, dict) and x.get("name") == g["name"] for x in all_groups) == 1
                and all(
                    type(g.get(k, d)) is bool
                    for k, d in (
                        ("can_run", False),
                        ("can_stop", False),
                        ("can_status", True),
                        ("can_rollback", False),
                    )
                )
                and isinstance(g.get("task_ids", []), list)
                and len(g.get("task_ids", [])) <= 200
                and all(isinstance(t, str) for t in g.get("task_ids", []))
                and len(set(g.get("task_ids", []))) == len(g.get("task_ids", []))
            )
        if not valid:
            warnings.append(f"ACL 组 #{i + 1} 无效、重复或超限，不参与授权")
            continue
        group = ACLGroup.model_validate(g)
        if (group.can_run or group.can_rollback) and not group.task_ids:
            warnings.append("该组已无可运行任务")
        if any(t not in task_ids for t in group.task_ids):
            warnings.append(f"ACL 组 #{i + 1} 引用不存在的任务")
        group.task_ids = [t for t in group.task_ids if t in task_ids]
        groups.append(group)
    gids = {g.id for g in groups}
    for i, m in enumerate(all_members):
        valid = isinstance(m, dict)
        if valid:
            chat, un, uid = m.get("chat_id"), m.get("username"), m.get("user_id")
            valid = (
                i < 500
                and isinstance(m.get("id"), str)
                and bool(m["id"])
                and m.get("group_id") in gids
                and isinstance(m.get("label", ""), str)
                and len(m.get("label", "")) <= 64
                and bool(chat or un)
                and (chat is None or numeric(chat))
                and (un is None or username(un))
                and (uid is None or numeric(uid))
                and sum(isinstance(x, dict) and x.get("id") == m["id"] for x in all_members) == 1
            )
            for key, value in (("chat_id", chat), ("username", un), ("user_id", uid)):
                if value is not None:
                    valid = (
                        valid
                        and sum(
                            isinstance(x, dict)
                            and isinstance(x.get(key), str)
                            and x[key].lower() == str(value).lower()
                            for x in all_members
                        )
                        == 1
                    )
        if not valid:
            warnings.append(f"ACL 成员 #{i + 1} 无效、重复或超限，不参与授权")
            continue
        members.append(ACLMember.model_validate(m))
    for i, entry in enumerate(tg.legacy_whitelist):
        if (
            i >= 500
            or not (numeric(entry) or username(entry))
            or (
                isinstance(entry, str)
                and sum(
                    isinstance(x, str) and x.lower() == entry.lower() for x in tg.legacy_whitelist
                )
                != 1
            )
        ):
            warnings.append(f"旧白名单 #{i + 1} 无效、重复或超限，不参与授权")
    if tg.owner.chat_id and not numeric(tg.owner.chat_id):
        warnings.append("旧 owner chat_id 无效，不参与授权")
    return groups, members, warnings


class RunOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ui", "telegram"] = "ui"
    bot_id: str | None = None
    chat_id: str | None = None
    user_id: str | None = None
    username_snapshot: str | None = Field(default=None, max_length=33)
    action_token: str | None = Field(default=None, max_length=64)
