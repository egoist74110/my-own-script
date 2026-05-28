from __future__ import annotations

import json
import shlex
from pathlib import Path


def tool_workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def lark_mcp_python() -> str:
    venv_python = tool_workspace_root() / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python"


def lark_mcp_server_script() -> str:
    return str(tool_workspace_root() / "app_lark" / "mcp_lark_server.py")


def lark_mcp_launch_command() -> str:
    return f"{lark_mcp_python()} {shlex.quote(lark_mcp_server_script())}"


def lark_mcp_claude_cli_command() -> str:
    py = lark_mcp_python()
    script = lark_mcp_server_script()
    return f"claude mcp add lark --scope user -- {shlex.quote(py)} {shlex.quote(script)}"


def lark_mcp_codex_toml() -> str:
    py = lark_mcp_python()
    script = lark_mcp_server_script()
    return (
        "[mcp_servers.lark]\n"
        f'command = "{py}"\n'
        f'args = ["{script}"]\n'
    )


def lark_mcp_gemini_json_fragment() -> str:
    py = lark_mcp_python()
    script = lark_mcp_server_script()
    payload = {"lark": {"command": py, "args": [script]}}
    return json.dumps(payload, ensure_ascii=False, indent=2)
