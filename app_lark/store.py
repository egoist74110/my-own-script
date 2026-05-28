from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app_ado.store import APP_ID, config_dir


DEFAULT_DOMAIN = "https://open.larksuite.com"
DEFAULT_TOOLS = "preset.doc.default"
DEFAULT_OAUTH_PORT = 3000
# 文档读 + 搜索接口需要 UAT,offline_access 拿 refresh token,wiki/docx 读权限
DEFAULT_SCOPE = "offline_access docx:document wiki:wiki"


class LarkSettings(BaseModel):
    app_id: str = ""
    domain: str = DEFAULT_DOMAIN
    tools: str = DEFAULT_TOOLS
    language: str = "zh"
    token_mode: str = "user_access_token"
    oauth_port: int = DEFAULT_OAUTH_PORT
    scope: str = DEFAULT_SCOPE


def lark_settings_path() -> Path:
    return config_dir() / "lark_settings.yaml"


def lark_login_state_path() -> Path:
    return config_dir() / "lark_login_state.json"


def load_lark_login_state() -> dict:
    p = lark_login_state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def save_lark_login_state(state: dict) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    p = lark_login_state_path()
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    return p


def clear_lark_login_state() -> None:
    p = lark_login_state_path()
    if p.exists():
        p.unlink()


def is_logged_in(app_id: str) -> bool:
    if not app_id:
        return False
    s = load_lark_login_state()
    return bool(s.get("app_id") == app_id and s.get("logged_in_at"))


def oauth_redirect_url(port: int) -> str:
    return f"http://localhost:{port}/callback"


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


def load_lark_settings() -> LarkSettings:
    p = lark_settings_path()
    if not p.exists():
        return LarkSettings()
    raw = _load(p.read_text("utf-8")) or {}
    return LarkSettings.model_validate(raw)


def save_lark_settings(s: LarkSettings) -> Path:
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    p = lark_settings_path()
    p.write_text(_dump(s.model_dump()), "utf-8")
    return p


__all__ = [
    "APP_ID",
    "DEFAULT_DOMAIN",
    "DEFAULT_TOOLS",
    "LarkSettings",
    "lark_settings_path",
    "load_lark_settings",
    "save_lark_settings",
]
