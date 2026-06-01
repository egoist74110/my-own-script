from __future__ import annotations

import json
import shlex
from pathlib import Path


def tool_workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def figma_mcp_python() -> str:
    venv_python = tool_workspace_root() / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python"


def figma_mcp_server_script() -> str:
    return str(tool_workspace_root() / "app_figma" / "mcp_figma_server.py")


def figma_mcp_launch_command() -> str:
    return f"{figma_mcp_python()} {shlex.quote(figma_mcp_server_script())}"


def figma_mcp_claude_cli_command() -> str:
    py = figma_mcp_python()
    script = figma_mcp_server_script()
    return f"claude mcp add figma --scope user -- {shlex.quote(py)} {shlex.quote(script)}"


def figma_mcp_codex_toml() -> str:
    py = figma_mcp_python()
    script = figma_mcp_server_script()
    return (
        "[mcp_servers.figma]\n"
        f'command = "{py}"\n'
        f'args = ["{script}"]\n'
    )


def figma_mcp_gemini_json_fragment() -> str:
    py = figma_mcp_python()
    script = figma_mcp_server_script()
    payload = {"figma": {"command": py, "args": [script]}}
    return json.dumps(payload, ensure_ascii=False, indent=2)
