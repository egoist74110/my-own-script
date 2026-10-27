"""VPN preferences. Credentials and runtime state intentionally live elsewhere."""

import copy
import os
import re
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VpnClient(Model):
    bundle_id: str = "com.safervpn.osx.smb"
    app_name: str | None = None
    url_scheme: Literal["HarmonySASE", "CheckPointSASE"] = "CheckPointSASE"

    @field_validator("bundle_id")
    @classmethod
    def safe_bundle(cls, value):
        if len(value) > 200 or not re.fullmatch(r"[A-Za-z0-9.-]+", value):
            raise ValueError("invalid client bundle id")
        return value


class VpnLogin(Model):
    workspace: str = Field(default="", max_length=200)
    residency: Literal[
        "US Data Residency",
        "EU Data Residency",
        "India Data Residency",
        "Australia Data Residency",
        "CA Data Residency",
    ] = "US Data Residency"
    email: str = Field(default="", max_length=200)
    totp_filter: str = "Perimeter"
    headless: bool = True

    @field_validator("workspace", "email", "totp_filter")
    @classmethod
    def no_controls(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("control characters are forbidden")
        return value


def tunnel_prefix(value: str) -> str:
    if not re.fullmatch(r"(?:\d{1,3}\.){2,3}", value):
        raise ValueError("invalid tunnel prefix")
    numbers = [int(part) for part in value.rstrip(".").split(".")]
    if any(part > 255 for part in numbers):
        raise ValueError("invalid tunnel prefix")
    return value


def chrome_path(value: str | None) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute() or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid Chrome path")
    try:
        info = path.stat()
    except OSError:
        raise ValueError("invalid Chrome path") from None
    if (
        not path.is_file()
        or not os.access(path, os.X_OK)
        or info.st_uid not in {os.getuid(), 0}
        or info.st_mode & stat.S_IWOTH
    ):
        raise ValueError("invalid Chrome path")
    return str(path)


class VpnConfig(Model):
    client: VpnClient = Field(default_factory=VpnClient)
    tunnel_prefix: str = "10.254."
    login: VpnLogin = Field(default_factory=VpnLogin)
    window_automation: Literal["off", "connect", "connect_update"] = "off"
    rung_timeout_s: int = Field(default=30, ge=5, le=120)
    login_timeout_s: int = Field(default=75, ge=30, le=300)
    max_run_s: int = Field(default=480, ge=120, le=1200)
    chrome_path: str | None = None

    @field_validator("tunnel_prefix")
    @classmethod
    def valid_tunnel_prefix(cls, value):
        return tunnel_prefix(value)

    @field_validator("chrome_path")
    @classmethod
    def valid_chrome_path(cls, value):
        return chrome_path(value)


def config_v5_to_v6(raw: dict) -> dict:
    result = copy.deepcopy(raw)
    result["schema_version"] = 6
    result.setdefault("vpn", VpnConfig().model_dump())
    return result
