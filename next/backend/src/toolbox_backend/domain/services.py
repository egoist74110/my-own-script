"""S7 persistent preferences; runtime state and tunnel URLs are never persisted."""

import copy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceBinaries(Model):
    code_server: str | None = None
    cloudflared: str | None = None

    @field_validator("code_server", "cloudflared")
    @classmethod
    def absolute_path(cls, value):
        if value is not None and (
            not value.startswith("/") or len(value) > 4096 or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("absolute binary path required")
        return value


class CodeServerSettings(Model):
    start_timeout_s: float = Field(default=30, ge=0.1, le=120)


class CloudflaredSettings(Model):
    protocol: Literal["http2", "quic"] = "http2"
    max_tunnels: int = Field(default=5, ge=1, le=100)


class ServicesConfig(Model):
    binaries: ServiceBinaries = Field(default_factory=ServiceBinaries)
    code_server: CodeServerSettings = Field(default_factory=CodeServerSettings)
    cloudflared: CloudflaredSettings = Field(default_factory=CloudflaredSettings)


def config_v4_to_v5(raw: dict) -> dict:
    result = copy.deepcopy(raw)
    result["schema_version"] = 5
    result.setdefault("services", ServicesConfig().model_dump())
    return result
