"""S6 configuration and pure v3 migration. No credentials are persisted here."""

import copy
import json
import logging
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

NODE_MIN_VERSION = "20.20.0"
MANAGED_NODE_VERSION = "v24.13.0"
DEFAULT_TOOLS = (
    "preset.doc.default,docx.v1.documentBlock.list,drive.v1.media.batchGetTmpDownloadUrl"
)
DEFAULT_SCOPE = "offline_access docx:document wiki:wiki drive:drive"


def package_versions():
    path = Path(__file__).resolve().parents[3] / "resources/mcp/package.json"
    return json.loads(path.read_text())["dependencies"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdoMcp(Model):
    allow_create_work_item: bool = False
    attachment_cache_mb: int = Field(default=500, ge=1, le=10000)
    attachment_max_mb: int = Field(default=25, ge=1, le=100)
    query_max_items: int = Field(default=200, ge=1, le=200)


class LoginMetadata(Model):
    logged_in_at: str | None = Field(default=None, max_length=80)
    scope: str | None = Field(default=None, max_length=4096)


class LarkMcp(Model):
    app_id: str = Field(default="", pattern=r"^[A-Za-z0-9_-]{0,128}$")
    domain: str = "https://open.larksuite.com"
    tools: str = DEFAULT_TOOLS
    language: Literal["zh", "en"] = "zh"
    port: int = Field(default=3000, ge=1024, le=65535)
    scope_hint: str = Field(default=DEFAULT_SCOPE, max_length=4096)
    owner_confirmed_at: str | None = None
    autostart: bool = False
    login: LoginMetadata = Field(default_factory=LoginMetadata)

    @field_validator("domain")
    @classmethod
    def domain_allowed(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"open.larksuite.com", "open.feishu.cn"}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid Lark domain")
        return value.rstrip("/")

    @field_validator("tools")
    @classmethod
    def tools_allowed(cls, value):
        parts = [p.strip() for p in value.split(",")]
        if not 1 <= len(parts) <= 40 or any(
            not re.fullmatch(r"[A-Za-z0-9_.]{1,80}", p) for p in parts
        ):
            raise ValueError("invalid Lark tools")
        return ",".join(parts)


class FigmaMcp(Model):
    token_set_at: str | None = Field(default=None, max_length=80)
    expiry_days: Literal[1, 7, 30, 90] = 90
    max_concurrency: int = Field(default=1, ge=1, le=10)
    min_interval_ms: int = Field(default=350, ge=0, le=60000)
    max_retry: int = Field(default=4, ge=0, le=10)


class NodeRuntime(Model):
    source: Literal["detected", "managed", "none"] = "none"
    path: str | None = None
    version: str | None = None


class Runtime(Model):
    node: NodeRuntime = Field(default_factory=NodeRuntime)
    packages: dict[str, str] = Field(default_factory=package_versions)

    @field_validator("packages")
    @classmethod
    def locked(cls, value):
        if value != package_versions():
            raise ValueError("packages must match lock")
        return value


class McpConfig(Model):
    ado: AdoMcp = Field(default_factory=AdoMcp)
    lark: LarkMcp = Field(default_factory=LarkMcp)
    figma: FigmaMcp = Field(default_factory=FigmaMcp)
    runtime: Runtime = Field(default_factory=Runtime)


def _import_fields(model, section, values):
    # Legacy data remains in imported.*. Validate each promoted field independently:
    # one invalid field must not discard valid siblings or block the S1 import.
    result = model()
    for key, value in values.items():
        try:
            candidate = model.model_validate({key: value})
        except ValidationError:
            logging.getLogger(__name__).warning(
                "invalid imported MCP field; default restored: %s", f"mcp.{section}.{key}"
            )
        else:
            setattr(result, key, getattr(candidate, key))
    return result


def imported_mcp(imported):
    lark = dict(imported.get("lark") or {})
    out = {k: lark[k] for k in ("app_id", "domain", "tools", "language") if k in lark}
    if "oauth_port" in lark:
        out["port"] = lark["oauth_port"]
    if "scope" in lark:
        out["scope_hint"] = lark["scope"]
    if str(out.get("tools", "")).strip() == "preset.doc.default":
        out["tools"] = DEFAULT_TOOLS
    if str(out.get("scope_hint", "")).strip() == "offline_access docx:document wiki:wiki":
        out["scope_hint"] = DEFAULT_SCOPE
    figma = dict(imported.get("figma") or {})
    return McpConfig(
        lark=_import_fields(LarkMcp, "lark", out),
        figma=_import_fields(
            FigmaMcp, "figma", {k: figma[k] for k in ("token_set_at", "expiry_days") if k in figma}
        ),
    )


def config_v3_to_v4(raw):
    result = copy.deepcopy(raw)
    result["schema_version"] = 4
    result["mcp"] = imported_mcp(result.get("imported", {})).model_dump()
    result.setdefault("ai", {}).setdefault("analysis", {})["mcp_source"] = "legacy"
    return result
