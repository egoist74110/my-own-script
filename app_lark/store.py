from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app_ado.store import APP_ID, config_dir


DEFAULT_DOMAIN = "https://open.larksuite.com"

# preset.doc.default 只装了 6 个工具，且没有任何"列文档 block"和"下载原图"的能力
# (rawContent 遇到图片只会吐占位符)。为了让 AI 能真读图，额外补两个：
#   - docx.v1.documentBlock.list ······· 列文档所有 block，从中拿图片 block 的 image.token
#   - drive.v1.media.batchGetTmpDownloadUrl  把 image_token 批量换成有时效的下载 URL
# 链路：wiki getNode → docx token → block.list 找 image → batchGetTmpDownloadUrl → URL → AI 下载并识图
DEFAULT_TOOLS = (
    "preset.doc.default,"
    "docx.v1.documentBlock.list,"
    "drive.v1.media.batchGetTmpDownloadUrl"
)
DEFAULT_OAUTH_PORT = 3000
# 共享 HTTP(streamable)模式监听地址。host 用 localhost 与已登记的 OAuth 重定向 URL 对齐。
DEFAULT_HTTP_HOST = "localhost"
# 文档读 + 搜索 + 原图下载所需 scope；drive:drive 给图片 token → URL 用
DEFAULT_SCOPE = "offline_access docx:document wiki:wiki drive:drive"

# 旧版本写过的默认值，用来识别"用户没改过"并自动迁移
_LEGACY_DEFAULT_TOOLS = "preset.doc.default"
_LEGACY_DEFAULT_SCOPE = "offline_access docx:document wiki:wiki"


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


def lark_mcp_http_url(port: int | None = None) -> str:
    """共享 streamable HTTP 模式下，MCP 客户端要连的 URL。"""
    p = int(port or DEFAULT_OAUTH_PORT)
    return f"http://{DEFAULT_HTTP_HOST}:{p}/mcp"


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
    s = LarkSettings.model_validate(raw)
    # 自动迁移：旧版本用户没改过 tools / scope 的话，无痛升到新默认。
    # 用户自定义过的（与旧默认不完全相等）一律不动，避免覆盖他们的配置。
    if (s.tools or "").strip() == _LEGACY_DEFAULT_TOOLS:
        s.tools = DEFAULT_TOOLS
    if (s.scope or "").strip() == _LEGACY_DEFAULT_SCOPE:
        s.scope = DEFAULT_SCOPE
    return s


def _tokenize_scope(scope: str) -> set[str]:
    """Lark scope 用空格或逗号分隔，搁一起当成集合处理。"""
    if not scope:
        return set()
    raw = scope.replace(",", " ").split()
    return {t.strip() for t in raw if t.strip()}


def required_scope_tokens() -> set[str]:
    return _tokenize_scope(DEFAULT_SCOPE)


def saved_login_scope_tokens() -> set[str]:
    state = load_lark_login_state()
    return _tokenize_scope(str(state.get("scope") or ""))


def missing_login_scopes() -> set[str]:
    """已登录时缺哪些 scope。空集 = 当前 UAT 已覆盖；非空 = 该重新登录拿新 scope。"""
    state = load_lark_login_state()
    if not state.get("logged_in_at"):
        return set()
    return required_scope_tokens() - saved_login_scope_tokens()


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
