"""Lark MCP 客户端接入配置生成。

Lark MCP 现为**共享 streamable HTTP 单实例**(由 App 托管,根治 20038 并发刷新)。
各 AI CLI 不再各自 spawn 进程,而是统一连同一个 URL。所有客户端首次连接会走一次
MCP OAuth(浏览器授权)。
"""

from __future__ import annotations

import json
from pathlib import Path


def tool_workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _http_url() -> str:
    # 延迟 import 避免与 store 的潜在循环
    from app_lark.store import lark_mcp_http_url, load_lark_settings, DEFAULT_OAUTH_PORT

    s = load_lark_settings()
    return lark_mcp_http_url(int(s.oauth_port or DEFAULT_OAUTH_PORT))


# 旧 stdio wrapper 路径,保留给"仍在用命令式接入"的回退/排错(已不是推荐接入方式)。
def lark_mcp_python() -> str:
    venv_python = tool_workspace_root() / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python"


def lark_mcp_server_script() -> str:
    return str(tool_workspace_root() / "app_lark" / "mcp_lark_server.py")


def lark_mcp_launch_command() -> str:
    """"复制启动命令"按钮:共享 HTTP 模式下复制的是客户端要连的 URL。"""
    return _http_url()


def lark_mcp_claude_cli_command() -> str:
    return f"claude mcp add --scope user --transport http lark {_http_url()}"


def lark_mcp_codex_toml() -> str:
    return (
        "[mcp_servers.lark]\n"
        f'url = "{_http_url()}"\n'
        "# 需要支持 streamable HTTP MCP 的 Codex 版本\n"
    )


def lark_mcp_gemini_json_fragment() -> str:
    # Gemini CLI: streamable HTTP 用 httpUrl 字段
    payload = {"lark": {"httpUrl": _http_url()}}
    return json.dumps(payload, ensure_ascii=False, indent=2)
