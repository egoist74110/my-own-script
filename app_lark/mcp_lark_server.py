"""Lark MCP server 入口:wrapper 形态 —— 从项目配置/keyring 读凭据,
然后 exec 官方 @larksuiteoapi/lark-mcp 走 stdio。

可直接被 Claude Code / Codex / Gemini CLI 当作 MCP server 命令调用。
"""

from __future__ import annotations

import os
import shutil
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app_lark.secrets import get_app_secret
from app_lark.store import (
    DEFAULT_DOMAIN,
    DEFAULT_OAUTH_PORT,
    DEFAULT_TOOLS,
    is_logged_in,
    load_lark_settings,
)


def _die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"[lark-mcp wrapper] {msg}\n")
    sys.exit(code)


def main() -> None:
    s = load_lark_settings()

    app_id = (s.app_id or "").strip()
    if not app_id:
        _die("未配置 App ID。请在 UI > MCP配置 > Lark MCP 卡里填写并保存。")

    secret = get_app_secret(app_id)
    if not secret:
        _die(f"找不到 App Secret(App ID={app_id})。请在 UI 里填写后保存到 keyring。")

    if not is_logged_in(app_id):
        _die("未登录。搜索 / 深度文档读取需要 user_access_token,请在 UI > MCP配置 > Lark MCP 点 \"登录\" 完成 OAuth 授权后再启动。", code=3)

    npx = shutil.which("npx")
    if not npx:
        _die("未找到 npx。需要先装 Node.js(brew install node)。")

    # 强制 user_access_token:搜索 / 深度文档读取走 UAT,tenant 模式部分接口直接 404
    token_mode = "user_access_token"
    port = int(s.oauth_port or DEFAULT_OAUTH_PORT)

    argv = [
        npx,
        "-y",
        "@larksuiteoapi/lark-mcp",
        "mcp",
        "-a", app_id,
        "-s", secret,
        "-d", (s.domain or DEFAULT_DOMAIN).strip(),
        "-t", (s.tools or DEFAULT_TOOLS).strip(),
        "-m", "stdio",
        "--token-mode", token_mode,
        "-l", (s.language or "zh").strip(),
        "--oauth",
        "-p", str(port),
    ]

    os.execvp(npx, argv)


if __name__ == "__main__":
    main()
