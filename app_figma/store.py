"""Figma MCP 的轻量本地设置:记录 token 的"设置日期 + 有效期天数"，用来估算剩余有效期。

Figma 已取消 PAT 的"永不过期"选项，最长 90 天。token 本身不含过期信息、
/v1/me 也不返回过期时间，所以必须在用户保存 token 时把"设了多少天"记下来，
才能在页面上显示"还剩 X 天"并临期提醒。token 明文仍只存系统钥匙串(见 secrets.py)。
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from app_ado.store import config_dir


DEFAULT_EXPIRY_DAYS = 90
# Figma 当前允许的 PAT 有效期档位(天)
EXPIRY_DAY_CHOICES = (1, 7, 30, 90)


def figma_settings_path() -> Path:
    return config_dir() / "figma_settings.yaml"


def _dump(obj: Any) -> str:
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)
    except Exception:
        return json.dumps(obj, ensure_ascii=False, indent=2)


def _load(text: str) -> Any:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except Exception:
        return json.loads(text)


def load_figma_settings() -> dict:
    p = figma_settings_path()
    if not p.exists():
        return {}
    try:
        return _load(p.read_text("utf-8")) or {}
    except Exception:
        return {}


def save_figma_settings(d: dict) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    p = figma_settings_path()
    p.write_text(_dump(d), "utf-8")
    return p


def record_token_set(expiry_days: int = DEFAULT_EXPIRY_DAYS) -> Path:
    """用户保存了新 token 时调用:记录设置时刻与有效期天数。"""
    return save_figma_settings(
        {
            "token_set_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "expiry_days": int(expiry_days),
        }
    )


def figma_expiry_date() -> _dt.datetime | None:
    """根据记录的设置日期 + 有效期天数算出到期时刻;没记录则 None。"""
    d = load_figma_settings()
    set_at = d.get("token_set_at")
    days = d.get("expiry_days")
    if not set_at or not isinstance(days, int):
        return None
    try:
        base = _dt.datetime.fromisoformat(str(set_at))
    except Exception:
        return None
    return base + _dt.timedelta(days=days)


__all__ = [
    "DEFAULT_EXPIRY_DAYS",
    "EXPIRY_DAY_CHOICES",
    "figma_settings_path",
    "load_figma_settings",
    "save_figma_settings",
    "record_token_set",
    "figma_expiry_date",
]
